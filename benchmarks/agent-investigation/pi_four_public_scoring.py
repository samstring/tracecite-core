from __future__ import annotations

"""Schema-aware scorer for the four public Pi A/B cases.

The public-case corpus currently contains both the legacy concept/marker gold
schema and the newer fixed root-cause rubric. The benchmark host must choose the
evaluator from the gold schema rather than assuming every case has already
migrated.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

from tracecite import benchmarking
from tracecite import root_cause_benchmarking


def _read_gold(case_dir: Path) -> dict[str, Any]:
    case = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
    gold_path = case_dir / str(case.get("gold_file", "gold.json"))
    gold = json.loads(gold_path.read_text(encoding="utf-8"))
    if not isinstance(gold, dict):
        raise ValueError("gold.json must contain an object")
    return gold


def score_kind(case_dir: Path) -> str:
    gold = _read_gold(case_dir)
    if gold.get("root_cause_schema_version") == root_cause_benchmarking.ROOT_CAUSE_SCHEMA_VERSION:
        return "root_cause"
    return "legacy"


def score_case(case_dir: Path, transcript: Path) -> dict[str, Any]:
    kind = score_kind(case_dir)
    if kind == "root_cause":
        score = root_cause_benchmarking.score_transcript(case_dir, transcript)
    else:
        score = benchmarking.score_transcript(case_dir, transcript)
    payload = dict(score)
    payload["score_kind"] = kind
    return payload


def project_score(score: Mapping[str, Any], *, answer_nonempty: bool) -> dict[str, Any]:
    kind = str(score.get("score_kind") or "")
    quality = score.get("quality") if isinstance(score.get("quality"), Mapping) else {}
    citation = quality.get("citation") if isinstance(quality.get("citation"), Mapping) else {}
    passed = score.get("passed") is True
    return {
        "score_kind": kind or None,
        "score_passed": score.get("passed"),
        "answer_success": bool(answer_nonempty and passed),
        "dimension_recall": quality.get("dimension_recall"),
        "supported_dimension_recall": quality.get("supported_dimension_recall"),
        "citation_accuracy": citation.get("accuracy"),
        "unsupported_claim_hits": quality.get("unsupported_claim_hits"),
        "contradiction_hits": quality.get("contradiction_hits"),
        "concept_recall": quality.get("concept_recall"),
        "evidence_marker_recall": quality.get("evidence_marker_recall"),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Score Pi four-public cases by their gold schema")
    sub = parser.add_subparsers(dest="command", required=True)
    score = sub.add_parser("score")
    score.add_argument("case_dir", type=Path)
    score.add_argument("transcript", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        payload = score_case(args.case_dir, args.transcript)
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
