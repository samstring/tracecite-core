from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

import gmi_host as base
import openai_host as common
from tracecite.integrations import cli as trace_cli
from tracecite.integrations.agent_projection import project
from tracecite.runtime import (
    EvidenceRequest,
    InvestigationStore,
    QueryTarget,
    RangeTarget,
    SourceTarget,
    retrieve,
)


_ORIGINAL_TOOLS_FOR_MODE = common._tools_for_mode
_ORIGINAL_POST_CHAT = base._post_chat
_CONTEXT_WINDOW_RE = re.compile(
    r"context window exceeds limit|context length exceeded|maximum context length|context_length_exceeded",
    re.IGNORECASE,
)
_HTTP_5XX_RE = re.compile(r"HTTP\s+5\d\d", re.IGNORECASE)
_MAX_GET_RADIUS = 8
_REQUEST_INDEX = 0
_DEFAULT_MAX_ROUNDS = 12
_DEFAULT_NO_GROWTH_ROUNDS = 2
_FINAL_ONLY_PROMPT = (
    "Evidence acquisition has stopped because the configured mechanical exploration limit was reached. "
    "Do not call more tools. Produce the best supported final root-cause answer from evidence already visible, "
    "cite precise source lines, and state unknown/partial where the evidence is insufficient."
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _host_failure_reason(exc: BaseException) -> str:
    if isinstance(exc, subprocess.TimeoutExpired):
        return "tool_timeout"
    message = str(exc)
    if _CONTEXT_WINDOW_RE.search(message):
        return "context_window_exceeded"
    lowered = message.casefold()
    if "http 402" in lowered or "insufficient balance" in lowered or "insufficient credit" in lowered:
        return "provider_insufficient_balance"
    if "http 429" in lowered:
        return "provider_rate_limited"
    if _HTTP_5XX_RE.search(message):
        return "provider_unavailable"
    return "host_error"


def _request_context_event(payload: Mapping[str, Any]) -> dict[str, Any]:
    global _REQUEST_INDEX
    _REQUEST_INDEX += 1
    serialized = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    messages = json.dumps(payload.get("messages") or [], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    tools = json.dumps(payload.get("tools") or [], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "type": "request_context",
        "request": _REQUEST_INDEX,
        "serialized_chars": len(serialized),
        "message_chars": len(messages),
        "tool_schema_chars": len(tools),
        "estimated_tokens_chars_div_4": (len(serialized) + 3) // 4,
    }


def _positive_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < 1:
        raise ValueError(f"{name} must be >= 1")
    return value


def _tool_output_payload(output: Any) -> Mapping[str, Any] | None:
    if isinstance(output, Mapping):
        return output
    if not isinstance(output, str):
        return None
    text = output.strip()
    start = text.find("{")
    if start < 0:
        return None
    try:
        payload = json.loads(text[start:])
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, Mapping) else None


def _tool_output_no_growth(output: Any) -> bool:
    """Return true only for an explicit mechanical stop, never substring hints.

    Fields such as ``frontier_exhausted: false`` appear in ordinary progress
    payloads, so string matching would incorrectly stop productive exploration.
    A no-match query also does not prove the source/frontier is exhausted.
    """

    payload = _tool_output_payload(output)
    if payload is None:
        return False
    status = str(payload.get("status") or "").strip().lower()
    if status == "no_new_evidence":
        return True
    data = payload.get("data") or {}
    if not isinstance(data, Mapping):
        return False
    stop = data.get("stop_reason") or {}
    if not isinstance(stop, Mapping):
        return False
    return str(stop.get("kind") or "").strip().lower() in {
        "source_exhausted",
        "frontier_exhausted",
    }


def _trailing_no_growth_rounds(messages: Sequence[Mapping[str, Any]]) -> int:
    index = len(messages) - 1
    rounds = 0
    while index >= 0:
        tool_outputs: list[Any] = []
        while index >= 0 and str(messages[index].get("role") or "") == "tool":
            tool_outputs.append(messages[index].get("content") or "")
            index -= 1
        if not tool_outputs:
            break
        if index < 0 or str(messages[index].get("role") or "") != "assistant":
            break
        assistant = messages[index]
        index -= 1
        if not assistant.get("tool_calls"):
            break
        if not all(_tool_output_no_growth(output) for output in tool_outputs):
            break
        rounds += 1
    return rounds


def _apply_stop_policy(payload: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    request = dict(payload)
    raw_messages = payload.get("messages") or []
    if not isinstance(raw_messages, list) or not payload.get("tools"):
        return request, None
    messages = [dict(item) for item in raw_messages if isinstance(item, Mapping)]
    if len(messages) != len(raw_messages):
        return request, None

    max_rounds = _positive_int_env("TRACECITE_BENCH_MAX_ROUNDS", _DEFAULT_MAX_ROUNDS)
    no_growth_limit = _positive_int_env(
        "TRACECITE_BENCH_NO_GROWTH_ROUNDS", _DEFAULT_NO_GROWTH_ROUNDS
    )
    assistant_rounds = sum(1 for item in messages if item.get("role") == "assistant")
    no_growth_rounds = _trailing_no_growth_rounds(messages)

    reason: str | None = None
    if no_growth_rounds >= no_growth_limit:
        reason = "consecutive_no_growth"
    elif assistant_rounds >= max_rounds:
        reason = "max_rounds"
    if reason is None:
        return request, None

    last = messages[-1] if messages else {}
    last_content = str(last.get("content") or "") if last.get("role") == "user" else ""
    if "Evidence acquisition has stopped" not in last_content and "previous assistant response hit" not in last_content:
        messages.append({"role": "user", "content": _FINAL_ONLY_PROMPT})
    request["messages"] = messages
    request.pop("tools", None)
    request.pop("tool_choice", None)
    return request, {
        "type": "protocol",
        "event": "force_final_only",
        "reason": reason,
        "assistant_rounds": assistant_rounds,
        "trailing_no_growth_rounds": no_growth_rounds,
        "max_rounds": max_rounds,
        "no_growth_limit": no_growth_limit,
    }


def _post_chat_measured(payload: Mapping[str, Any]) -> dict[str, Any]:
    transcript_value = os.environ.get("TRACECITE_BENCH_TRANSCRIPT", "").strip()
    request_payload, stop_event = _apply_stop_policy(payload)
    if transcript_value:
        transcript = Path(transcript_value)
        if stop_event is not None:
            common._append_event(transcript, stop_event)
        common._append_event(transcript, _request_context_event(request_payload))

    for attempt in range(3):
        try:
            return _ORIGINAL_POST_CHAT(request_payload)
        except RuntimeError as exc:
            message = str(exc)
            transient = any(f"HTTP {code}" in message for code in (429, 500, 502, 503, 504))
            if not transient or attempt >= 2:
                raise
            if transcript_value:
                common._append_event(
                    Path(transcript_value),
                    {
                        "type": "protocol",
                        "event": "provider_retry",
                        "attempt": attempt + 1,
                        "failure_reason": _host_failure_reason(exc),
                    },
                )
            time.sleep(2 ** attempt)
    raise AssertionError("unreachable")


class CanonicalRuntime(base.BenchmarkToolRuntime):
    """Thin benchmark adapter over the public canonical Runtime contract."""

    def __init__(self, *, mode: str, input_root: Path, scratch: Path, context_id: str) -> None:
        super().__init__(mode=mode, input_root=input_root, scratch=scratch, context_id=context_id)
        self._investigation_path = scratch / "canonical-investigation.json"
        if not self._investigation_path.exists():
            InvestigationStore(self._investigation_path).create("root-cause benchmark investigation")
        self._sha_by_file = {path.name: _sha256(path) for path in self.files}

    def _render(self, result: Any, *, prefix: str = "") -> str:
        payload = result.to_dict() if hasattr(result, "to_dict") else dict(result)
        view = project(payload, profile="agent")
        if view.get("operation") == "search":
            view = trace_cli._compact_search_result(view, max_output_chars=None)
        elif view.get("operation") == "expand":
            coverage = view.get("coverage") or {}
            evidence = view.get("evidence") or []
            if isinstance(coverage, Mapping) and isinstance(evidence, list) and evidence:
                first = evidence[0]
                if isinstance(first, Mapping):
                    source_name = Path(str(first.get("source_path") or "source")).name
                    start = coverage.get("context_start_line")
                    end = coverage.get("context_end_line")
                    if (
                        isinstance(start, int)
                        and not isinstance(start, bool)
                        and isinstance(end, int)
                        and not isinstance(end, bool)
                        and end >= start
                    ):
                        data = dict(view.get("data") or {})
                        data["visible_line_refs"] = [
                            f"{source_name}:{line}" for line in range(start, end + 1)
                        ]
                        view["data"] = data
        rendered = json.dumps(view, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return f"{prefix}\n{rendered}" if prefix else rendered

    def _tracecite_inspect(self, args: Mapping[str, Any]) -> str:
        file_name = str(args.get("file") or "")
        if not file_name:
            raise ValueError("file must be non-empty")
        path = common._safe_input(self.input_root, file_name)
        result = retrieve(
            EvidenceRequest(
                SourceTarget(path),
                investigation_path=self._investigation_path,
                cache=True,
            )
        )
        return self._render(result)

    def _tracecite_search(self, args: Mapping[str, Any]) -> str:
        file_name = str(args.get("file") or "")
        path = common._safe_input(self.input_root, file_name)
        query = str(args.get("query") or "").strip()
        if not query:
            raise ValueError("query must be non-empty")
        result = retrieve(
            EvidenceRequest(
                QueryTarget(
                    path,
                    query,
                    regex=bool(args.get("regex")),
                    snapshot=False,
                    max_evidence=None,
                    max_line_chars=None,
                ),
                investigation_path=self._investigation_path,
                cache=True,
            )
        )
        return self._render(result)

    def _tracecite_get(self, args: Mapping[str, Any]) -> str:
        file_name = str(args.get("file") or "")
        path = common._safe_input(self.input_root, file_name)
        try:
            line = int(args.get("line"))
            requested_radius = int(args.get("radius", 3))
        except (TypeError, ValueError) as exc:
            raise ValueError("line and radius must be integers") from exc
        if line < 1:
            raise ValueError("line must be >= 1")
        if requested_radius < 0:
            raise ValueError("radius must be >= 0")
        radius = min(requested_radius, _MAX_GET_RADIUS)
        prefix = ""
        if radius != requested_radius:
            prefix = f"@NORMALIZE radius_clamped_from={requested_radius} radius={radius}"
        result = retrieve(
            EvidenceRequest(
                RangeTarget(
                    path,
                    line,
                    before=radius,
                    after=radius,
                    expected_sha256=self._sha_by_file[file_name],
                    max_chars=20_000,
                ),
                investigation_path=self._investigation_path,
                cache=True,
            )
        )
        return self._render(result, prefix=prefix)

    def call(self, name: str, args: Mapping[str, Any]) -> str:
        if self.mode in {"tracecite", "tracecite_context"}:
            if name == "tracecite_inspect":
                return self._tracecite_inspect(args)
            if name == "tracecite_search":
                return self._tracecite_search(args)
            if name == "tracecite_get":
                return self._tracecite_get(args)
        return super().call(name, args)


def _tools_for_mode(mode: str, files: Sequence[Path]) -> list[dict[str, Any]]:
    if mode not in {"tracecite", "tracecite_context"}:
        return _ORIGINAL_TOOLS_FOR_MODE(mode, files)
    file_property = common._common_file_property(files)
    return [
        common._function_tool(
            "tracecite_inspect",
            (
                "Inspect one raw evidence source through TraceCite's canonical Runtime before forming a root-cause conclusion. "
                "This returns bounded source structure/coverage rather than dumping the whole source into model context."
            ),
            {"file": file_property},
            ["file"],
        ),
        common._function_tool(
            "tracecite_search",
            (
                "Search one source for a genuinely new semantic hypothesis through the canonical Runtime. "
                "Searches that return only previously seen Evidence produce NO_NEW_EVIDENCE."
            ),
            {
                "file": file_property,
                "query": {"type": "string"},
                "regex": {"type": "boolean"},
            },
            ["file", "query", "regex"],
        ),
        common._function_tool(
            "tracecite_get",
            (
                "Recover exact line-addressable context around a known line through the canonical Runtime. radius is bounded to 0-8; "
                "slight model overshoot is normalized to 8 instead of wasting a model turn."
            ),
            {
                "file": file_property,
                "line": {"type": "integer", "minimum": 1},
                "radius": {"type": "integer", "minimum": 0, "maximum": _MAX_GET_RADIUS},
            },
            ["file", "line", "radius"],
        ),
    ]


base.BenchmarkToolRuntime = CanonicalRuntime
base._post_chat = _post_chat_measured
common._tools_for_mode = _tools_for_mode


if __name__ == "__main__":
    try:
        raise SystemExit(base.run())
    except Exception as exc:
        transcript_value = os.environ.get("TRACECITE_BENCH_TRANSCRIPT", "").strip()
        failure_reason = _host_failure_reason(exc)
        if transcript_value:
            try:
                common._append_event(
                    Path(transcript_value),
                    {
                        "type": "host_error",
                        "error": type(exc).__name__,
                        "failure_reason": failure_reason,
                        "message": str(exc),
                    },
                )
            except Exception:
                pass
        print(
            f"benchmark host failed: reason={failure_reason} {type(exc).__name__}: {exc}",
            file=os.sys.stderr,
        )
        raise
