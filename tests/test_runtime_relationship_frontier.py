from __future__ import annotations

from tracecite.runtime.agent_api import RetrievalResult
from tracecite.runtime.evidence_progress import EvidenceProgressTracker
from tracecite.runtime.relationship_frontier import (
    attach_relationship_frontier,
    relationship_candidates,
)


def test_relationship_candidates_extract_generic_reference_fields_without_status_noise() -> None:
    text = (
        "101: event=request_failed requestID=req-7 parentTraceID=trace-abc status=500\n"
        "102: targetUID=7f5e8a10-1111-2222-3333-444455556666 ownerRef=user-42\n"
    )

    rows = relationship_candidates(text)
    pairs = {(row["key"], row["value"]) for row in rows}

    assert ("targetUID", "7f5e8a10-1111-2222-3333-444455556666") in pairs
    assert ("parentTraceID", "trace-abc") in pairs
    assert ("requestID", "req-7") in pairs
    assert ("ownerRef", "user-42") in pairs
    assert all(row["key"] != "status" for row in rows)
    assert rows[0]["recommended_action"]["operation"] == "search"


def test_relationship_candidates_work_for_unrelated_mobile_style_identifiers() -> None:
    text = (
        "44: crash sessionUID=550e8400-e29b-41d4-a716-446655440000 ownerRef=screen-home\n"
        "45: traceID=trace-mobile-9 sourceKey=ios-client level=error\n"
    )

    rows = relationship_candidates(text)
    values = {row["value"] for row in rows}

    assert "550e8400-e29b-41d4-a716-446655440000" in values
    assert "screen-home" in values
    assert "trace-mobile-9" in values
    assert "ios-client" in values


def test_expand_result_gets_mechanical_relationship_frontier() -> None:
    progress = EvidenceProgressTracker().observe(evidence_ids=("E1",))
    result = RetrievalResult(
        operation="expand",
        status="ok",
        canonical_result={
            "operation": "expand",
            "status": "ok",
            "outcome": "not_assessed",
            "evidence": [
                {
                    "uri": "evidence://sha256/" + "a" * 64 + "#L10-L11",
                    "source_path": "/tmp/runtime.log",
                    "sha256": "a" * 64,
                    "start_line": 10,
                    "end_line": 11,
                }
            ],
            "coverage": {"context_start_line": 10, "context_end_line": 11},
            "data": {
                "text": "10: update resourceID=device-a targetUID=abcde-12345\n11: done status=ok\n"
            },
        },
        progress=progress,
        new_evidence=(
            {
                "uri": "evidence://sha256/" + "a" * 64 + "#L10-L11",
                "source_path": "/tmp/runtime.log",
                "sha256": "a" * 64,
                "start_line": 10,
                "end_line": 11,
            },
        ),
    )

    enriched = attach_relationship_frontier(result)
    data = enriched.canonical_result["data"]

    assert data["relationship_frontier"]
    assert data["relationship_action"]["operation"] == "search"
    assert data["relationship_action"]["query"] == "abcde-12345"
    assert "causal" in data["relationship_frontier"][0]["note"]
