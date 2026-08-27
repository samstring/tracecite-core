from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
from pathlib import Path
from typing import Any


MAX_VISIBLE_EVIDENCE = 30
MAX_VISIBLE_LINE_CHARS = 1024


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


def _rg(source: Path, query: str) -> tuple[int, str]:
    executable = shutil.which("rg")
    if not executable:
        raise RuntimeError("ripgrep (rg) is required for the shell baseline")
    completed = subprocess.run(
        [
            executable,
            "-n",
            "--no-heading",
            "--color",
            "never",
            "-m",
            str(MAX_VISIBLE_EVIDENCE),
            "--",
            query,
            str(source),
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=180,
    )
    if completed.returncode not in {0, 1}:
        raise RuntimeError(
            f"rg failed ({completed.returncode}): {completed.stderr[-2000:]}"
        )
    lines = completed.stdout.splitlines()
    visible = "\n".join(line[:MAX_VISIBLE_LINE_CHARS] for line in lines)
    if visible:
        visible += "\n"
    return len(lines), visible


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
        "--max-evidence",
        str(MAX_VISIBLE_EVIDENCE),
        "--max-line-chars",
        str(MAX_VISIBLE_LINE_CHARS),
    ]


def _cost(outputs: list[str]) -> dict[str, Any]:
    chars = sum(len(output) for output in outputs)
    return {
        "visible_chars_two_turns": chars,
        "estimated_visible_tokens_chars_div_4": math.ceil(chars / 4),
    }


def _read_context_state(root: Path, context_id: str) -> dict[str, Any]:
    path = root / "_contexts" / f"{context_id}.json"
    if not path.is_file():
        raise AssertionError(f"missing Context state: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise AssertionError("Context state must be a JSON object")
    return payload


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

    rg_counts: list[int] = []
    rg_outputs: list[str] = []
    baseline_outputs: list[tuple[dict[str, Any], str]] = []
    context_outputs: list[tuple[dict[str, Any], str]] = []
    for query in queries:
        rg_count, rg_output = _rg(source, query)
        rg_counts.append(rg_count)
        rg_outputs.append(rg_output)
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
    context_state = _read_context_state(context_ledger, context_id)
    baseline_visible = [item[1] for item in baseline_outputs]
    context_visible = [item[1] for item in context_outputs]
    baseline_cost = _cost(baseline_visible)
    context_cost = _cost(context_visible)
    rg_cost = _cost(rg_outputs)

    if min(rg_counts) < 1:
        raise AssertionError(f"{name}: rg returned no evidence: {rg_counts}")
    if baseline_counts[0] < 1 or baseline_counts[1] < 1:
        raise AssertionError(f"{name}: baseline search returned no evidence: {baseline_counts}")
    if context_counts[0] < 1:
        raise AssertionError(f"{name}: Context first turn returned no evidence")
    if context_counts[1] > baseline_counts[1]:
        raise AssertionError(f"{name}: Context cannot add Evidence beyond the ordinary Agent view")
    if int(context_state.get("revision") or 0) != 2:
        raise AssertionError(f"{name}: Context state did not advance across both turns")

    baseline_chars = int(baseline_cost["visible_chars_two_turns"])
    context_chars = int(context_cost["visible_chars_two_turns"])
    if context_chars > baseline_chars:
        raise AssertionError(
            f"{name}: gain-aware Context view became larger than ordinary TraceCite: "
            f"{context_chars} > {baseline_chars}"
        )

    projection = "delta" if context_meta else "canonical_fallback"
    return {
        "queries": queries,
        "shell_rg": {
            "matched_lines_per_turn": rg_counts,
            "semantics": "rg -m 30; each model-visible line capped at 1024 characters; no Coverage or recovery metadata",
            **rg_cost,
        },
        "tracecite": {
            "evidence_per_turn": baseline_counts,
            **baseline_cost,
        },
        "tracecite_context": {
            "evidence_per_turn": context_counts,
            **context_cost,
            "second_turn_projection": projection,
            "second_turn_context": context_meta,
            "state_after_two_turns": {
                "revision": context_state.get("revision"),
                "seen_evidence": len(context_state.get("seen_evidence") or []),
                "seen_results": len(context_state.get("seen_results") or []),
            },
        },
        "context_vs_tracecite": {
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
        raise AssertionError("repeated-query second turn should use the smaller all-seen delta")
    if repeated["tracecite_context"]["second_turn_projection"] != "delta":
        raise AssertionError("repeated-query experiment should select the smaller delta view")

    exact_panic = "failed to merge global and in-flight KubeletConfiguration while setting defaults"
    overlapping = _experiment(
        source=source,
        root=output.parent,
        name="overlap",
        queries=[
            exact_panic,
            f"{exact_panic}|PodLevelResourcesFixDefaulting",
        ],
    )

    result = {
        "schema_version": 1,
        "case_id": prepared.get("case_id"),
        "source_bytes": inputs[0].get("bytes"),
        "source_sha256": inputs[0].get("sha256"),
        "warning": "Fixed-query transport comparison only. It does not measure model reasoning, diagnosis accuracy, or total Agent tokens.",
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
