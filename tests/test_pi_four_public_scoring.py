from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "benchmarks" / "agent-investigation" / "pi_four_public_scoring.py"


def _load_helper():
    spec = importlib.util.spec_from_file_location("pi_four_public_scoring_test", HELPER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_existing_four_public_cases_use_legacy_gold_schema() -> None:
    module = _load_helper()
    base = ROOT / "benchmarks" / "agent-investigation" / "cases"
    for case_id in (
        "containerd-6772",
        "kubernetes-140039-runc-5347",
        "kubernetes-141402-podcertificate-readiness",
        "kubernetes-141283-compat-feature-gate",
    ):
        assert module.score_kind(base / case_id) == "legacy"


def test_project_score_preserves_legacy_quality() -> None:
    module = _load_helper()
    projected = module.project_score(
        {
            "score_kind": "legacy",
            "passed": True,
            "quality": {"concept_recall": 1.0, "evidence_marker_recall": 0.75},
        },
        answer_nonempty=True,
    )
    assert projected["answer_success"] is True
    assert projected["score_passed"] is True
    assert projected["concept_recall"] == 1.0
    assert projected["evidence_marker_recall"] == 0.75
    assert projected["dimension_recall"] is None


def test_project_score_preserves_root_cause_quality() -> None:
    module = _load_helper()
    projected = module.project_score(
        {
            "score_kind": "root_cause",
            "passed": True,
            "quality": {
                "dimension_recall": 0.75,
                "supported_dimension_recall": 0.5,
                "citation": {"accuracy": 1.0},
                "unsupported_claim_hits": 0,
                "contradiction_hits": 0,
                "evidence_marker_recall": 1.0,
            },
        },
        answer_nonempty=True,
    )
    assert projected["answer_success"] is True
    assert projected["dimension_recall"] == 0.75
    assert projected["supported_dimension_recall"] == 0.5
    assert projected["citation_accuracy"] == 1.0
    assert projected["concept_recall"] is None


def test_project_score_requires_nonempty_answer_and_passed_score() -> None:
    module = _load_helper()
    score = {"score_kind": "legacy", "passed": True, "quality": {}}
    assert module.project_score(score, answer_nonempty=False)["answer_success"] is False
    score["passed"] = False
    assert module.project_score(score, answer_nonempty=True)["answer_success"] is False
