from __future__ import annotations

import hashlib

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
    StopReason,
    investigate,
    retrieve,
)


def _sha256(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    assert snapshot.stop_recommended is False


def test_progress_exposes_formal_no_new_evidence_stop() -> None:
    tracker = EvidenceProgressTracker()
    tracker.observe(evidence_ids=("E1",))
    readiness = tracker.observe(evidence_ids=("E1",))

    assert readiness.stop_recommended is True
    assert isinstance(readiness.stop, StopReason)
    assert readiness.stop.kind == "no_new_evidence"
    assert readiness.to_dict()["stop"]["kind"] == "no_new_evidence"


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
    assert second.stop_reason is not None
    assert second.stop_reason.kind == "no_new_evidence"
    assert second.to_dict()["evidence"] == []
    assert len(second.canonical_result["evidence"]) == 1


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
    assert second.stop_reason is not None
    assert "immutable_source_identity" in second.stop_reason.basis

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
    result = investigate((_Provider(),), seed_evidence_ids=("record-1",))

    assert result.investigation.status == "ok"
    assert result.investigation.stop_reason == "frontier_exhausted"
    assert result.stop_reason is not None
    assert result.stop_reason.kind == "frontier_exhausted"
    assert result.progress.frontier_exhausted is True
