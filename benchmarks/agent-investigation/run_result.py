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
    result: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
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


def _session_error_diagnostics(session_text: str) -> str:
    """Extract provider/host diagnostics without scanning Evidence or answer text."""

    diagnostics: list[str] = []
    for raw_line in session_text.splitlines():
        if not raw_line.strip():
            continue
        try:
            event = json.loads(raw_line)
        except Exception:
            continue
        if not isinstance(event, Mapping):
            continue

        event_type = str(event.get("type") or "").lower()
        if "error" in event_type:
            diagnostics.append(json.dumps(event, ensure_ascii=False, sort_keys=True))
            continue
        if event_type != "message":
            continue

        message = event.get("message")
        if not isinstance(message, Mapping) or str(message.get("role") or "") != "assistant":
            continue

        error_fields: dict[str, Any] = {}
        for key in ("error", "errorMessage", "error_message"):
            value = message.get(key)
            if value not in (None, "", [], {}):
                error_fields[key] = value

        stop_reason = str(message.get("stopReason") or "")
        raw_stop_reason = str(message.get("rawStopReason") or "")
        error_stop = "error" in stop_reason.lower() or "error" in raw_stop_reason.lower()
        if not error_fields and not error_stop:
            continue

        payload: dict[str, Any] = dict(error_fields)
        if stop_reason:
            payload["stopReason"] = stop_reason
        if raw_stop_reason:
            payload["rawStopReason"] = raw_stop_reason
        if error_stop and message.get("content") not in (None, "", [], {}):
            payload["content"] = message.get("content")
        diagnostics.append(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))
    return "\n".join(diagnostics)


def _tracecite_shape(event: Mapping[str, Any]) -> tuple[bool, bool, bool]:
    name = str(event.get("name") or event.get("tool") or "")
    if name not in {"tracecite_search", "tracecite_expand"}:
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
            if name in {"tracecite_search", "tracecite_expand"}:
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


def build_run_result(
    score: Mapping[str, Any],
    *,
    exit_code: int,
    stderr: str = "",
    session_text: str = "",
    transcript_text: str = "",
    transcript_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    # Transcript/final-answer text may legitimately contain HTTP-like numbers,
    # timeout words, or Evidence line numbers such as 429. Validity must be
    # derived only from host/provider diagnostics, never from task content.
    _ = transcript_text
    diagnostics = "\n".join((stderr, _session_error_diagnostics(session_text)))
    provider_contamination = classify_provider_contamination(diagnostics)
    timed_out = exit_code == 124 or re.search(r"\b(?:timed out|timeout)\b", diagnostics, re.I) is not None
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
    return {
        "schema_version": 1,
        "task_result": {
            "passed": score.get("passed"),
            "legacy_passed": score.get("legacy_passed"),
            "support_aware_passed": score.get("support_aware_passed", score.get("passed")),
            "quality": score.get("quality") or {},
            "context_cost": score.get("context_cost") or {},
            "failure": score.get("failure"),
        },
        "run_validity": {
            "valid_for_comparison": valid,
            "reason": validity_reason,
            "exit_code": exit_code,
            "provider_contamination": provider_contamination,
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
