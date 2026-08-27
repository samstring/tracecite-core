from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _median(values: list[float | int]) -> float | None:
    return float(statistics.median(values)) if values else None


def aggregate(paths: list[Path]) -> dict[str, Any]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for path in paths:
        item = _load(path)
        key = (
            str(item.get("case_id") or "unknown"),
            str(item.get("model") or "unknown"),
            str(item.get("mode") or "unknown"),
        )
        groups[key].append(item)

    rows: list[dict[str, Any]] = []
    for (case_id, model, mode), runs in sorted(groups.items()):
        passed = [bool(run.get("passed")) for run in runs]
        costs = [run.get("context_cost") or {} for run in runs]
        tool_calls = [
            int(cost["tool_calls"])
            for cost in costs
            if isinstance(cost.get("tool_calls"), int)
        ]
        visible_chars = [
            int(cost["tool_output_chars"])
            for cost in costs
            if isinstance(cost.get("tool_output_chars"), int)
        ]
        duplicate_chars = [
            int(cost["exact_duplicate_tool_output_chars"])
            for cost in costs
            if isinstance(cost.get("exact_duplicate_tool_output_chars"), int)
        ]
        reported_input = [
            int(cost["reported_input_tokens"])
            for cost in costs
            if isinstance(cost.get("reported_input_tokens"), int)
        ]
        reported_output = [
            int(cost["reported_output_tokens"])
            for cost in costs
            if isinstance(cost.get("reported_output_tokens"), int)
        ]
        estimated_visible = [
            int(cost["estimated_tool_output_tokens_chars_div_4"])
            for cost in costs
            if isinstance(cost.get("estimated_tool_output_tokens_chars_div_4"), int)
        ]
        rows.append(
            {
                "case_id": case_id,
                "model": model,
                "mode": mode,
                "runs": len(runs),
                "passed_runs": sum(passed),
                "pass_rate": round(sum(passed) / len(runs), 4),
                "median_tool_calls": _median(tool_calls),
                "median_tool_output_chars": _median(visible_chars),
                "median_exact_duplicate_tool_output_chars": _median(duplicate_chars),
                "median_reported_input_tokens": _median(reported_input),
                "median_reported_output_tokens": _median(reported_output),
                "median_estimated_visible_output_tokens_chars_div_4": _median(estimated_visible),
                "reported_token_runs": min(len(reported_input), len(reported_output)),
            }
        )

    return {
        "schema_version": 1,
        "input_runs": len(paths),
        "groups": rows,
        "warning": (
            "Provider-reported tokens are only comparable when the same provider/model and usage semantics "
            "were used. chars/4 values are fallback estimates, not exact tokenizer counts."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Aggregate TraceCite Agent benchmark score JSON files")
    parser.add_argument("scores", nargs="+", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = aggregate(args.scores)
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}))
        return 1
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
