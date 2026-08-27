from __future__ import annotations

import pytest

from tracecite.extension import (
    CapabilityResult,
    ContractError,
    Coverage,
    DomainEvent,
    EvidenceRef,
    ExtensionManifest,
    SourceChunk,
    SourceCursor,
    SourceDescriptor,
)


def test_domain_event_keeps_fact_and_evidence_without_runtime_relevance() -> None:
    ref = EvidenceRef(
        source_id="snapshot-1",
        start_line=12,
        end_line=14,
        digest="abc123",
    )
    event = DomainEvent(
        type="mobile.network.request_failed",
        timestamp="2026-08-27T10:00:00Z",
        severity="ERROR",
        attributes={"status": 504, "endpoint": "/home"},
        evidence=(ref,),
    )

    payload = event.to_dict()
    assert payload["type"] == "mobile.network.request_failed"
    assert payload["severity"] == "error"
    assert payload["attributes"]["status"] == 504
    assert payload["evidence"][0]["start_line"] == 12
    assert "relevance" not in payload


def test_source_cursor_is_opaque_and_chunk_requires_same_source() -> None:
    source = SourceDescriptor(id="device-log", kind="stream", mutable=True)
    cursor = SourceCursor(source_id="device-log", token={"segment": 4, "offset": 10})
    chunk = SourceChunk(
        source=source,
        records=("a", "b"),
        next_cursor=cursor,
        coverage=Coverage(complete=False, scanned=2, returned=2),
    )
    assert chunk.next_cursor == cursor
    assert chunk.records == ("a", "b")

    with pytest.raises(ContractError, match="同一个 source"):
        SourceChunk(
            source=source,
            next_cursor=SourceCursor(source_id="other", token=1),
        )


def test_capability_result_keeps_execution_status_separate_from_findings() -> None:
    result = CapabilityResult(
        status="ok",
        value={"count": 3},
        coverage=Coverage(complete=False, returned=3, omitted=7, reasons=("budget",)),
    )
    assert result.status == "ok"
    assert result.coverage.omitted == 7
    assert not hasattr(result, "outcome")


def test_manifest_rejects_wrong_protocol_version() -> None:
    with pytest.raises(ContractError, match="protocol"):
        ExtensionManifest(
            id="bad",
            version="1",
            domain="unit",
            protocol_version="999",
        )
