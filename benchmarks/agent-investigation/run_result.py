from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

PROVIDER_PATTERNS = (
    (
        "provider_rate_limited",
        re.compile(
            r"\bHTTP(?:/\d(?:\.\d)?)?\s+429\b|\b(?:status(?:\s+code)?|error)\s*[:=]?\s*429\b|rate\s*limit(?:ed)?|overload(?:ed)?",
            re.I,
        ),
    ),
    (
        "provider_quota_exhausted",
        re.compile(
            r"\bHTTP(?:/\d(?:\.\d)?)?\s+402\b|\b(?:status(?:\s+code)?|error)\s*[:=]?\s*402\b|insufficient\s+balance|quota\s+(?:exhausted|exceeded)",
            re.I,
        ),
    ),
    (
        "provider_unavailable",
        re.compile(
            r"\bHTTP(?:/\d(?:\.\d)?)?\s+50[234]\b|\b(?:status(?:\s+code)?|error)\s*[:=]?\s*50[234]\b|service\s+unavailable|bad\s+gateway|gateway\s+timeout",
            re.I,
        ),
    ),
)

TRACECITE_TOOL_NAMES = frozenset(
    {
        "tracecite_run",
        "tracecite_retrieve",
        "tracecite_materialize",
        "tracecite_replay",
        "tracecite_aggregate",
        "tracecite_traverse",
        "tracecite_verify",
        "tracecite_search",
        "tracecite_expand",
    }
)
TRACECITE_NOVELTY_TOOL_NAMES = frozenset(
    {
        "tracecite_run",
        "tracecite_retrieve",
        "tracecite_materialize",
        "tracecite_replay",
        "tracecite_search",
        "tracecite_expand",
    }
)


def _read_text(path: Path | None) -> str:
    if path is None or not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _events(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.is_file():
        return []
    return _parse_jsonl_events(path.read_text(encoding="utf-8", errors="replace"))


def _parse_jsonl_events(text: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except Exception:
            continue
        if isinstance(item, dict):
            result.append(item)
    return result


def classify_provider_contamination(text: str) -> str | None:
    for name, pattern in PROVIDER_PATTERNS:
        if pattern.search(text):
            return name
    return None


def _assistant_error_payload(event: Mapping[str, Any]) -> tuple[Mapping[str, Any], str] | None:
    if str(event.get("type") or "").lower() != "message":
        return None
    message = event.get("message")
    if not isinstance(message, Mapping) or str(message.get("role") or "") != "assistant":
        return None
    error_fields: dict[str, Any] = {}
    for key in ("error", "errorMessage", "error_message"):
        value = message.get(key)
        if value not in (None, "", [], {}):
            error_fields[key] = value
    stop_reason = str(message.get("stopReason") or "")
    raw_stop_reason = str(message.get("rawStopReason") or "")
    error_stop = "error" in stop_reason.lower() or "error" in raw_stop_reason.lower()
    if not error_fields and not error_stop:
        return None
    payload: dict[str, Any] = dict(error_fields)
    if stop_reason:
        payload["stopReason"] = stop_reason
    if raw_stop_reason:
        payload["rawStopReason"] = raw_stop_reason
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return message, text


def _successful_assistant_child(event: Mapping[str, Any], parent_id: str) -> bool:
    if str(event.get("type") or "").lower() != "message":
        return False
    if str(event.get("parentId") or "") != parent_id:
        return False
    message = event.get("message")
    if not isinstance(message, Mapping) or str(message.get("role") or "") != "assistant":
        return False
    stop_reason = str(message.get("stopReason") or "").lower()
    raw_stop_reason = str(message.get("rawStopReason") or "").lower()
    if "error" in stop_reason or "error" in raw_stop_reason:
        return False
    if any(message.get(key) not in (None, "", [], {}) for key in ("error", "errorMessage", "error_message")):
        return False
    return message.get("content") not in (None, "", [], {})


def _provider_session_incidents(session_text: str) -> list[dict[str, Any]]:
    """Return structured provider failures and whether Pi recovered from each one.

    Pi records a retry recovery as a later successful assistant message whose
    ``parentId`` points at the assistant error event. A transient, recovered
    provider failure is still important observability, but it should not make a
    completed run invalid merely because the retry is preserved in session
    history.
    """

    events = _parse_jsonl_events(session_text)
    incidents: list[dict[str, Any]] = []
    for index, event in enumerate(events):
        parsed = _assistant_error_payload(event)
        if parsed is None:
            continue
        _message, diagnostic = parsed
        kind = classify_provider_contamination(diagnostic)
        if kind is None:
            continue
        event_id = str(event.get("id") or "")
        recovered = bool(event_id) and any(
            _successful_assistant_child(candidate, event_id)
            for candidate in events[index + 1 :]
        )
        incidents.append(
            {
                "kind": kind,
                "recovered": recovered,
                "event_id": event_id or None,
            }
        )
    return incidents


def _session_error_diagnostics(session_text: str) -> str:
    """Extract non-Evidence host diagnostics from session history."""

    diagnostics: list[str] = []
    for event in _parse_jsonl_events(session_text):
        event_type = str(event.get("type") or "").lower()
        if "error" in event_type:
            diagnostics.append(json.dumps(event, ensure_ascii=False, sort_keys=True))
            continue
        parsed = _assistant_error_payload(event)
        if parsed is not None:
            diagnostics.append(parsed[1])
    return "\n".join(diagnostics)


def _tracecite_shape(event: Mapping[str, Any]) -> tuple[bool, bool, bool]:
    name = str(event.get("name") or event.get("tool") or "")
    if name not in TRACECITE_TOOL_NAMES:
        return False, False, False
    output = event.get("output")
    if not isinstance(output, str):
        return True, False, False
    try:
        payload = json.loads(output)
    except Exception:
        return True, bool(output.strip()), False
    if not isinstance(payload, Mapping):
        return True, False, False

    status = str(payload.get("status") or "")
    if name not in TRACECITE_NOVELTY_TOOL_NAMES:
        return True, status in {"ok", "partial", "empty"}, False

    coverage = payload.get("coverage") if isinstance(payload.get("coverage"), Mapping) else {}
    evidence = payload.get("evidence") if isinstance(payload.get("evidence"), list) else []
    text = payload.get("text")
    new_evidence = coverage.get("new_evidence") if isinstance(coverage, Mapping) else None
    repeated = coverage.get("repeated_evidence") if isinstance(coverage, Mapping) else None
    added = bool(evidence) or bool(text) or (isinstance(new_evidence, int) and new_evidence > 0)
    low_novelty = status in {"no_match", "no_new_evidence"} or (
        isinstance(new_evidence, int)
        and new_evidence == 0
        and isinstance(repeated, int)
        and repeated > 0
    )
    return True, added, low_novelty


def trajectory_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    tool_events = [event for event in events if event.get("type") == "tool"]
    names = [str(event.get("name") or event.get("tool") or "unknown") for event in tool_events]
    counts = Counter(names)
    categories: Counter[str] = Counter()
    for event in tool_events:
        activity = event.get("activity")
        if isinstance(activity, Mapping):
            categories[str(activity.get("category") or "other")] += 1
        else:
            name = str(event.get("name") or event.get("tool") or "")
            if name in TRACECITE_TOOL_NAMES:
                categories["tracecite_evidence"] += 1
            elif name in {"grep", "find"}:
                categories["native_search"] += 1
            elif name == "read":
                categories["native_read"] += 1
            elif name == "bash":
                categories["opaque_shell"] += 1
            else:
                categories["native_other"] += 1

    first_core: int | None = None
    tracecite_calls = 0
    low_novelty = 0
    for index, event in enumerate(tool_events, start=1):
        is_tracecite, added, low = _tracecite_shape(event)
        if is_tracecite:
            tracecite_calls += 1
            low_novelty += int(low)
            if added and first_core is None:
                first_core = index

    final_event_index = next(
        (index for index, event in enumerate(events, start=1) if event.get("type") == "final"),
        None,
    )
    return {
        "tool_calls": len(tool_events),
        "tool_names": dict(sorted(counts.items())),
        "tool_categories": dict(sorted(categories.items())),
        "core_evidence_first_tool_index": first_core,
        "final_answer_after_tool_count": len(tool_events),
        "final_answer_event_index": final_event_index,
        "post_core_tool_calls": (len(tool_events) - first_core) if first_core is not None else None,
        "tracecite_evidence_calls": categories.get("tracecite_evidence", 0),
        "native_search_calls": categories.get("native_search", 0),
        "native_read_calls": categories.get("native_read", 0),
        "opaque_shell_calls": categories.get("opaque_shell", 0),
        "tracecite_low_novelty_calls": low_novelty,
        "tracecite_low_novelty_ratio": round(low_novelty / tracecite_calls, 4) if tracecite_calls else None,
    }


def _metric(mapping: Mapping[str, Any], key: str) -> int | None:
    value = mapping.get(key)
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def token_usage(score: Mapping[str, Any]) -> dict[str, Any]:
    context = score.get("context_cost") or {}
    if not isinstance(context, Mapping):
        context = {}
    fresh = _metric(context, "reported_input_tokens")
    cached = _metric(context, "reported_cached_input_tokens")
    output = _metric(context, "reported_output_tokens")
    fresh_plus_cached = fresh + cached if fresh is not None and cached is not None else None
    return {
        "fresh_input_tokens": fresh,
        "cached_input_tokens": cached,
        "fresh_plus_cached_input_tokens": fresh_plus_cached,
        "output_tokens": output,
        "model_calls": _metric(context, "model_calls"),
        "usage_source": context.get("usage_source"),
    }


def build_run_result(
    score: Mapping[str, Any],
    *,
    exit_code: int,
    stderr: str = "",
    session_text: str = "",
    transcript_text: str = "",
    transcript_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    _ = transcript_text
    incidents = _provider_session_incidents(session_text)
    unresolved_incidents = [item for item in incidents if not item["recovered"]]
    stderr_provider = classify_provider_contamination(stderr)
    provider_contamination = stderr_provider or (
        str(unresolved_incidents[0]["kind"]) if unresolved_incidents else None
    )

    # Agent runner timeouts surface via exit=124/stderr. Do not interpret a
    # recovered provider 504 preserved in session history as an Agent timeout.
    timed_out = exit_code == 124 or re.search(r"\b(?:timed out|timeout)\b", stderr, re.I) is not None
    if provider_contamination is not None:
        validity_reason = provider_contamination
    elif timed_out:
        validity_reason = "timeout"
    elif exit_code != 0:
        validity_reason = "host_exit_nonzero"
    else:
        validity_reason = "clean"
    valid = exit_code == 0 and provider_contamination is None and not timed_out
    events = transcript_events or []
    incident_counts = Counter(str(item["kind"]) for item in incidents)
    recovered_counts = Counter(str(item["kind"]) for item in incidents if item["recovered"])
    return {
        "schema_version": 2,
        "task_result": {
            "primary_evaluation": score.get("primary_evaluation") or {},
            "passed": score.get("passed"),
            "legacy_passed": score.get("legacy_passed"),
            "support_aware_passed": score.get("support_aware_passed", score.get("passed")),
            "quality": score.get("quality") or {},
            "context_cost": score.get("context_cost") or {},
            "failure": score.get("failure"),
        },
        "token_usage": token_usage(score),
        "run_validity": {
            "valid_for_comparison": valid,
            "reason": validity_reason,
            "exit_code": exit_code,
            "provider_contamination": provider_contamination,
            "provider_incidents": dict(sorted(incident_counts.items())),
            "provider_recovered_incidents": dict(sorted(recovered_counts.items())),
            "timeout": timed_out,
        },
        "trajectory": trajectory_summary(events),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build the canonical Pi benchmark task_result/run_validity contract.")
    parser.add_argument("--score", type=Path, required=True)
    parser.add_argument("--exit-code-file", type=Path, required=True)
    parser.add_argument("--stderr", type=Path)
    parser.add_argument("--session", type=Path)
    parser.add_argument("--transcript", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    score = _read_json(args.score)
    exit_code = int(args.exit_code_file.read_text(encoding="utf-8").strip())
    events = _events(args.transcript)
    result = build_run_result(
        score,
        exit_code=exit_code,
        stderr=_read_text(args.stderr),
        session_text=_read_text(args.session),
        transcript_text=_read_text(args.transcript),
        transcript_events=events,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
