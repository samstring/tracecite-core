from __future__ import annotations

import hashlib
from pathlib import Path

from tracecite import (
    AggregateRequest,
    EvidenceRequest,
    QueryTarget,
    RangeTarget,
    RetrievalSessionStore,
    aggregate,
    materialize,
    replay,
    retrieve,
)
from tracecite.evaluation_contract import RunValidity
from tracecite.integrations import ToolActivityEvent, ToolActivityLedger


def _session(tmp_path: Path) -> RetrievalSessionStore:
    return RetrievalSessionStore(tmp_path, "canonical", namespace="_retrieval_sessions", legacy_evidence_context=False)


def test_retrieve_materialize_replay_share_one_session(tmp_path: Path) -> None:
    source = tmp_path / "app.log"
    source.write_text("INFO boot\nERROR timeout id=7\nINFO done\n", encoding="utf-8")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    session = _session(tmp_path)

    first = retrieve(EvidenceRequest(QueryTarget(source, "timeout")), session=session)
    second = retrieve(EvidenceRequest(QueryTarget(source, "ERROR")), session=session)
    assert first.new_evidence
    assert second.new_evidence == ()
    matched = second.to_dict()["data"]["matched_existing_evidence"]
    assert matched and matched[0]["start_line"] == 2

    materialized = materialize(
        RangeTarget(source, 2, before=1, after=1, expected_sha256=digest),
        session=session,
    )
    assert "ERROR timeout" in materialized.to_dict()["data"]["new_text"]

    before = session.load().retrieval_summary()
    replayed = replay(
        RangeTarget(source, 2, before=1, after=1, expected_sha256=digest),
        session=session,
    )
    after = session.load().retrieval_summary()
    assert replayed.to_dict()["data"]["replayed"] is True
    assert replayed.to_dict()["coverage"]["new_evidence"] == 0
    assert after["operation_counts"]["replay"] == before["operation_counts"].get("replay", 0) + 1
    # Replay is recorded as replay, not as new retrieval novelty.
    assert after["recent_with_new_evidence"] == before["recent_with_new_evidence"]


def test_aggregate_is_complete_mechanical_provenance(tmp_path: Path) -> None:
    source = tmp_path / "app.log"
    source.write_text("ERROR x\nINFO y\nERROR x\nERROR z\n", encoding="utf-8")
    counted = aggregate(AggregateRequest(source, "ERROR", operation="count"))
    assert counted["data"]["count"] == 3
    assert counted["coverage"]["complete"] is True
    assert len(counted["sha256"]) == 64

    distinct = aggregate(AggregateRequest(source, "ERROR", operation="distinct"))
    assert distinct["data"]["distinct_total"] == 2

    grouped = aggregate(
        AggregateRequest(source, "ERROR", operation="group", group_regex=r"ERROR\s+(\w+)")
    )
    assert grouped["data"]["groups"][0] == {"key": "x", "count": 2}


def test_host_activity_is_not_core_evidence_state() -> None:
    ledger = ToolActivityLedger()
    ledger.record(ToolActivityEvent("tracecite_retrieve", "tracecite_evidence"))
    ledger.record(ToolActivityEvent("grep", "native_search"))
    ledger.record(ToolActivityEvent("read", "native_read"))
    summary = ledger.summary()
    assert summary["total_tool_calls"] == 3
    assert summary["categories"]["native_search"] == 1
    assert "should_stop" not in repr(ledger.checkpoint_view())


def test_provider_contamination_is_separate_validity() -> None:
    clean = RunValidity.from_provider_signals("ok")
    dirty = RunValidity.from_provider_signals("429 all endpoints overloaded")
    assert clean.valid_for_product_comparison is True
    assert dirty.valid_for_product_comparison is False
    assert "provider_rate_limit" in dirty.invalid_reasons
