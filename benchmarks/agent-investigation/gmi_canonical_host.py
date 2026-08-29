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
from tracecite.integrations.agent_projection import DEFAULT_AGENT_MAX_OUTPUT_CHARS, project
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
_MAX_GET_RADIUS = 12
_MIN_GET_RADIUS = 12
_REQUEST_INDEX = 0
_DEFAULT_MAX_ROUNDS = 12
_DEFAULT_NO_GROWTH_ROUNDS = 2
_ACTION_PROMPT_MARKER = "TRACECITE_ACTION_REQUIRED"
_NAVIGATION_PROMPT_MARKER = "TRACECITE_COVERAGE_REQUIRED"
_CONSTRAINT_PROMPT_MARKER = "TRACECITE_CONSTRAINT_REQUIRED"
# Process-local protocol memory. A benchmark process owns one conversation,
# so this prevents re-injecting the same synthetic action prompt without
# leaking state across independent benchmark jobs/processes.
_PROMPTED_ACTIONS: set[tuple[str, str, str]] = set()
_PROMPTED_CONSTRAINTS: set[tuple[str, str, str]] = set()
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


def _action_from_tool_output(output: Any) -> dict[str, Any] | None:
    payload = _tool_output_payload(output)
    if payload is None:
        return None
    data = payload.get("data") or {}
    if not isinstance(data, Mapping):
        return None
    raw = data.get("actionable_retrieval")
    if not isinstance(raw, Mapping):
        return None
    operation = str(raw.get("operation") or "").strip()
    source = str(raw.get("source") or "").strip()
    query = str(raw.get("query") or "").strip()
    if operation != "search" or not source or not query:
        return None
    return {
        "operation": operation,
        "source": source,
        "query": query,
        "purpose": str(raw.get("purpose") or "").strip(),
        "gap_kind": str(raw.get("gap_kind") or "").strip(),
    }



def _original_question_text(messages: Sequence[Mapping[str, Any]]) -> str:
    parts: list[str] = []
    for message in messages:
        if str(message.get("role") or "") != "user":
            continue
        content = str(message.get("content") or "")
        if not content:
            continue
        if (
            _ACTION_PROMPT_MARKER in content
            or _NAVIGATION_PROMPT_MARKER in content
            or _CONSTRAINT_PROMPT_MARKER in content
        ):
            continue
        if "Evidence acquisition has stopped" in content or "previous assistant response hit" in content:
            continue
        parts.append(content)
    return "\n".join(parts)


def _question_aligned_navigation_from_tool_output(
    output: Any,
    question_text: str,
) -> dict[str, Any] | None:
    # Lexical coverage control only; this does not infer or rank a root cause.
    payload = _tool_output_payload(output)
    if payload is None:
        return None
    coverage = payload.get("coverage") or {}
    if not isinstance(coverage, Mapping) or not bool(coverage.get("evidence_truncated")):
        return None
    data = payload.get("data") or {}
    if not isinstance(data, Mapping):
        return None
    evidence_source = data.get("evidence_source") or {}
    if not isinstance(evidence_source, Mapping):
        return None
    source_path = str(evidence_source.get("path") or "").strip()
    if not source_path:
        return None
    question_folded = question_text.casefold()
    if not question_folded:
        return None
    for raw in payload.get("next_queries") or []:
        query = str(raw or "").strip()
        if len(query) < 3 or query.casefold() not in question_folded:
            continue
        return {
            "operation": "search",
            "source": Path(source_path).name,
            "query": query,
            "purpose": "cover_question_aligned_truncated_branch",
            "gap_kind": "truncated_question_coverage",
        }
    return None


def _integrity_constraint_from_tool_output(output: Any) -> dict[str, Any] | None:
    """Return one completed Runtime-owned correlation-safety invariant.

    This is evidence integrity only. It never says a collision happened and
    never chooses a root-cause hypothesis.
    """

    payload = _tool_output_payload(output)
    if payload is None:
        return None
    data = payload.get("data") or {}
    if not isinstance(data, Mapping):
        return None
    if isinstance(data.get("actionable_retrieval"), Mapping):
        return None
    for raw in data.get("correlation_constraints") or []:
        if not isinstance(raw, Mapping):
            continue
        if str(raw.get("kind") or "") != "scoped_local_identifier":
            continue
        if raw.get("identifier_only_correlation_safe") is not False:
            continue
        identifier_key = str(raw.get("identifier_key") or "").strip()
        identifier_value = str(raw.get("identifier_value") or "").strip()
        if not identifier_key or not identifier_value:
            continue
        sibling_count = int(raw.get("sibling_entity_count_observed") or 0)
        if sibling_count < 2:
            continue
        required = [
            str(item).strip()
            for item in raw.get("minimum_safe_correlation_key")
            or raw.get("required_correlation_components")
            or []
            if str(item).strip()
        ]
        entities = [
            str(item).strip()
            for item in raw.get("scoped_entities") or []
            if str(item).strip()
        ]
        return {
            "source": str((data.get("evidence_source") or {}).get("path") or "").strip(),
            "identifier_key": identifier_key,
            "identifier_value": identifier_value,
            "source_uniqueness": str(raw.get("source_uniqueness") or "unverified"),
            "required_correlation_components": required,
            "scoped_entities": entities,
            "sibling_entity_count_observed": sibling_count,
        }
    return None


def _constraint_signature(constraint: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(constraint.get("source") or "").strip(),
        str(constraint.get("identifier_key") or "").strip(),
        str(constraint.get("identifier_value") or "").strip(),
    )


def _constraint_prompt(constraint: Mapping[str, Any]) -> str:
    signature = "|".join(_constraint_signature(constraint))
    required = ", ".join(constraint.get("required_correlation_components") or [])
    observed = ", ".join(constraint.get("scoped_entities") or [])
    sibling_count = int(constraint.get("sibling_entity_count_observed") or 0)
    uniqueness = str(constraint.get("source_uniqueness") or "unverified")
    return (
        f"{_CONSTRAINT_PROMPT_MARKER} {signature}\n"
        "The canonical Runtime has completed its deterministic identity-evidence ladder and reports "
        "a correlation-safety constraint. This does NOT identify a root cause. Before concluding, "
        "explicitly test your causal hypothesis against this invariant: "
        f"{constraint['identifier_key']}={constraint['identifier_value']!r} is not safe as an "
        f"identifier-only correlation key (source uniqueness={uniqueness}); the minimum safe "
        f"correlation key is [{required}]. The source also contains {sibling_count} sibling scoped "
        f"entities in the same family"
        + (f", including [{observed}]" if observed else "")
        + ". Do not assume global identifier uniqueness. If your hypothesis involves lookup, routing, "
        "ownership, or correlation, distinguish identifier-only behavior from scope-preserving behavior "
        "and label any causal step as inference unless directly observed."
    )


def _pending_constraint_review(
    messages: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    pending: dict[str, Any] | None = None
    for message in messages:
        if str(message.get("role") or "") != "tool":
            continue
        constraint = _integrity_constraint_from_tool_output(message.get("content") or "")
        if constraint is not None:
            pending = constraint
    if pending is None:
        return None
    signature = _constraint_signature(pending)
    marker = f"{_CONSTRAINT_PROMPT_MARKER} {'|'.join(signature)}"
    if signature in _PROMPTED_CONSTRAINTS:
        return None
    if any(
        str(item.get("role") or "") == "user"
        and marker in str(item.get("content") or "")
        for item in messages
    ):
        return None
    return pending


def _apply_constraint_policy(
    payload: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    request = dict(payload)
    raw_messages = payload.get("messages") or []
    if not isinstance(raw_messages, list) or not payload.get("tools"):
        return request, None
    messages = [dict(item) for item in raw_messages if isinstance(item, Mapping)]
    if len(messages) != len(raw_messages):
        return request, None
    constraint = _pending_constraint_review(messages)
    if constraint is None:
        return request, None

    signature = _constraint_signature(constraint)
    _PROMPTED_CONSTRAINTS.add(signature)
    messages.append({"role": "user", "content": _constraint_prompt(constraint)})
    request["messages"] = messages
    return request, {
        "type": "protocol",
        "event": "require_correlation_constraint_review",
        "source": constraint.get("source") or "",
        "identifier_key": constraint["identifier_key"],
        "identifier_value": constraint["identifier_value"],
        "source_uniqueness": constraint.get("source_uniqueness") or "unverified",
        "required_correlation_components": constraint.get("required_correlation_components") or [],
        "sibling_entity_count_observed": constraint.get("sibling_entity_count_observed") or 0,
    }


def _tool_call_signature(call: Mapping[str, Any]) -> tuple[str, str, str] | None:
    function = call.get("function") or {}
    if not isinstance(function, Mapping):
        return None
    name = str(function.get("name") or "").strip()
    raw_arguments = function.get("arguments") or "{}"
    if isinstance(raw_arguments, Mapping):
        arguments = raw_arguments
    else:
        try:
            arguments = json.loads(str(raw_arguments))
        except json.JSONDecodeError:
            return None
    if not isinstance(arguments, Mapping):
        return None
    if name != "tracecite_search":
        return None
    source = str(arguments.get("file") or "").strip()
    query = str(arguments.get("query") or "").strip()
    if not source or not query:
        return None
    return ("search", source, query)


def _action_signature(action: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(action.get("operation") or "").strip(),
        str(action.get("source") or "").strip(),
        str(action.get("query") or "").strip(),
    )


def _pending_action(messages: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    """Return the newest Runtime action that has not yet been attempted once.

    An action is considered mechanically attempted when a later/equal canonical
    tool call uses the same operation, source and query. If that retrieval still
    leaves a semantic question open, the Agent may reason about it, but the host
    must not blindly repeat the same mechanical action forever.
    """

    attempted: set[tuple[str, str, str]] = set()
    pending: dict[str, Any] | None = None
    for message in messages:
        role = str(message.get("role") or "")
        if role == "assistant":
            for raw_call in message.get("tool_calls") or []:
                if not isinstance(raw_call, Mapping):
                    continue
                signature = _tool_call_signature(raw_call)
                if signature is not None:
                    attempted.add(signature)
                    if pending is not None and signature == _action_signature(pending):
                        pending = None
            continue
        if role != "tool":
            continue
        action = _action_from_tool_output(message.get("content") or "")
        if action is None:
            continue
        if _action_signature(action) not in attempted:
            pending = action
    return pending



def _pending_question_navigation(messages: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    attempted: set[tuple[str, str, str]] = set()
    pending: dict[str, Any] | None = None
    question_text = _original_question_text(messages)
    for message in messages:
        role = str(message.get("role") or "")
        if role == "assistant":
            for raw_call in message.get("tool_calls") or []:
                if not isinstance(raw_call, Mapping):
                    continue
                signature = _tool_call_signature(raw_call)
                if signature is not None:
                    attempted.add(signature)
                    if pending is not None and signature == _action_signature(pending):
                        pending = None
            continue
        if role != "tool":
            continue
        action = _question_aligned_navigation_from_tool_output(
            message.get("content") or "", question_text
        )
        if action is not None and _action_signature(action) not in attempted:
            pending = action
    return pending


def _navigation_prompt(action: Mapping[str, Any]) -> str:
    signature = "|".join(_action_signature(action))
    return (
        f"{_NAVIGATION_PROMPT_MARKER} {signature}\n"
        "The latest canonical search was truncated and Runtime exposed a next-query branch that is also "
        "explicitly named in the investigation question. Before concluding, cover that branch once: "
        f"tracecite_search(file={action['source']!r}, query={action['query']!r}, regex=false). "
        "This is lexical evidence-coverage completion only; it is not a causal or root-cause recommendation."
    )


def _action_prompt(action: Mapping[str, Any]) -> str:
    signature = "|".join(_action_signature(action))
    purpose = str(action.get("purpose") or "mechanical_evidence_gap_closure").strip()
    return (
        f"{_ACTION_PROMPT_MARKER} {signature}\n"
        "The canonical Runtime reports an unresolved actionable evidence gap. Before concluding or exploring "
        "unrelated queries, execute this mechanical gap-closing retrieval once: "
        f"tracecite_search(file={action['source']!r}, query={action['query']!r}, regex=false). "
        f"Purpose: {purpose}. This is evidence-integrity verification only; it is not a causal or root-cause recommendation."
    )


def _apply_action_policy(payload: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    request = dict(payload)
    raw_messages = payload.get("messages") or []
    if not isinstance(raw_messages, list) or not payload.get("tools"):
        return request, None
    messages = [dict(item) for item in raw_messages if isinstance(item, Mapping)]
    if len(messages) != len(raw_messages):
        return request, None
    action = _pending_action(messages)
    event_name = "prioritize_actionable_retrieval"
    prompt_builder = _action_prompt
    marker_prefix = _ACTION_PROMPT_MARKER
    if action is None:
        action = _pending_question_navigation(messages)
        event_name = "prioritize_question_aligned_coverage"
        prompt_builder = _navigation_prompt
        marker_prefix = _NAVIGATION_PROMPT_MARKER
    if action is None:
        return request, None

    action_signature = _action_signature(action)
    signature = "|".join(action_signature)
    marker = f"{marker_prefix} {signature}"
    already_prompted = action_signature in _PROMPTED_ACTIONS or any(
        str(item.get("role") or "") == "user" and marker in str(item.get("content") or "")
        for item in messages
    )
    if already_prompted:
        return request, None

    _PROMPTED_ACTIONS.add(action_signature)
    messages.append({"role": "user", "content": prompt_builder(action)})
    request["messages"] = messages
    return request, {
        "type": "protocol",
        "event": event_name,
        "operation": action["operation"],
        "source": action["source"],
        "query": action["query"],
        "purpose": action.get("purpose") or "",
        "gap_kind": action.get("gap_kind") or "",
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
    request_payload, action_event = _apply_action_policy(payload)
    constraint_event = None
    if action_event is None:
        request_payload, constraint_event = _apply_constraint_policy(request_payload)
    if action_event is None and constraint_event is None:
        request_payload, stop_event = _apply_stop_policy(request_payload)
    else:
        # Give a newly surfaced Runtime-owned mechanical action/constraint one
        # model turn before applying the exploration safety cap. If the model
        # ignores the one-time prompt, the normal cap applies next request.
        stop_event = None
    if transcript_value:
        transcript = Path(transcript_value)
        if action_event is not None:
            common._append_event(transcript, action_event)
        if constraint_event is not None:
            common._append_event(transcript, constraint_event)
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
            view = project(
                view,
                profile="portable-json",
                max_output_chars=DEFAULT_AGENT_MAX_OUTPUT_CHARS,
            )
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
        radius = (
            0
            if requested_radius == 0
            else min(_MAX_GET_RADIUS, max(_MIN_GET_RADIUS, requested_radius))
        )
        prefix = ""
        if radius != requested_radius:
            direction = "expanded" if radius > requested_radius else "clamped"
            prefix = f"@NORMALIZE radius_{direction}_from={requested_radius} radius={radius}"
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
                "Searches that return only previously seen Evidence produce NO_NEW_EVIDENCE. If canonical output reports "
                "data.actionable_retrieval, execute that mechanical gap-closing action before unrelated exploration or conclusion."
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
                "Recover exact line-addressable context around a known line through the canonical Runtime. radius=0 is exact-line; any positive radius is normalized to a 12-line evidence neighborhood for fidelity. "
                "This preserves adjacent correlated evidence without requiring the model to guess a larger radius. If canonical output reports "
                "data.actionable_retrieval, execute that mechanical gap-closing action before unrelated exploration or conclusion."
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
