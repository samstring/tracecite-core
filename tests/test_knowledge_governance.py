from __future__ import annotations

import json
import multiprocessing
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


def _verify_in_process(path: str, candidate_id: str, case_id: str, queue) -> None:
    try:
        result = KnowledgeGovernanceStore(Path(path)).verify(
            candidate_id,
            case_id=case_id,
            outcome="support",
            evidence_refs=[f"evidence://{case_id}"],
            verified_by=f"reviewer-{case_id}",
        )
        queue.put(("ok", result.status))
    except Exception as exc:  # pragma: no cover - asserted by parent process
        queue.put(("error", repr(exc)))


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


def test_legacy_store_migrates_to_current_schema(tmp_path: Path) -> None:
    path = tmp_path / "legacy.json"
    legacy = {
        "schema_version": 1,
        "revision": 4,
        "policy": {
            "min_independent_cases": 2,
            "require_distinct_reviewer": True,
            "allow_contradictions": False,
        },
        "candidates": [
            {
                "id": "kc-legacy",
                "kind": "learning",
                "payload": {"summary": "legacy"},
                "domain": "unit",
                "scope": "global",
                "created_by": "agent-a",
                "created_at": "2025-01-01T00:00:00+00:00",
                "status": "promoted",
                "verifications": [],
                "promoted_at": "2025-01-02T00:00:00+00:00",
                "approved_by": "reviewer",
                "promotion_result": {},
            }
        ],
        "managed_targets": {},
    }
    path.write_text(json.dumps(legacy), encoding="utf-8")
    store = KnowledgeGovernanceStore(path)

    candidate = store.get("kc-legacy")
    assert candidate.validity["source_version"] == "unknown"
    migrated = store.migrate()
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert migrated["schema_version"] == 2
    assert persisted["schema_version"] == 2
    assert persisted["candidates"][0]["version"] == 1


def test_validity_expiry_is_explicit_and_revalidation_restores_current(
    tmp_path: Path,
) -> None:
    target = tmp_path / "knowledge.json"
    target.write_text("{}\n", encoding="utf-8")
    store = KnowledgeGovernanceStore(tmp_path / "candidates.json")
    candidate = _propose(store)
    store.verify(
        candidate.id,
        case_id="case-2",
        outcome="support",
        evidence_refs=["evidence://run/2"],
        verified_by="agent-b",
    )
    promoted = store.promote(
        candidate.id,
        approved_by="reviewer",
        promoter=lambda _: {},
        target_name="unit",
        target_path=target,
        source_version="logs-2025",
        tool_version="tracecite-0.1",
        schema_version="knowledge-1",
        reviewed_at="2025-01-01T00:00:00+00:00",
        expires_at="2025-02-01T00:00:00+00:00",
        revalidate_after="2025-01-15T00:00:00+00:00",
        conditions={"input_kind": "request logs"},
    )
    stale = store.evaluate_validity(
        promoted.id,
        now="2025-01-20T00:00:00+00:00",
    )
    assert stale["state"] == "stale"
    assert stale["usable"] is False
    expired = store.evaluate_validity(
        promoted.id,
        now="2025-03-01T00:00:00+00:00",
    )
    assert expired["state"] == "expired"
    assert expired["usable"] is False
    assert expired["conditions_unverified"] is True

    store.revalidate(
        promoted.id,
        reviewed_by="reviewer-2",
        reviewed_at="2025-03-01T00:00:00+00:00",
        expires_at="2025-04-01T00:00:00+00:00",
    )
    current = store.evaluate_validity(
        promoted.id,
        now="2025-03-15T00:00:00+00:00",
    )
    assert current["state"] == "current"
    assert store.is_current(promoted.id, now="2025-03-15T00:00:00+00:00")
    assert len(store.get(promoted.id).revalidation_history) == 1


def test_supersession_preserves_old_payload_and_lineage(tmp_path: Path) -> None:
    store = KnowledgeGovernanceStore(tmp_path / "candidates.json")
    original = _propose(store)
    replacement = store.supersede(
        original.id,
        payload={"summary": "new semantics"},
        created_by="agent-b",
        case_id="case-2",
        evidence_refs=["evidence://run/2"],
    )

    assert replacement.version == 2
    assert replacement.supersedes == original.id
    assert store.get(original.id).status == "superseded"
    assert store.get(original.id).superseded_by == replacement.id
    assert store.evaluate_validity(original.id)["state"] == "superseded"
    assert store.get(original.id).payload == {"summary": "bounded evidence is required"}
    assert store.supersede(
        original.id,
        payload={"ignored": True},
        created_by="agent-c",
        case_id="case-3",
        evidence_refs=["evidence://run/3"],
    ).id == replacement.id


def test_unpromoted_replacement_does_not_displace_current_knowledge(
    tmp_path: Path,
) -> None:
    target = tmp_path / "knowledge.json"
    target.write_text("{}\n", encoding="utf-8")
    store = KnowledgeGovernanceStore(tmp_path / "candidates.json")
    original = _propose(store)
    store.verify(
        original.id,
        case_id="case-2",
        outcome="support",
        evidence_refs=["evidence://run/2"],
        verified_by="agent-b",
    )
    store.promote(
        original.id,
        approved_by="reviewer",
        promoter=lambda _: {},
        target_name="unit",
        target_path=target,
    )
    replacement = store.supersede(
        original.id,
        payload={"summary": "replacement"},
        created_by="agent-c",
        case_id="case-3",
        evidence_refs=["evidence://run/3"],
    )
    assert store.get(original.id).status == "promoted"
    assert store.evaluate_validity(original.id)["state"] == "current"
    assert store.evaluate_validity(replacement.id)["state"] == "not_promoted"

    store.verify(
        replacement.id,
        case_id="case-4",
        outcome="support",
        evidence_refs=["evidence://run/4"],
        verified_by="agent-d",
    )
    store.promote(
        replacement.id,
        approved_by="reviewer-2",
        promoter=lambda _: {},
        target_name="unit",
        target_path=target,
    )
    assert store.get(original.id).status == "superseded"
    assert store.evaluate_validity(original.id)["state"] == "superseded"
    assert store.evaluate_validity(replacement.id)["state"] == "current"


def test_promote_is_idempotent_after_success(tmp_path: Path) -> None:
    target = tmp_path / "knowledge.json"
    target.write_text("{}\n", encoding="utf-8")
    store = KnowledgeGovernanceStore(tmp_path / "candidates.json")
    candidate = _propose(store)
    store.verify(
        candidate.id,
        case_id="case-2",
        outcome="support",
        evidence_refs=["evidence://run/2"],
        verified_by="agent-b",
    )
    calls = []

    def promoter(_candidate):
        calls.append(True)
        return {"ok": True}

    first = store.promote(
        candidate.id,
        approved_by="reviewer",
        promoter=promoter,
        target_name="unit",
        target_path=target,
    )
    second = store.promote(
        candidate.id,
        approved_by="reviewer",
        promoter=promoter,
        target_name="unit",
        target_path=target,
    )
    assert first.id == second.id
    assert calls == [True]


def test_cross_process_verifications_do_not_lose_updates(tmp_path: Path) -> None:
    path = tmp_path / "candidates.json"
    store = KnowledgeGovernanceStore(path)
    candidate = _propose(store)
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    processes = [
        context.Process(
            target=_verify_in_process,
            args=(str(path), candidate.id, case_id, queue),
        )
        for case_id in ("case-2", "case-3")
    ]
    for process in processes:
        process.start()
    results = [queue.get(timeout=10) for _ in processes]
    for process in processes:
        process.join(timeout=10)
        assert process.exitcode == 0
    assert all(status == "ok" for status, _ in results)
    final = KnowledgeGovernanceStore(path).get(candidate.id)
    assert final.support_count == 3
    assert final.status == "verified"


@pytest.mark.parametrize(
    "field_value",
    [
        None,
        ["not-an-object"],
        [{}] * 33,
    ],
)
def test_tampered_revalidation_history_fails_closed(
    tmp_path: Path, field_value: object
) -> None:
    path = tmp_path / "candidates.json"
    store = KnowledgeGovernanceStore(path)
    candidate = _propose(store)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["candidates"][0]["revalidation_history"] = field_value
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(KnowledgeGovernanceError, match="revalidation_history"):
        store.get(candidate.id)


def test_tampered_promotion_result_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "candidates.json"
    store = KnowledgeGovernanceStore(path)
    candidate = _propose(store)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["candidates"][0]["promotion_result"] = "not-an-object"
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(KnowledgeGovernanceError, match="promotion_result"):
        store.get(candidate.id)


def test_oversized_promotion_result_is_rejected_before_persisting(
    tmp_path: Path,
) -> None:
    target = tmp_path / "knowledge.json"
    target.write_text("{}\n", encoding="utf-8")
    store = KnowledgeGovernanceStore(tmp_path / "candidates.json")
    candidate = _propose(store)
    store.verify(
        candidate.id,
        case_id="case-2",
        outcome="support",
        evidence_refs=["evidence://run/2"],
        verified_by="agent-b",
    )

    with pytest.raises(KnowledgeGovernanceError, match="promotion_result"):
        store.promote(
            candidate.id,
            approved_by="reviewer",
            promoter=lambda _: {"large": "x" * 20_000},
            target_name="unit",
            target_path=target,
        )
    assert store.get(candidate.id).status == "verified"
