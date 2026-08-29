from __future__ import annotations

from tracecite.runtime.agent_api import RetrievalResult
from tracecite.runtime.evidence_progress import EvidenceProgressTracker
from tracecite.runtime.relationship_frontier import (
    attach_relationship_frontier,
    relationship_candidates,
    relationship_observations,
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
    assert all("recommended_action" not in row for row in rows)


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


def test_relationship_observations_bind_reference_to_visible_structured_anchor() -> None:
    text = (
        "200: - name: test.device/device-plugin-failures-3083\n"
        "201: resources:\n"
        "202: - health: Healthy\n"
        "203: resourceID: testdevice\n"
        "204: to equal\n"
        "205: - name: test.device/device-plugin-failures-5477\n"
    )

    rows = relationship_observations(text)

    relation = next(row for row in rows if row["object"]["key"] == "resourceID")
    assert relation["relation"] == "field_in_same_structured_block"
    assert relation["subject"] == {
        "key": "name",
        "value": "test.device/device-plugin-failures-3083",
    }
    assert relation["object"] == {"key": "resourceID", "value": "testdevice"}
    assert relation["visible_lines"] == [200, 203]
    assert relation["relation_id"].startswith("rel:")
    assert "action" not in relation


def test_relationship_observations_capture_same_line_reference_co_observation() -> None:
    rows = relationship_observations(
        "300: requestID=req-7 parentTraceID=trace-abc status=500\n"
    )

    assert len(rows) == 1
    assert rows[0]["relation"] == "co_observed_on_line"
    assert rows[0]["subject"] == {"key": "requestID", "value": "req-7"}
    assert rows[0]["object"] == {"key": "parentTraceID", "value": "trace-abc"}
    assert rows[0]["visible_lines"] == [300]


def test_expand_result_gets_evidence_only_observed_relations() -> None:
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
                    "uri": "evidence://sha256/" + "a" * 64 + "#L10-L13",
                    "source_path": "/tmp/runtime.log",
                    "sha256": "a" * 64,
                    "start_line": 10,
                    "end_line": 13,
                }
            ],
            "coverage": {"context_start_line": 10, "context_end_line": 13},
            "data": {
                "text": (
                    "10: - name: resource-a\n"
                    "11: resources:\n"
                    "12: resourceID: device-a\n"
                    "13: targetUID=abcde-12345\n"
                )
            },
        },
        progress=progress,
        new_evidence=(
            {
                "uri": "evidence://sha256/" + "a" * 64 + "#L10-L13",
                "source_path": "/tmp/runtime.log",
                "sha256": "a" * 64,
                "start_line": 10,
                "end_line": 13,
            },
        ),
    )

    enriched = attach_relationship_frontier(result)
    data = enriched.canonical_result["data"]

    assert data["observed_references"]
    assert data["observed_relations"]
    assert "textual-structure" in data["observed_relations_note"]
    assert "relationship_action" not in data
    assert "recommended_action" not in str(data)
