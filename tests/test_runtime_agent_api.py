from __future__ import annotations

import hashlib
import json

from tracecite.extension.evidence import EntityRef
from tracecite.extension.retrieval import (
    ProviderEvidence,
    RetrieveRequest as ProviderRetrieveRequest,
    RetrieveResult as ProviderRetrieveResult,
)
from tracecite.runtime import (
    EvidenceIdentity,
    EvidenceProgressTracker,
    EvidenceRequest,
    InvestigationStore,
    ProviderTarget,
    QueryTarget,
    RangeTarget,
    SourceVersion,
    traverse,
    retrieve,
)
from tracecite.runtime.retrieval_session import RetrievalSessionStore


def _sha256(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _clear_audit_executions(state_path) -> None:
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    payload["executions"] = []
    state_path.write_text(json.dumps(payload), encoding="utf-8")


def test_identity_keeps_record_event_and_group_layers_distinct() -> None:
    version = SourceVersion(
        namespace="sentry",
        source="project:1",
        kind="generation",
        value="42",
    )
    identity = EvidenceIdentity(
        record_id="record-1",
        event_id="event-9",
        group_id="group-a",
        source_version=version,
    )

    assert identity.record_key == (version.key, "record-1")
    assert identity.event_key == ("sentry", "event-9")
    assert identity.group_key == "group-a"
    assert identity.record_key != identity.event_key


def test_query_target_contains_query_semantics_not_result_budget_knobs() -> None:
    assert "max_evidence" not in QueryTarget.__dataclass_fields__
    assert "max_line_chars" not in QueryTarget.__dataclass_fields__


def test_mutable_source_version_is_not_immutable() -> None:
    version = SourceVersion(
        namespace="file",
        source="/tmp/live.log",
        kind="mutable",
    )
    assert version.immutable is False
    assert "@mutable:live" in version.key


def test_progress_restore_does_not_create_fake_no_growth_round() -> None:
    tracker = EvidenceProgressTracker()
    tracker.restore(
        source="file:a@sha256:" + "a" * 64,
        evidence_ids=("E1",),
        line_ranges=((10, 20),),
    )

    snapshot = tracker.snapshot(source="file:a@sha256:" + "a" * 64)
    assert snapshot.seen_evidence == 1
    assert snapshot.seen_lines == 11
    assert snapshot.consecutive_no_growth == 0
    payload = snapshot.to_dict()
    assert "ready_for_reasoning" not in payload
    assert "stop_recommended" not in payload
    assert "stop" not in payload
    assert snapshot.acquisition_end_reason is None


def test_progress_no_growth_remains_mechanical() -> None:
    tracker = EvidenceProgressTracker()
    tracker.observe(evidence_ids=("E1",))
    progress = tracker.observe(evidence_ids=("E1",))

    assert progress.delta.new_evidence == 0
    assert progress.consecutive_no_growth == 1
    assert progress.acquisition_end_reason is None
    payload = progress.to_dict()
    assert "ready_for_reasoning" not in payload
    assert "stop_recommended" not in payload
    assert "stop" not in payload


def test_retrieve_query_suppresses_repeated_evidence(tmp_path) -> None:
    source = tmp_path / "runtime.log"
    source.write_text("INFO boot\nERROR timeout request=7\nINFO done\n", encoding="utf-8")
    state_path = tmp_path / "investigation.json"
    InvestigationStore(state_path).create("why did request 7 fail?")

    first = retrieve(
        EvidenceRequest(
            QueryTarget(source, "timeout", snapshot=True),
            investigation_path=state_path,
        )
    )
    second = retrieve(
        EvidenceRequest(
            QueryTarget(source, "timeout", snapshot=True),
            investigation_path=state_path,
        )
    )

    assert first.status == "ok"
    assert len(first.new_evidence) == 1
    assert second.status == "no_new_evidence"
    assert second.new_evidence == ()
    assert second.repeated_evidence == 1
    assert second.acquisition_end_reason is None
    payload = second.to_dict()
    novelty = payload["data"]["novelty"]
    assert novelty["state"] == "no_new_evidence"
    assert "all_returned_evidence_already_seen" in novelty["basis"]
    assert payload["evidence"] == []
    assert second.canonical_result["evidence"] == []
    repeated = second.canonical_result["data"]["matched_existing_evidence"]
    assert len(repeated) == 1
    assert repeated[0]["uri"].startswith("evidence://sha256/")
    assert repeated[0]["start_line"] == 2


def test_retrieval_session_remains_novelty_owner_without_audit_executions(tmp_path) -> None:
    source = tmp_path / "runtime.log"
    source.write_text("ERROR timeout request=7\n", encoding="utf-8")
    state_path = tmp_path / "investigation.json"
    InvestigationStore(state_path).create("novelty state ownership")

    first = retrieve(
        EvidenceRequest(QueryTarget(source, "timeout"), investigation_path=state_path)
    )
    session_store = RetrievalSessionStore.for_investigation(state_path)
    assert session_store.path.is_file()
    assert session_store.load().seen_evidence

    _clear_audit_executions(state_path)
    second = retrieve(
        EvidenceRequest(QueryTarget(source, "timeout"), investigation_path=state_path)
    )

    assert first.new_evidence
    assert second.status == "no_new_evidence"
    assert second.repeated_evidence == 1


def test_audit_history_is_not_migrated_into_retrieval_novelty(tmp_path) -> None:
    source = tmp_path / "runtime.log"
    source.write_text("ERROR timeout request=7\n", encoding="utf-8")
    state_path = tmp_path / "investigation.json"
    InvestigationStore(state_path).create("legacy progress migration")

    first = retrieve(
        EvidenceRequest(QueryTarget(source, "timeout"), investigation_path=state_path)
    )
    session_store = RetrievalSessionStore.for_investigation(state_path)
    assert first.new_evidence
    session_store.path.unlink()
    assert not session_store.path.exists()

    migrated = retrieve(
        EvidenceRequest(QueryTarget(source, "timeout"), investigation_path=state_path)
    )

    assert session_store.path.is_file()
    assert migrated.status == "ok"
    assert migrated.new_evidence
    assert migrated.repeated_evidence == 0


def test_retrieve_range_hard_stops_only_for_same_immutable_version(tmp_path) -> None:
    source = tmp_path / "runtime.log"
    source.write_text("one\ntwo\nthree\nfour\nfive\n", encoding="utf-8")
    digest = _sha256(source)
    state_path = tmp_path / "investigation.json"
    InvestigationStore(state_path).create("inspect the relevant range")

    first = retrieve(
        EvidenceRequest(
            RangeTarget(
                source,
                3,
                before=1,
                after=1,
                expected_sha256=digest,
            ),
            investigation_path=state_path,
        )
    )
    second = retrieve(
        EvidenceRequest(
            RangeTarget(
                source,
                3,
                before=1,
                after=1,
                expected_sha256=digest,
            ),
            investigation_path=state_path,
        )
    )

    assert first.status == "ok"
    assert second.status == "no_new_evidence"
    assert second.acquisition_end_reason is None
    novelty = second.to_dict()["data"]["novelty"]
    assert novelty["state"] == "no_new_evidence"
    assert "immutable_source_identity" in novelty["basis"]

    source.write_text("one\ntwo changed\nthree\nfour\nfive\n", encoding="utf-8")
    changed = retrieve(
        EvidenceRequest(
            RangeTarget(
                source,
                3,
                before=1,
                after=1,
                expected_sha256=digest,
            ),
            investigation_path=state_path,
        )
    )
    assert changed.status == "error"
    assert changed.status != "no_new_evidence"


def test_range_coverage_remains_owned_by_session_without_audit_executions(tmp_path) -> None:
    source = tmp_path / "runtime.log"
    source.write_text("one\ntwo\nthree\nfour\nfive\n", encoding="utf-8")
    digest = _sha256(source)
    state_path = tmp_path / "investigation.json"
    InvestigationStore(state_path).create("range ownership")

    first = retrieve(
        EvidenceRequest(
            RangeTarget(source, 3, before=1, after=1, expected_sha256=digest),
            investigation_path=state_path,
        )
    )
    store = RetrievalSessionStore.for_investigation(state_path)
    assert store.load().covered_ranges
    _clear_audit_executions(state_path)

    second = retrieve(
        EvidenceRequest(
            RangeTarget(source, 3, before=1, after=1, expected_sha256=digest),
            investigation_path=state_path,
        )
    )

    assert first.status == "ok"
    assert second.status == "no_new_evidence"
    assert "requested_context_already_covered" in second.to_dict()["data"]["novelty"]["basis"]


def test_range_context_growth_is_not_suppressed_by_prior_search_pointer(tmp_path) -> None:
    source = tmp_path / "runtime.log"
    source.write_text("one\ntwo\nthree\nfour\nfive\n", encoding="utf-8")
    digest = _sha256(source)
    state_path = tmp_path / "investigation.json"
    InvestigationStore(state_path).create("search then recover exact context")

    broad = retrieve(
        EvidenceRequest(
            QueryTarget(source, ".*", regex=True, snapshot=False),
            investigation_path=state_path,
        )
    )
    assert broad.status == "ok"
    assert broad.new_evidence

    expanded = retrieve(
        EvidenceRequest(
            RangeTarget(source, 3, before=1, after=1, expected_sha256=digest),
            investigation_path=state_path,
        )
    )
    assert expanded.status == "ok"
    assert expanded.progress.delta.new_lines == 3
    assert expanded.acquisition_end_reason is None
    assert expanded.new_evidence
    text = expanded.to_dict()["data"]["text"]
    assert "2: two" in text
    assert "3: three" in text
    assert "4: four" in text

    repeated = retrieve(
        EvidenceRequest(
            RangeTarget(source, 3, before=1, after=1, expected_sha256=digest),
            investigation_path=state_path,
        )
    )
    assert repeated.status == "no_new_evidence"
    assert repeated.progress.delta.new_lines == 0


class _Provider:
    name = "demo"

    def can_handle(self, request: ProviderRetrieveRequest) -> bool:
        return bool(request.evidence_ids or request.entities)

    def retrieve(self, request: ProviderRetrieveRequest) -> ProviderRetrieveResult:
        return ProviderRetrieveResult(
            status="ok",
            evidence=(
                ProviderEvidence(
                    id="record-1",
                    kind="log",
                    source="demo-source",
                    label="timeout",
                    evidence_uri="evidence://demo/record-1",
                    entities=(EntityRef(kind="request", value="7", namespace="demo"),),
                ),
            ),
            coverage={"complete": True},
        )


def test_provider_target_extends_retrieve_without_new_top_level_api(tmp_path) -> None:
    state_path = tmp_path / "investigation.json"
    InvestigationStore(state_path).create("provider evidence")
    provider_request = ProviderRetrieveRequest(evidence_ids=("record-1",))

    first = retrieve(
        EvidenceRequest(
            ProviderTarget(provider_request),
            providers=(_Provider(),),
            investigation_path=state_path,
        )
    )
    second = retrieve(
        EvidenceRequest(
            ProviderTarget(provider_request),
            providers=(_Provider(),),
            investigation_path=state_path,
        )
    )

    assert first.status == "ok"
    assert len(first.new_evidence) == 1
    assert second.status == "no_new_evidence"
    assert second.new_evidence == ()


def test_investigate_reports_mechanical_frontier_stop() -> None:
    result = traverse((_Provider(),), seed_evidence_ids=("record-1",))

    assert result.traversal.status == "ok"
    assert result.traversal.stop_reason == "frontier_exhausted"
    assert result.acquisition_end_reason is not None
    assert result.acquisition_end_reason.kind == "frontier_exhausted"
    assert result.progress.frontier_exhausted is True
    assert "stop" not in result.to_dict()
