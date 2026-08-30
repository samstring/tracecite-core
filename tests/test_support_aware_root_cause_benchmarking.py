from __future__ import annotations

import json
from pathlib import Path

from tracecite.root_cause_benchmarking import score_transcript


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def test_support_aware_scoring_is_part_of_canonical_root_cause_scorer(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    _write(
        case_dir / "case.json",
        {
            "schema_version": 1,
            "id": "support-aware-demo",
            "question_file": "question.md",
            "gold_file": "gold.json",
            "inputs": [{"id": "runtime", "url": "https://example.invalid/runtime.log", "filename": "runtime.log", "sha256": "a" * 64}],
            "provenance": {"project": "example/project"},
        },
    )
    (case_dir / "question.md").write_text("Why?\n", encoding="utf-8")
    _write(
        case_dir / "gold.json",
        {
            "root_cause_schema_version": 1,
            "root_cause": {
                "failure_localization": {"patterns": ["worker queue"]},
                "immediate_failure_mechanism": {"patterns": ["checksum mismatch"]},
                "upstream_contributor": {"patterns": ["stale cache"], "boundary_patterns": ["upstream.{0,120}(?:not established|cannot be determined)"]},
                "fix_alignment": {"patterns": ["invalidate cache"], "boundary_patterns": ["fix.{0,120}(?:not established|cannot be determined)"]},
            },
            "evidence_sufficiency": {
                "failure_localization": "supported",
                "immediate_failure_mechanism": "inference_supported",
                "upstream_contributor": "unsupported_from_log",
                "fix_alignment": "unsupported_from_log",
            },
            "evidence_markers": [],
            "unsupported_claims": [],
            "contradictions": [],
            "root_cause_thresholds": {
                "dimension_recall": 1.0,
                "supported_dimension_recall": 1.0,
                "citation_accuracy": 1.0,
                "evidence_boundary_recall": 1.0,
                "support_level_accuracy": 1.0,
                "max_unsupported_claim_hits": 0,
                "max_contradiction_hits": 0,
                "max_unsupported_dimension_overreach_hits": 0,
            },
        },
    )
    transcript = tmp_path / "run.jsonl"
    events = [
        {"type": "session", "mode": "tracecite", "model": "demo"},
        {"type": "tool", "name": "tracecite_search", "output": "runtime.log #L12 worker queue checksum mismatch"},
        {"type": "final", "answer": "The worker queue hit what is likely a checksum mismatch. Evidence: L12.\n\nThe upstream cause is not established by the supplied evidence and cannot be determined.\n\nThe fix is not established by the supplied evidence and cannot be determined."},
    ]
    transcript.write_text("".join(json.dumps(item) + "\n" for item in events), encoding="utf-8")

    score = score_transcript(case_dir, transcript)
    assert score["legacy_passed"] is False
    assert score["support_aware_passed"] is True
    assert score["passed"] is True
    assert score["quality"]["dimension_recall"] == 1.0
    assert score["quality"]["evidence_boundary_recall"] == 1.0
    assert score["quality"]["support_level_accuracy"] == 1.0



def test_scale_case_gold_does_not_require_hidden_upstream_truth() -> None:
    root = Path(__file__).resolve().parents[1]
    for case_name in ("kubernetes-139417", "kubernetes-140268"):
        case_dir = root / "benchmarks" / "agent-investigation" / "scale-cases" / case_name
        gold = json.loads((case_dir / "gold.json").read_text(encoding="utf-8"))
        sufficiency = gold["evidence_sufficiency"]
        assert sufficiency["upstream_contributor"] == "unsupported_from_log"
        assert sufficiency["fix_alignment"] == "unsupported_from_log"
        assert gold["root_cause"]["upstream_contributor"]["boundary_patterns"]
        assert gold["root_cause"]["fix_alignment"]["boundary_patterns"]
