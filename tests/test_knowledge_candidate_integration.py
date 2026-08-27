from __future__ import annotations

import json
from pathlib import Path

import pytest

from tracecite import InvestigationError, InvestigationStore
from tracecite.knowledge import KnowledgeGovernanceError, KnowledgeGovernanceStore


SUPPORT_REF = "evidence://sha256/" + ("a" * 64) + "#L2-L3"
CONTRADICT_REF = "evidence://sha256/" + ("b" * 64) + "#L8"
SECOND_SUPPORT_REF = "evidence://sha256/" + ("c" * 64) + "#L3-L4"


def _ready(tmp_path: Path, *, outcome: str = "supported") -> tuple[InvestigationStore, dict]:
    state = InvestigationStore(tmp_path / "investigation.json")
    state.create("why did the request fail?", created_by="agent-a", investigation_id="INV-1")
    state.add_hypothesis("the request timed out", hypothesis_id="H1")
    state.add_test(
        "H1",
        "inspect timeout records",
        expected_observation="timeout is present",
        contradicting_observation="request completed successfully",
        strategy={"operation": "search", "query": "timeout"},
        test_id="T1",
    )
    if outcome in {"supported", "contradicted"}:
        evidence_ref = SUPPORT_REF if outcome == "supported" else CONTRADICT_REF
        state.record_execution(
            "search",
            {
                "status": "ok",
                "outcome": "not_assessed",
                "evidence": [{"uri": evidence_ref}],
                "coverage": {"records": 1, "complete": True},
                "verification": {"integrity_checked": True},
            },
            hypothesis_id="H1",
            test_id="T1",
        )
    finding = state.add_finding(
        "H1",
        outcome,
        "timeout evidence was found" if outcome == "supported" else "not enough evidence",
        supporting_evidence=[SUPPORT_REF] if outcome == "supported" else (),
        contradicting_evidence=[CONTRADICT_REF] if outcome == "contradicted" else (),
        coverage={"records": 1, "complete": True} if outcome != "unknown" else {},
        limitations=["one bounded sample"],
    )
    return state, finding


def test_supported_finding_proposal_contains_refs_scope_tests_and_source(
    tmp_path: Path,
) -> None:
    state, finding = _ready(tmp_path)
    candidate_store = KnowledgeGovernanceStore(tmp_path / "candidates.json")

    candidate = state.propose_knowledge_candidate(
        finding["id"],
        candidate_store,
        applicability={"input_kind": "request logs"},
        exclusions=["synthetic test traffic"],
    )

    assert candidate.status == "candidate"
    assert candidate.payload["investigation_id"] == "INV-1"
    assert candidate.payload["hypothesis_claim"] == "the request timed out"
    assert candidate.payload["outcome"] == "supported"
    assert candidate.payload["applicability"] == {"input_kind": "request logs"}
    assert candidate.payload["exclusions"] == ["synthetic test traffic"]
    assert candidate.payload["supporting_refs"] == [SUPPORT_REF]
    assert candidate.payload["contradicting_refs"] == []
    assert candidate.payload["coverage"] == {"records": 1, "complete": True}
    assert candidate.payload["limitations"] == ["one bounded sample"]
    assert candidate.payload["test_strategy"][0]["strategy"]["query"] == "timeout"
    assert candidate.payload["test_recipes"][0]["expected_observation"] == "timeout is present"
    assert candidate.payload["source_schema"] == 1
    assert candidate.payload["source_revision"] == 4

    persisted = json.loads(state.path.read_text(encoding="utf-8"))
    link = persisted["knowledge_candidates"]
    assert len(link) == 1
    assert link[0]["candidate_id"] == candidate.id
    assert link[0]["finding_id"] == finding["id"]
    assert link[0]["status"] == "candidate"
    assert "payload" not in link[0]
    assert "hypothesis_claim" not in json.dumps(link)


@pytest.mark.parametrize("outcome", ["unknown", "contradicted"])
def test_unknown_or_contradicted_finding_is_not_eligible(
    tmp_path: Path, outcome: str
) -> None:
    state, finding = _ready(tmp_path, outcome=outcome)
    with pytest.raises(InvestigationError, match="只有 supported"):
        state.propose_knowledge_candidate(
            finding["id"],
            governance_store_path=tmp_path / "candidates.json",
            applicability={},
            exclusions=[],
        )
    assert not (tmp_path / "candidates.json").exists()
    assert state.load().knowledge_candidates == []


def test_duplicate_proposal_is_idempotent_and_does_not_add_candidates(
    tmp_path: Path,
) -> None:
    state, finding = _ready(tmp_path)
    path = tmp_path / "candidates.json"
    first = state.propose_knowledge_candidate(
        finding["id"], governance_store_path=path, applicability={}, exclusions=[]
    )
    second = state.propose_knowledge_candidate(
        finding["id"], governance_store_path=path, applicability={}, exclusions=[]
    )
    assert second.id == first.id
    assert len(KnowledgeGovernanceStore(path).list_candidates()) == 1
    assert len(state.load().knowledge_candidates) == 1


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("applicability", {"input_kind": "different"}),
        ("exclusions", ["different exclusion"]),
        ("kind", "different-kind"),
        ("domain", "different-domain"),
        ("scope", "different-scope"),
        ("created_by", "different-agent"),
        ("case_id", "different-case"),
    ],
)
def test_duplicate_proposal_with_parameter_drift_is_a_conflict(
    tmp_path: Path, field: str, value: object
) -> None:
    state, finding = _ready(tmp_path)
    path = tmp_path / "candidates.json"
    state.propose_knowledge_candidate(
        finding["id"],
        governance_store_path=path,
        applicability={"input_kind": "request logs"},
        exclusions=["synthetic test traffic"],
        created_by="agent-a",
        case_id="case-1",
    )
    kwargs = {
        "applicability": {"input_kind": "request logs"},
        "exclusions": ["synthetic test traffic"],
        "created_by": "agent-a",
        "case_id": "case-1",
    }
    kwargs[field] = value
    with pytest.raises(InvestigationError, match="候选提案冲突"):
        state.propose_knowledge_candidate(
            finding["id"], governance_store_path=path, **kwargs
        )
    assert len(KnowledgeGovernanceStore(path).list_candidates()) == 1


def test_duplicate_proposal_to_a_different_store_is_a_conflict(tmp_path: Path) -> None:
    state, finding = _ready(tmp_path)
    first_path = tmp_path / "candidates.json"
    state.propose_knowledge_candidate(finding["id"], governance_store_path=first_path)
    with pytest.raises(InvestigationError, match="store_path"):
        state.propose_knowledge_candidate(
            finding["id"], governance_store_path=tmp_path / "other.json"
        )
    assert not (tmp_path / "other.json").exists()


def test_candidate_support_refs_must_be_immutable_citable_evidence_uris(
    tmp_path: Path,
) -> None:
    state, finding = _ready(tmp_path)
    raw = json.loads(state.path.read_text(encoding="utf-8"))
    raw["findings"][0]["supporting_evidence"] = ["evidence://run/1#L2"]
    state.path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(InvestigationError, match="带 SHA-256 摘要和行范围"):
        state.propose_knowledge_candidate(
            finding["id"], governance_store_path=tmp_path / "candidates.json"
        )
    assert not (tmp_path / "candidates.json").exists()

    for invalid in (
        "evidence://sha256/abc#L1",
        "evidence://sha256/" + ("a" * 64) + "#L4-L2",
        "manifest://sha256/" + ("a" * 64),
    ):
        raw["findings"][0]["supporting_evidence"] = [invalid]
        state.path.write_text(json.dumps(raw), encoding="utf-8")
        with pytest.raises(InvestigationError, match="带 SHA-256 摘要和行范围"):
            state.propose_knowledge_candidate(
                finding["id"], governance_store_path=tmp_path / "candidates.json"
            )


def test_failed_governance_proposal_does_not_claim_state_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state, finding = _ready(tmp_path)
    candidate_store = KnowledgeGovernanceStore(tmp_path / "candidates.json")

    def fail(**_kwargs):
        raise KnowledgeGovernanceError("store unavailable")

    monkeypatch.setattr(candidate_store, "propose", fail)
    with pytest.raises(KnowledgeGovernanceError, match="store unavailable"):
        state.propose_knowledge_candidate(
            finding["id"],
            candidate_store,
            applicability={},
            exclusions=[],
        )
    assert state.load().knowledge_candidates == []


def test_candidate_still_requires_independent_review_before_promotion(
    tmp_path: Path,
) -> None:
    state, finding = _ready(tmp_path)
    candidate_path = tmp_path / "candidates.json"
    curated_path = tmp_path / "curated.json"
    curated_path.write_text("{}\n", encoding="utf-8")
    candidate = state.propose_knowledge_candidate(
        finding["id"],
        governance_store_path=candidate_path,
        applicability={},
        exclusions=[],
    )
    store = KnowledgeGovernanceStore(candidate_path)
    store.register_target("generic", curated_path)
    with pytest.raises(KnowledgeGovernanceError, match="不能晋升"):
        store.promote(
            candidate.id,
            approved_by="reviewer",
            promoter=lambda _: {},
            target_name="generic",
            target_path=curated_path,
        )
    store.verify(
        candidate.id,
        case_id="independent-case-2",
        outcome="support",
        evidence_refs=[SECOND_SUPPORT_REF],
        verified_by="reviewer",
    )
    promoted = store.promote(
        candidate.id,
        approved_by="reviewer",
        promoter=lambda _: {"ok": True},
        target_name="generic",
        target_path=curated_path,
    )
    assert promoted.status == "promoted"
