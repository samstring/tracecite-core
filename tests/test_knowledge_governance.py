from __future__ import annotations

import json
from pathlib import Path

import pytest

from tracecite.knowledge import (
    KnowledgeGovernanceError,
    KnowledgeGovernanceStore,
)


def _propose(store: KnowledgeGovernanceStore):
    return store.propose(
        kind="learning",
        payload={"summary": "bounded evidence is required"},
        domain="unit",
        scope="global",
        created_by="agent-a",
        case_id="case-1",
        evidence_refs=["evidence://run/1#event=1"],
    )


def test_candidate_is_separate_and_requires_independent_cases(tmp_path: Path) -> None:
    store_path = tmp_path / "candidates.json"
    store = KnowledgeGovernanceStore(store_path)
    candidate = _propose(store)

    assert candidate.status == "candidate"
    assert candidate.support_count == 1
    assert store_path.is_file()
    assert json.loads(store_path.read_text())["candidates"][0]["kind"] == "learning"

    verified = store.verify(
        candidate.id,
        case_id="case-2",
        outcome="support",
        evidence_refs=["evidence://run/2#event=4"],
        verified_by="agent-b",
    )
    assert verified.status == "verified"
    assert verified.support_count == 2


def test_duplicate_case_and_contradiction_block_promotion(tmp_path: Path) -> None:
    target = tmp_path / "knowledge.json"
    target.write_text("{}\n", encoding="utf-8")
    store = KnowledgeGovernanceStore(tmp_path / "candidates.json")
    candidate = _propose(store)
    with pytest.raises(KnowledgeGovernanceError, match="不能重复计数"):
        store.verify(
            candidate.id,
            case_id="case-1",
            outcome="support",
            evidence_refs=["evidence://duplicate"],
            verified_by="agent-b",
        )
    contradicted = store.verify(
        candidate.id,
        case_id="case-2",
        outcome="contradict",
        evidence_refs=["evidence://run/2#counterexample"],
        verified_by="agent-b",
    )
    assert contradicted.status == "contradicted"
    store.register_target("unit", target)
    with pytest.raises(KnowledgeGovernanceError, match="不能晋升"):
        store.promote(
            candidate.id,
            approved_by="reviewer",
            promoter=lambda _: {},
            target_name="unit",
            target_path=target,
        )


def test_promotion_requires_reviewer_and_tracks_target_integrity(tmp_path: Path) -> None:
    target = tmp_path / "knowledge.json"
    target.write_text("{}\n", encoding="utf-8")
    store = KnowledgeGovernanceStore(tmp_path / "candidates.json")
    candidate = _propose(store)
    store.verify(
        candidate.id,
        case_id="case-2",
        outcome="support",
        evidence_refs=["evidence://run/2#event=4"],
        verified_by="agent-b",
    )
    store.register_target("unit", target)

    with pytest.raises(KnowledgeGovernanceError, match="不能批准自己"):
        store.promote(
            candidate.id,
            approved_by="agent-a",
            promoter=lambda _: {},
            target_name="unit",
            target_path=target,
        )

    def promoter(_candidate):
        target.write_text('{"promoted": true}\n', encoding="utf-8")
        return {"changed": True}

    promoted = store.promote(
        candidate.id,
        approved_by="human-reviewer",
        promoter=promoter,
        target_name="unit",
        target_path=target,
    )
    assert promoted.status == "promoted"
    assert promoted.approved_by == "human-reviewer"
    assert store.check_target("unit", target)["status"] == "ok"

    target.write_text('{"unreviewed": true}\n', encoding="utf-8")
    assert store.check_target("unit", target)["status"] == "modified"


def test_proposal_requires_evidence(tmp_path: Path) -> None:
    store = KnowledgeGovernanceStore(tmp_path / "candidates.json")
    with pytest.raises(KnowledgeGovernanceError, match="evidence_refs"):
        store.propose(
            kind="learning",
            payload={"summary": "unsupported"},
            domain="unit",
            scope="global",
            created_by="agent-a",
            case_id="case-1",
            evidence_refs=[],
        )
