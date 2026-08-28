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


def _post_chat_measured(payload: Mapping[str, Any]) -> dict[str, Any]:
    transcript_value = os.environ.get("TRACECITE_BENCH_TRANSCRIPT", "").strip()
    if transcript_value:
        common._append_event(Path(transcript_value), _request_context_event(payload))

    for attempt in range(3):
        try:
            return _ORIGINAL_POST_CHAT(payload)
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
    """Thin benchmark adapter over the public canonical Runtime contract.

    The benchmark owns only tool naming and model transport. Evidence novelty,
    range coverage, source-version safety and deterministic stop semantics are
    delegated to ``tracecite.runtime.retrieve`` and persisted through one
    InvestigationState. This prevents the benchmark adapter from becoming a
    second, smarter implementation of TraceCite.
    """

    def __init__(self, *, mode: str, input_root: Path, scratch: Path, context_id: str) -> None:
        super().__init__(mode=mode, input_root=input_root, scratch=scratch, context_id=context_id)
        self._investigation_path = scratch / "canonical-investigation.json"
        if not self._investigation_path.exists():
            InvestigationStore(self._investigation_path).create("root-cause benchmark investigation")
        self._sha_by_file = {path.name: _sha256(path) for path in self.files}

    def _render(self, result: Any, *, prefix: str = "") -> str:
        payload = result.to_dict() if hasattr(result, "to_dict") else dict(result)
        frame = trace_cli.render_frame(project(payload, profile="agent"))
        return f"{prefix}\n{frame}" if prefix else frame

    def _tracecite_inspect(self, args: Mapping[str, Any]) -> str:
        file_name = str(args.get("file") or "")
        if not file_name:
            raise ValueError("file must be non-empty")
        path = common._safe_input(self.input_root, file_name)
        result = retrieve(
            EvidenceRequest(
                QueryTarget(
                    path,
                    ".*",
                    regex=True,
                    snapshot=False,
                    max_evidence=None,
                    max_line_chars=None,
                ),
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
                "Repeated evidence is mechanically suppressed by the linked InvestigationState."
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
                "Recover exact context around a known line through the canonical Runtime. radius is bounded to 0-8; "
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
