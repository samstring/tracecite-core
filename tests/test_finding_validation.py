from __future__ import annotations

from pathlib import Path

import pytest

from tracecite.runtime.finding_validation import validate_finding
from tracecite.runtime.investigation import InvestigationError, InvestigationStore
from tracecite.runtime.test_assessment import assess_test


DIGEST = "a" * 64
EVIDENCE = f"evidence://sha256/{DIGEST}#L10-L12"


def _store(tmp_path: Path) -> InvestigationStore:
    store = InvestigationStore(tmp_path / "investigation.json")
    store.create("why did the request fail?", scope={"sources": ["app.log"]})
    store.add_hypothesis("the request timed out", hypothesis_id="H1")
    store.add_test(
        "H1",
        "inspect timeout records",
        expected_observation="timeout is present",
        contradicting_observation="request completed successfully",
        test_id="T1",
    )
    return store


def _record_valid_execution(store: InvestigationStore) -> None:
    store.record_execution(
        "search",
        {
            "status": "ok",
            "outcome": "not_assessed",
            "evidence": [{"uri": EVIDENCE}],
            "coverage": {"complete": True},
            "verification": {"integrity_checked": True},
        },
        hypothesis_id="H1",
        test_id="T1",
    )


def _assess_supported(store: InvestigationStore) -> None:
    assess_test(
        store,
        "T1",
        "supported",
        evidence_refs=[EVIDENCE],
        coverage={"complete": True},
    )


def test_supported_finding_requires_an_executed_test(tmp_path: Path) -> None:
    store = _store(tmp_path)

    result = validate_finding(
        store,
        "H1",
        "supported",
        supporting_evidence=[EVIDENCE],
    )

    assert result.valid is False
    assert result.validated_outcome == "unknown"
    assert "test_not_executed" in result.reasons
    assert "test_not_assessed" in result.reasons


def test_decisive_finding_rejects_non_citable_evidence(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.record_execution(
        "search",
        {
            "status": "ok",
            "outcome": "not_assessed",
            "evidence": [{"uri": "evidence://mutable/log#L10"}],
            "coverage": {"complete": True},
        },
        hypothesis_id="H1",
        test_id="T1",
    )

    result = validate_finding(
        store,
        "H1",
        "supported",
        supporting_evidence=["evidence://mutable/log#L10"],
    )

    assert result.valid is False
    assert result.validated_outcome == "unknown"
    assert "non_citable_evidence" in result.reasons


def test_finding_evidence_must_come_from_linked_test_execution(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _record_valid_execution(store)
    other = f"evidence://sha256/{'b' * 64}#L1"

    result = validate_finding(
        store,
        "H1",
        "supported",
        supporting_evidence=[other],
    )

    assert result.valid is False
    assert "evidence_not_from_linked_test" in result.reasons


def test_explicit_coverage_gap_downgrades_decisive_finding(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.record_execution(
        "search",
        {
            "status": "ok",
            "outcome": "not_assessed",
            "evidence": [{"uri": EVIDENCE}],
            "coverage": {"complete": False},
        },
        hypothesis_id="H1",
        test_id="T1",
    )

    result = validate_finding(
        store,
        "H1",
        "supported",
        supporting_evidence=[EVIDENCE],
    )

    assert result.valid is False
    assert result.validated_outcome == "unknown"
    assert "linked_execution_coverage_gap" in result.reasons


def test_valid_supported_finding_passes_mechanical_validation(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _record_valid_execution(store)
    _assess_supported(store)

    result = validate_finding(
        store,
        "H1",
        "supported",
        supporting_evidence=[EVIDENCE],
        coverage={"complete": True},
    )

    assert result.valid is True
    assert result.validated_outcome == "supported"
    assert result.reasons == ()
    assert result.test_ids == ("T1",)
    assert result.test_assessments == {"T1": "supported"}
    assert len(result.execution_ids) == 2


def test_supported_finding_requires_every_declared_test_assessed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _record_valid_execution(store)
    _assess_supported(store)
    store.add_test(
        "H1",
        "check competing explanation",
        expected_observation="competing explanation is absent",
        contradicting_observation="competing explanation is observed",
        test_id="T2",
    )

    result = validate_finding(
        store,
        "H1",
        "supported",
        supporting_evidence=[EVIDENCE],
        coverage={"complete": True},
    )

    assert result.valid is False
    assert result.validated_outcome == "unknown"
    assert "test_not_assessed" in result.reasons


def test_unknown_test_assessment_blocks_decisive_finding(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _record_valid_execution(store)
    assess_test(store, "T1", "unknown")

    result = validate_finding(
        store,
        "H1",
        "supported",
        supporting_evidence=[EVIDENCE],
        coverage={"complete": True},
    )

    assert result.valid is False
    assert result.validated_outcome == "unknown"
    assert "test_assessment_unknown" in result.reasons


def test_contradicting_test_blocks_supported_finding(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _record_valid_execution(store)
    assess_test(
        store,
        "T1",
        "contradicted",
        evidence_refs=[EVIDENCE],
        coverage={"complete": True},
    )

    result = validate_finding(
        store,
        "H1",
        "supported",
        supporting_evidence=[EVIDENCE],
        coverage={"complete": True},
    )

    assert result.valid is False
    assert result.validated_outcome == "unknown"
    assert "test_contradicts_supported_finding" in result.reasons


def test_contradicted_finding_requires_contradicting_test_assessment(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _record_valid_execution(store)
    _assess_supported(store)

    result = validate_finding(
        store,
        "H1",
        "contradicted",
        contradicting_evidence=[EVIDENCE],
        coverage={"complete": True},
    )

    assert result.valid is False
    assert result.validated_outcome == "unknown"
    assert "no_contradicting_test_assessment" in result.reasons


def test_unknown_is_safe_without_evidence_or_execution(tmp_path: Path) -> None:
    store = _store(tmp_path)

    result = validate_finding(store, "H1", "unknown")

    assert result.valid is True
    assert result.validated_outcome == "unknown"
    assert result.reasons == ()


def test_add_finding_rejects_unvalidated_decisive_outcome_without_mutation(tmp_path: Path) -> None:
    store = _store(tmp_path)

    with pytest.raises(InvestigationError, match="Finding Validation") as exc_info:
        store.add_finding(
            "H1",
            "supported",
            "timeout caused the failure",
            supporting_evidence=[EVIDENCE],
        )

    assert "test_not_executed" in str(exc_info.value)
    state = store.load()
    assert state.findings == []
    assert state.hypotheses[0]["status"] == "open"


def test_add_finding_accepts_validated_decisive_outcome(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _record_valid_execution(store)
    _assess_supported(store)

    finding = store.add_finding(
        "H1",
        "supported",
        "timeout evidence was found",
        supporting_evidence=[EVIDENCE],
        coverage={"complete": True},
    )

    assert finding["outcome"] == "supported"
    state = store.load()
    assert state.findings[0]["id"] == finding["id"]
    assert state.hypotheses[0]["status"] == "supported"


def test_add_finding_keeps_unknown_as_explicit_safe_stop(tmp_path: Path) -> None:
    store = _store(tmp_path)

    finding = store.add_finding("H1", "unknown", "evidence remains insufficient")

    assert finding["outcome"] == "unknown"
    assert store.load().hypotheses[0]["status"] == "unknown"


def test_adversarial_no_match_cannot_be_used_as_decisive_proof(tmp_path: Path) -> None:
    """A hostile host must not turn a successful zero-match search into proof."""

    store = _store(tmp_path)
    store.record_execution(
        "search",
        {
            "status": "no_match",
            "outcome": "unknown",
            "evidence": [{"uri": EVIDENCE}],
            "coverage": {"complete": True},
            "verification": {"integrity_checked": True},
        },
        hypothesis_id="H1",
        test_id="T1",
    )

    result = validate_finding(
        store,
        "H1",
        "supported",
        supporting_evidence=[EVIDENCE],
    )

    assert result.valid is False
    assert result.validated_outcome == "unknown"
    assert "linked_execution_no_match" in result.reasons

    with pytest.raises(InvestigationError, match="linked_execution_no_match"):
        store.add_finding(
            "H1",
            "supported",
            "zero matches prove absence",
            supporting_evidence=[EVIDENCE],
        )
    assert store.load().hypotheses[0]["status"] == "open"


def test_adversarial_unverified_evidence_cannot_be_certified(tmp_path: Path) -> None:
    """A valid-looking evidence URI is insufficient when integrity was not checked."""

    store = _store(tmp_path)
    store.record_execution(
        "search",
        {
            "status": "ok",
            "outcome": "not_assessed",
            "evidence": [{"uri": EVIDENCE}],
            "coverage": {"complete": True},
            "verification": {"integrity_checked": False},
        },
        hypothesis_id="H1",
        test_id="T1",
    )

    result = validate_finding(
        store,
        "H1",
        "supported",
        supporting_evidence=[EVIDENCE],
    )

    assert result.valid is False
    assert result.validated_outcome == "unknown"
    assert "linked_execution_unverified" in result.reasons


def test_adversarial_evidence_from_other_hypothesis_is_rejected(tmp_path: Path) -> None:
    """Evidence recorded under a different investigation branch cannot be stolen."""

    store = _store(tmp_path)
    store.add_hypothesis("the request succeeded", hypothesis_id="H2")
    store.add_test(
        "H2",
        "inspect success records",
        expected_observation="success is present",
        contradicting_observation="success is absent",
        test_id="T2",
    )
    store.record_execution(
        "search",
        {
            "status": "ok",
            "outcome": "not_assessed",
            "evidence": [{"uri": EVIDENCE}],
            "coverage": {"complete": True},
            "verification": {"integrity_checked": True},
        },
        hypothesis_id="H2",
        test_id="T2",
    )

    result = validate_finding(
        store,
        "H1",
        "supported",
        supporting_evidence=[EVIDENCE],
    )

    assert result.valid is False
    assert result.validated_outcome == "unknown"
    assert "test_not_executed" in result.reasons
    assert "evidence_not_from_linked_test" in result.reasons
