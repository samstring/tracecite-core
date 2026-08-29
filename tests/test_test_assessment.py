from __future__ import annotations

from pathlib import Path

import pytest

from tracecite.runtime.investigation import InvestigationError, InvestigationStore
from tracecite.runtime.test_assessment import (
    assess_test,
    confirm_test_evidence,
    validate_test_assessment,
)


DIGEST = "a" * 64
EVIDENCE = f"evidence://sha256/{DIGEST}#L10-L12"
VISIBLE_LINE = f"evidence://sha256/{DIGEST}#L15"
OTHER = f"evidence://sha256/{'b' * 64}#L20-L21"


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


def _record(
    store: InvestigationStore,
    *,
    evidence: str = EVIDENCE,
    status: str = "ok",
    coverage: dict[str, object] | None = None,
    integrity_checked: bool = True,
    linked: bool = True,
) -> None:
    store.record_execution(
        "search",
        {
            "status": status,
            "outcome": "not_assessed",
            "evidence": [{"uri": evidence}],
            "coverage": {"complete": True} if coverage is None else coverage,
            "verification": {"integrity_checked": integrity_checked},
        },
        hypothesis_id="H1" if linked else None,
        test_id="T1" if linked else None,
    )


def test_decisive_assessment_requires_evidence(tmp_path: Path) -> None:
    store = _store(tmp_path)
    result = validate_test_assessment(store, "T1", "supported")
    assert result.valid is False
    assert "missing_assessment_evidence" in result.reasons


def test_assessment_evidence_must_come_from_same_test(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _record(store)
    result = validate_test_assessment(store, "T1", "supported", evidence_refs=[OTHER])
    assert result.valid is False
    assert "assessment_evidence_not_from_test" in result.reasons


def test_free_exploration_evidence_requires_explicit_confirmation(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _record(store, linked=False)

    before = validate_test_assessment(store, "T1", "supported", evidence_refs=[EVIDENCE])
    assert before.valid is False
    assert "assessment_evidence_not_from_test" in before.reasons

    confirmed = confirm_test_evidence(store, "T1", evidence_refs=[EVIDENCE])
    assert confirmed["test_id"] == "T1"
    assert confirmed["evidence_refs"] == [EVIDENCE]
    assert confirmed["origin_execution_ids"]

    after = validate_test_assessment(store, "T1", "supported", evidence_refs=[EVIDENCE])
    assert after.valid is True
    assert assess_test(store, "T1", "supported", evidence_refs=[EVIDENCE])["outcome"] == "supported"


def test_confirm_accepts_precise_line_inside_recorded_materialized_window(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _record(
        store,
        linked=False,
        coverage={"context_start_line": 5, "context_end_line": 20, "truncated": False},
    )

    confirmed = confirm_test_evidence(store, "T1", evidence_refs=[VISIBLE_LINE])
    assert confirmed["evidence_refs"] == [VISIBLE_LINE]

    state = store.load()
    execution = state.executions[-1]
    assert execution["operation"] == "confirm_test_evidence"
    assert execution["evidence"][0]["uri"] == VISIBLE_LINE
    assert execution["evidence"][0]["start_line"] == 15
    assert execution["evidence"][0]["end_line"] == 15

    result = validate_test_assessment(store, "T1", "supported", evidence_refs=[VISIBLE_LINE])
    assert result.valid is True


def test_confirm_rejects_line_outside_recorded_materialized_window(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _record(
        store,
        linked=False,
        coverage={"context_start_line": 5, "context_end_line": 20, "truncated": False},
    )
    outside = f"evidence://sha256/{DIGEST}#L21"
    with pytest.raises(InvestigationError, match="confirmed_evidence_not_materialized"):
        confirm_test_evidence(store, "T1", evidence_refs=[outside])


def test_confirm_prefers_clean_repeated_observation(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _record(store, linked=False, coverage={"complete": False})
    _record(store, linked=False, coverage={"complete": True})

    confirmed = confirm_test_evidence(store, "T1", evidence_refs=[EVIDENCE])
    assert confirmed["evidence_refs"] == [EVIDENCE]
    assert len(confirmed["origin_execution_ids"]) == 1


def test_confirm_rejects_evidence_not_seen_in_investigation(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _record(store, linked=False)
    with pytest.raises(InvestigationError, match="confirmed_evidence_not_materialized"):
        confirm_test_evidence(store, "T1", evidence_refs=[OTHER])


def test_confirm_rejects_unverified_free_exploration_evidence(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _record(store, linked=False, integrity_checked=False)
    with pytest.raises(InvestigationError, match="assessment_source_unverified"):
        confirm_test_evidence(store, "T1", evidence_refs=[EVIDENCE])


def test_assessment_rejects_incomplete_source_coverage(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _record(store, coverage={"complete": False})
    result = validate_test_assessment(store, "T1", "supported", evidence_refs=[EVIDENCE])
    assert result.valid is False
    assert "assessment_source_coverage_gap" in result.reasons


def test_assessment_rejects_unverified_source_evidence(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _record(store, integrity_checked=False)
    result = validate_test_assessment(store, "T1", "supported", evidence_refs=[EVIDENCE])
    assert result.valid is False
    assert "assessment_source_unverified" in result.reasons


def test_unknown_assessment_is_safe_without_evidence(tmp_path: Path) -> None:
    store = _store(tmp_path)
    assessment = assess_test(store, "T1", "unknown")
    assert assessment["outcome"] == "unknown"
    state = store.load()
    execution = state.executions[-1]
    assert execution["operation"] == "assess_test"
    assert execution["outcome"] == "unknown"
    assert execution["test_id"] == "T1"


def test_decisive_assessment_persists_evidence_backed_execution(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _record(store)
    assessment = assess_test(
        store,
        "T1",
        "supported",
        evidence_refs=[EVIDENCE],
        coverage={"complete": True},
    )
    assert assessment["outcome"] == "supported"
    assert assessment["evidence_refs"] == [EVIDENCE]
    state = store.load()
    execution = state.executions[-1]
    assert execution["operation"] == "assess_test"
    assert execution["outcome"] == "supported"
    assert execution["evidence_refs"] == [EVIDENCE]


def test_invalid_decisive_assessment_does_not_mutate_state(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _record(store)
    before = len(store.load().executions)
    with pytest.raises(InvestigationError, match="Test Assessment"):
        assess_test(store, "T1", "supported", evidence_refs=[OTHER])
    assert len(store.load().executions) == before
