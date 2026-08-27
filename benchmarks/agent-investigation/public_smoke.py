from __future__ import annotations

import argparse
import json
import math
import subprocess
from pathlib import Path
from typing import Any


def _run(command: list[str]) -> tuple[dict[str, Any], str]:
    completed = subprocess.run(
        command,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=180,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"command failed ({completed.returncode}): {' '.join(command)}\n"
            f"stdout={completed.stdout[-2000:]}\nstderr={completed.stderr[-2000:]}"
        )
    payload = json.loads(completed.stdout)
    if not isinstance(payload, dict):
        raise RuntimeError("TraceCite command did not return a JSON object")
    return payload, completed.stdout


def _evidence_count(payload: dict[str, Any]) -> int:
    evidence = payload.get("evidence")
    if isinstance(evidence, list):
        return len(evidence)
    if isinstance(evidence, dict) and isinstance(evidence.get("rows"), list):
        return len(evidence["rows"])
    return 0


def _search_command(source: Path, query: str) -> list[str]:
    return [
        "tracecite",
        "search",
        str(source),
        query,
        "--regex",
        "--no-snapshot",
        "--segmenter",
        "rawtext",
        "--agent-profile",
        "stateful-index",
        "--max-output-chars",
        "12000",
    ]


def _experiment(
    *,
    source: Path,
    root: Path,
    name: str,
    queries: list[str],
) -> dict[str, Any]:
    if len(queries) != 2:
        raise ValueError("public smoke experiments require exactly two turns")

    baseline_ledger = root / f"{name}-baseline-ledger"
    context_ledger = root / f"{name}-context-ledger"
    context_id = f"kubernetes-140848-{name}"

    baseline_outputs: list[tuple[dict[str, Any], str]] = []
    context_outputs: list[tuple[dict[str, Any], str]] = []
    for query in queries:
        baseline_outputs.append(
            _run(_search_command(source, query) + ["--ledger-dir", str(baseline_ledger)])
        )
        context_outputs.append(
            _run(
                _search_command(source, query)
                + [
                    "--ledger-dir",
                    str(context_ledger),
                    "--context-id",
                    context_id,
                ]
            )
        )

    baseline_counts = [_evidence_count(item[0]) for item in baseline_outputs]
    context_counts = [_evidence_count(item[0]) for item in context_outputs]
    context_meta = dict((context_outputs[1][0].get("data") or {}).get("context") or {})
    baseline_chars = sum(len(item[1]) for item in baseline_outputs)
    context_chars = sum(len(item[1]) for item in context_outputs)

    if baseline_counts[0] < 1 or baseline_counts[1] < 1:
        raise AssertionError(f"{name}: baseline search returned no evidence: {baseline_counts}")
    if context_counts[0] < 1:
        raise AssertionError(f"{name}: Context first turn returned no evidence")
    if int(context_meta.get("repeated_evidence") or 0) < 1:
        raise AssertionError(f"{name}: second turn did not detect any overlapping Evidence")
    if context_counts[1] > baseline_counts[1]:
        raise AssertionError(f"{name}: Context cannot add Evidence beyond the canonical view")

    return {
        "queries": queries,
        "baseline": {
            "evidence_per_turn": baseline_counts,
            "visible_chars_two_turns": baseline_chars,
            "estimated_visible_tokens_chars_div_4": math.ceil(baseline_chars / 4),
        },
        "tracecite_context": {
            "evidence_per_turn": context_counts,
            "visible_chars_two_turns": context_chars,
            "estimated_visible_tokens_chars_div_4": math.ceil(context_chars / 4),
            "second_turn_context": context_meta,
        },
        "delta": {
            "visible_chars_saved": baseline_chars - context_chars,
            "fraction_saved": round(
                (baseline_chars - context_chars) / baseline_chars if baseline_chars else 0.0,
                6,
            ),
        },
    }


def run_smoke(prepared_manifest: Path, output: Path) -> dict[str, Any]:
    prepared = json.loads(prepared_manifest.read_text(encoding="utf-8"))
    inputs = prepared.get("inputs") or []
    if not inputs:
        raise ValueError("prepared manifest has no inputs")
    source = Path(inputs[0]["path"])
    if not source.is_file():
        raise FileNotFoundError(source)

    repeated_query = "panic|PodLevelResources|KubeletConfiguration|configz"
    repeated = _experiment(
        source=source,
        root=output.parent,
        name="repeated",
        queries=[repeated_query, repeated_query],
    )
    if repeated["tracecite_context"]["evidence_per_turn"][1] != 0:
        raise AssertionError("repeated-query second turn should suppress all citable Evidence")

    overlapping = _experiment(
        source=source,
        root=output.parent,
        name="overlap",
        queries=[
            "panic|PodLevelResourcesFixDefaulting",
            "PodLevelResourcesFixDefaulting|KubeletConfiguration|configz",
        ],
    )

    result = {
        "schema_version": 1,
        "case_id": prepared.get("case_id"),
        "source_bytes": inputs[0].get("bytes"),
        "source_sha256": inputs[0].get("sha256"),
        "experiments": {
            "repeated_query": repeated,
            "overlapping_queries": overlapping,
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("prepared_manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run_smoke(args.prepared_manifest, args.output)
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
