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

CASE_PROFILES: dict[str, dict[str, Any]] = {
    "kubernetes-140848": {
        "repeated_query": "panic|PodLevelResources|KubeletConfiguration|configz",
        "overlap_queries": [
            "failed to merge global and in-flight KubeletConfiguration while setting defaults",
            "failed to merge global and in-flight KubeletConfiguration while setting defaults|PodLevelResourcesFixDefaulting",
        ],
    },
    "flutter-179398": {
        "repeated_query": "EXC_BAD_ACCESS|DrawCircularArc|RoundSuperellipse|_dispatch_cache_cleanup",
        "overlap_queries": [
            "DrawCircularArc|RoundSuperellipseGeometry",
            "DrawCircularArc|RoundSuperellipseGeometry|_dispatch_cache_cleanup",
        ],
    },
}


def _run_text(command: list[str]) -> str:
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
    return completed.stdout


def _run_json(command: list[str]) -> tuple[dict[str, Any], str]:
    rendered = _run_text(command)
    payload = json.loads(rendered)
    if not isinstance(payload, dict):
        raise RuntimeError("TraceCite command did not return a JSON object")
    return payload, rendered


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


def _frame_evidence_count(rendered: str) -> int:
    in_evidence = False
    count = 0
    for line in rendered.splitlines():
        if line.startswith("@E "):
            in_evidence = True
            continue
        if in_evidence and line.startswith("@"):
            break
        if in_evidence and line:
            count += 1
    return count


def _search_command(source: Path, query: str, *, profile: str) -> list[str]:
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
        profile,
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


def _saving(baseline_chars: int, context_chars: int) -> dict[str, Any]:
    return {
        "visible_chars_saved": baseline_chars - context_chars,
        "fraction_saved": round(
            (baseline_chars - context_chars) / baseline_chars if baseline_chars else 0.0,
            6,
        ),
    }


def _experiment(
    *,
    case_id: str,
    source: Path,
    root: Path,
    name: str,
    queries: list[str],
) -> dict[str, Any]:
    if len(queries) != 2:
        raise ValueError("public smoke experiments require exactly two turns")

    json_baseline_ledger = root / f"{case_id}-{name}-json-baseline-ledger"
    json_context_ledger = root / f"{case_id}-{name}-json-context-ledger"
    frame_baseline_ledger = root / f"{case_id}-{name}-frame-baseline-ledger"
    frame_context_ledger = root / f"{case_id}-{name}-frame-context-ledger"
    json_context_id = f"{case_id}-{name}-json"
    frame_context_id = f"{case_id}-{name}-frame"

    rg_counts: list[int] = []
    rg_outputs: list[str] = []
    json_baseline: list[tuple[dict[str, Any], str]] = []
    json_context: list[tuple[dict[str, Any], str]] = []
    frame_baseline: list[str] = []
    frame_context: list[str] = []

    for query in queries:
        rg_count, rg_output = _rg(source, query)
        rg_counts.append(rg_count)
        rg_outputs.append(rg_output)

        json_baseline.append(
            _run_json(
                _search_command(source, query, profile="stateful-index")
                + ["--ledger-dir", str(json_baseline_ledger)]
            )
        )
        json_context.append(
            _run_json(
                _search_command(source, query, profile="stateful-index")
                + [
                    "--ledger-dir",
                    str(json_context_ledger),
                    "--context-id",
                    json_context_id,
                ]
            )
        )
        frame_baseline.append(
            _run_text(
                _search_command(source, query, profile="frame")
                + ["--ledger-dir", str(frame_baseline_ledger)]
            )
        )
        frame_context.append(
            _run_text(
                _search_command(source, query, profile="frame")
                + [
                    "--ledger-dir",
                    str(frame_context_ledger),
                    "--context-id",
                    frame_context_id,
                ]
            )
        )

    json_baseline_counts = [_evidence_count(item[0]) for item in json_baseline]
    json_context_counts = [_evidence_count(item[0]) for item in json_context]
    frame_baseline_counts = [_frame_evidence_count(item) for item in frame_baseline]
    frame_context_counts = [_frame_evidence_count(item) for item in frame_context]

    json_context_meta = dict((json_context[1][0].get("data") or {}).get("context") or {})
    json_state = _read_context_state(json_context_ledger, json_context_id)
    frame_state = _read_context_state(frame_context_ledger, frame_context_id)

    json_baseline_cost = _cost([item[1] for item in json_baseline])
    json_context_cost = _cost([item[1] for item in json_context])
    frame_baseline_cost = _cost(frame_baseline)
    frame_context_cost = _cost(frame_context)
    rg_cost = _cost(rg_outputs)

    if min(rg_counts) < 1:
        raise AssertionError(f"{case_id}/{name}: rg returned no evidence: {rg_counts}")
    if min(json_baseline_counts) < 1 or min(frame_baseline_counts) < 1:
        raise AssertionError(
            f"{case_id}/{name}: baseline search returned no evidence: "
            f"json={json_baseline_counts} frame={frame_baseline_counts}"
        )
    if json_context_counts[0] < 1 or frame_context_counts[0] < 1:
        raise AssertionError(f"{case_id}/{name}: Context first turn returned no evidence")
    if json_context_counts[1] > json_baseline_counts[1]:
        raise AssertionError(f"{case_id}/{name}: JSON Context added Evidence")
    if frame_context_counts[1] > frame_baseline_counts[1]:
        raise AssertionError(f"{case_id}/{name}: frame Context added Evidence")
    if int(json_state.get("revision") or 0) != 2 or int(frame_state.get("revision") or 0) != 2:
        raise AssertionError(f"{case_id}/{name}: Context state did not advance across both turns")

    json_baseline_chars = int(json_baseline_cost["visible_chars_two_turns"])
    json_context_chars = int(json_context_cost["visible_chars_two_turns"])
    frame_baseline_chars = int(frame_baseline_cost["visible_chars_two_turns"])
    frame_context_chars = int(frame_context_cost["visible_chars_two_turns"])
    if json_context_chars > json_baseline_chars:
        raise AssertionError(f"{case_id}/{name}: JSON Context view became larger")
    if frame_context_chars > frame_baseline_chars:
        raise AssertionError(f"{case_id}/{name}: frame Context view became larger")

    json_projection = "delta" if json_context_meta else "canonical_fallback"
    return {
        "queries": queries,
        "shell_rg": {
            "matched_lines_per_turn": rg_counts,
            "semantics": "rg -m 30; each model-visible line capped at 1024 characters; no Coverage or recovery metadata",
            **rg_cost,
        },
        "tracecite_json": {
            "evidence_per_turn": json_baseline_counts,
            **json_baseline_cost,
        },
        "tracecite_json_context": {
            "evidence_per_turn": json_context_counts,
            **json_context_cost,
            "second_turn_projection": json_projection,
            "second_turn_context": json_context_meta,
            "state_after_two_turns": {
                "revision": json_state.get("revision"),
                "seen_evidence": len(json_state.get("seen_evidence") or []),
                "seen_results": len(json_state.get("seen_results") or []),
            },
        },
        "json_context_vs_json": _saving(json_baseline_chars, json_context_chars),
        "tracecite_frame": {
            "evidence_per_turn": frame_baseline_counts,
            **frame_baseline_cost,
        },
        "tracecite_frame_context": {
            "evidence_per_turn": frame_context_counts,
            **frame_context_cost,
            "state_after_two_turns": {
                "revision": frame_state.get("revision"),
                "seen_evidence": len(frame_state.get("seen_evidence") or []),
                "seen_results": len(frame_state.get("seen_results") or []),
            },
        },
        "frame_context_vs_frame": _saving(frame_baseline_chars, frame_context_chars),
        "frame_vs_json": {
            "plain_visible_chars_saved": json_baseline_chars - frame_baseline_chars,
            "plain_fraction_saved": round(
                (json_baseline_chars - frame_baseline_chars) / json_baseline_chars
                if json_baseline_chars
                else 0.0,
                6,
            ),
            "context_visible_chars_saved": json_context_chars - frame_context_chars,
            "context_fraction_saved": round(
                (json_context_chars - frame_context_chars) / json_context_chars
                if json_context_chars
                else 0.0,
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

    case_id = str(prepared.get("case_id") or "")
    profile = CASE_PROFILES.get(case_id)
    if profile is None:
        raise ValueError(f"no public transport smoke profile for case: {case_id}")

    repeated_query = str(profile["repeated_query"])
    repeated = _experiment(
        case_id=case_id,
        source=source,
        root=output.parent,
        name="repeated",
        queries=[repeated_query, repeated_query],
    )
    if repeated["tracecite_json_context"]["evidence_per_turn"][1] != 0:
        raise AssertionError("repeated-query JSON second turn should use the smaller all-seen delta")
    if repeated["tracecite_json_context"]["second_turn_projection"] != "delta":
        raise AssertionError("repeated-query JSON experiment should select the smaller delta view")
    if repeated["tracecite_frame_context"]["evidence_per_turn"][1] != 0:
        raise AssertionError("repeated-query frame second turn should use the smaller all-seen delta")

    overlapping = _experiment(
        case_id=case_id,
        source=source,
        root=output.parent,
        name="overlap",
        queries=[str(item) for item in profile["overlap_queries"]],
    )

    result = {
        "schema_version": 2,
        "case_id": case_id,
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
