from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _number(value: Any) -> int | float | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _reduction(shell: Any, trace: Any) -> float | None:
    shell = _number(shell)
    trace = _number(trace)
    if shell is None or trace is None or shell == 0:
        return None
    return round(1.0 - trace / shell, 6)


def _ratio(shell: Any, trace: Any) -> float | None:
    shell = _number(shell)
    trace = _number(trace)
    if shell is None or trace is None or trace == 0:
        return None
    return round(shell / trace, 4)


def aggregate(root: Path) -> dict[str, Any]:
    records = []
    for path in sorted(root.rglob("outcome.json")):
        try:
            records.append(_load(path))
        except Exception:
            continue

    pairs: dict[str, dict[str, dict[str, Any]]] = {}
    for row in records:
        case_id = str(row.get("case_id") or "unknown")
        mode = str(row.get("mode") or "unknown")
        pairs.setdefault(case_id, {})[mode] = row

    comparisons: list[dict[str, Any]] = []
    for case_id in sorted(pairs):
        pair = pairs[case_id]
        shell = pair.get("free_shell") or {}
        trace = pair.get("tracecite") or {}
        sc = shell.get("context_cost") or {}
        tc = trace.get("context_cost") or {}
        comparisons.append(
            {
                "case_id": case_id,
                "scorer": shell.get("scorer") or trace.get("scorer"),
                "free_shell_status": shell.get("run_status"),
                "tracecite_status": trace.get("run_status"),
                "free_shell_failure_reason": shell.get("host_failure_reason"),
                "tracecite_failure_reason": trace.get("host_failure_reason"),
                "free_shell_attempts": shell.get("attempts"),
                "tracecite_attempts": trace.get("attempts"),
                "free_shell_provider_retries": shell.get("provider_retries", 0),
                "tracecite_provider_retries": trace.get("provider_retries", 0),
                "free_shell_passed": shell.get("passed"),
                "tracecite_passed": trace.get("passed"),
                "primary_quality_name": shell.get("primary_quality_name") or trace.get("primary_quality_name"),
                "free_shell_primary_quality": shell.get("primary_quality"),
                "tracecite_primary_quality": trace.get("primary_quality"),
                "free_shell_input_tokens": sc.get("reported_input_tokens"),
                "tracecite_input_tokens": tc.get("reported_input_tokens"),
                "input_token_reduction": _reduction(sc.get("reported_input_tokens"), tc.get("reported_input_tokens")),
                "shell_over_tracecite_input_ratio": _ratio(sc.get("reported_input_tokens"), tc.get("reported_input_tokens")),
                "free_shell_tool_output_chars": sc.get("tool_output_chars"),
                "tracecite_tool_output_chars": tc.get("tool_output_chars"),
                "tool_output_reduction": _reduction(sc.get("tool_output_chars"), tc.get("tool_output_chars")),
                "shell_over_tracecite_tool_output_ratio": _ratio(sc.get("tool_output_chars"), tc.get("tool_output_chars")),
                "free_shell_cumulative_context_chars": sc.get("cumulative_attempted_context_chars"),
                "tracecite_cumulative_context_chars": tc.get("cumulative_attempted_context_chars"),
                "cumulative_context_reduction": _reduction(sc.get("cumulative_attempted_context_chars"), tc.get("cumulative_attempted_context_chars")),
                "free_shell_peak_context_chars": sc.get("peak_attempted_context_chars"),
                "tracecite_peak_context_chars": tc.get("peak_attempted_context_chars"),
                "peak_context_reduction": _reduction(sc.get("peak_attempted_context_chars"), tc.get("peak_attempted_context_chars")),
            }
        )

    valid = [
        row
        for row in comparisons
        if row["free_shell_status"] in {"ok", "incomplete"}
        and row["tracecite_status"] in {"ok", "incomplete"}
    ]
    token_pairs = [
        row
        for row in valid
        if _number(row["free_shell_input_tokens"]) is not None
        and _number(row["tracecite_input_tokens"]) is not None
    ]
    shell_tokens = sum(int(row["free_shell_input_tokens"]) for row in token_pairs)
    trace_tokens = sum(int(row["tracecite_input_tokens"]) for row in token_pairs)
    shell_tool = sum(int(row["free_shell_tool_output_chars"] or 0) for row in valid)
    trace_tool = sum(int(row["tracecite_tool_output_chars"] or 0) for row in valid)

    # Correctness is a hard product boundary: if the baseline Agent can solve a
    # case, TraceCite must not turn that success into a failed answer or host
    # outcome.  Token/context improvements never compensate for this regression.
    no_harm_regressions = [
        {
            "case_id": row["case_id"],
            "free_shell_status": row["free_shell_status"],
            "tracecite_status": row["tracecite_status"],
            "tracecite_failure_reason": row["tracecite_failure_reason"],
            "primary_quality_name": row["primary_quality_name"],
            "free_shell_primary_quality": row["free_shell_primary_quality"],
            "tracecite_primary_quality": row["tracecite_primary_quality"],
        }
        for row in comparisons
        if row["free_shell_passed"] is True and row["tracecite_passed"] is not True
    ]
    quality_degradations = [
        {
            "case_id": row["case_id"],
            "primary_quality_name": row["primary_quality_name"],
            "free_shell_primary_quality": row["free_shell_primary_quality"],
            "tracecite_primary_quality": row["tracecite_primary_quality"],
        }
        for row in valid
        if row["free_shell_passed"] is True
        and row["tracecite_passed"] is True
        and _number(row["free_shell_primary_quality"]) is not None
        and _number(row["tracecite_primary_quality"]) is not None
        and float(row["tracecite_primary_quality"]) < float(row["free_shell_primary_quality"])
    ]

    return {
        "schema_version": 1,
        "comparison": "16 unique runnable incidents; same model + same canonical agent loop + seed; provider_rate_limited/provider_unavailable retried every 120 seconds",
        "expected_cases": 16,
        "expected_arms": 32,
        "observed_outcomes": len(records),
        "observed_cases": len(pairs),
        "valid_paired_cases": len(valid),
        "all_16_valid": len(valid) == 16,
        "no_harm_passed": not no_harm_regressions,
        "no_harm_regression_count": len(no_harm_regressions),
        "no_harm_regressions": no_harm_regressions,
        "quality_degradations": quality_degradations,
        "total_provider_retries": sum(
            int(row.get("free_shell_provider_retries") or 0)
            + int(row.get("tracecite_provider_retries") or 0)
            for row in comparisons
        ),
        "provider_or_host_failures": [
            {
                "case_id": row["case_id"],
                "free_shell": row["free_shell_failure_reason"],
                "tracecite": row["tracecite_failure_reason"],
            }
            for row in comparisons
            if row["free_shell_status"] not in {"ok", "incomplete"}
            or row["tracecite_status"] not in {"ok", "incomplete"}
        ],
        "aggregate_valid_pairs": {
            "token_pairs": len(token_pairs),
            "free_shell_reported_input_tokens": shell_tokens,
            "tracecite_reported_input_tokens": trace_tokens,
            "input_token_reduction": _reduction(shell_tokens, trace_tokens),
            "shell_over_tracecite_input_ratio": _ratio(shell_tokens, trace_tokens),
            "free_shell_tool_output_chars": shell_tool,
            "tracecite_tool_output_chars": trace_tool,
            "tool_output_reduction": _reduction(shell_tool, trace_tool),
            "shell_over_tracecite_tool_output_ratio": _ratio(shell_tool, trace_tool),
        },
        "comparisons": comparisons,
        "records": records,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = aggregate(args.root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
