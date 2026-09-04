from __future__ import annotations

from tracecite.runtime.agent_api import RetrievalResult
from tracecite.runtime.evidence_progress import EvidenceProgressTracker
from tracecite.runtime.retrieval_guidance import prioritize_actionable_retrieval


def _result(*, entity_count: int = 1) -> RetrievalResult:
    entities = [
        {"entity": "vendor.example/device-run-3083", "scope": "vendor.example/"}
    ]
    if entity_count >= 2:
        entities.append(
            {"entity": "vendor.example/device-run-5477", "scope": "vendor.example/"}
        )
    canonical = {
        "operation": "search",
        "status": "ok",
        "outcome": "not_assessed",
        "evidence": [{"uri": "evidence://sha256/abc#L10", "label": "observed"}],
        "coverage": {"match_records": 2},
        "data": {
            "query": "local-device",
            "actionable_retrieval": {
                "operation": "search",
                "query": "device-run-3083",
            },
            "signal_hints": [{"line": 999, "label": "fatal"}],
            "signal_hint_note": (
                "Truncated-search high-signal candidates; materialize the referenced line before citing."
            ),
            "evidence_integrity": {
                "scoped_identity": [
                    {
                        "source": "evidence.log",
                        "identity_verification": [
                            {
                                "kind": "scoped_identifier_verification",
                                "identifier_key": "resourceID",
                                "identifier_value": "local-device",
                                "status": (
                                    "multiple_scoped_entities_observed"
                                    if entity_count >= 2
                                    else "uniqueness_unverified_with_sibling_scope_fanout"
                                ),
                                "entity_count_observed": entity_count,
                                "entities": entities,
                                "sibling_entity_count_observed": 5,
                                "sibling_entities": [
                                    {
                                        "entity": "vendor.example/device-run-3083",
                                        "scope": "vendor.example/",
                                        "occurrence_count": 3,
                                        "references": ["evidence.log:10", "evidence.log:40"],
                                    },
                                    {
                                        "entity": "vendor.example/device-run-5477",
                                        "scope": "vendor.example/",
                                        "occurrence_count": 2,
                                        "references": ["evidence.log:22"],
                                    },
                                ],
                            }
                        ],
                    }
                ]
            },
        },
        "missing_evidence": [
            {
                "kind": "scope_uniqueness_unverified",
                "detail": "Identifier uniqueness is not established by the observed source.",
                "actionable": True,
                "source": "evidence.log",
                "identifier_key": "resourceID",
                "identifier_value": "local-device",
                "recommended_action": {
                    "operation": "search",
                    "query": "local-device",
                },
            }
        ],
    }
    return RetrievalResult(
        operation="search",
        status="ok",
        canonical_result=canonical,
        progress=EvidenceProgressTracker().snapshot(),
        new_evidence=(),
        repeated_evidence=0,
    )


def test_projection_keeps_evidence_facts_but_strips_other_planner_fields() -> None:
    projected = prioritize_actionable_retrieval(_result())
    canonical = projected.canonical_result
    data = canonical["data"]

    assert canonical["evidence"][0]["label"] == "observed"
    assert canonical["coverage"]["match_records"] == 2
    assert "next_queries" not in canonical
    assert "actionable_retrieval" not in data

    assert data["signal_hints"] == [{"line": 999, "label": "fatal"}]
    assert "materialize" in data["signal_hint_note"].lower()

    constraint = data["correlation_constraints"][0]
    assert constraint["source_uniqueness"] == "unverified"
    assert constraint["identifier_only_correlation_safe"] is False
    assert constraint["minimum_safe_correlation_key"] == [
        "scoped_entity",
        "resourceID",
    ]
    assert constraint["observed_sibling_entities"] == [
        {
            "entity": "vendor.example/device-run-3083",
            "scope": "vendor.example/",
            "occurrence_count": 3,
            "references": ["evidence.log:10", "evidence.log:40"],
        },
        {
            "entity": "vendor.example/device-run-5477",
            "scope": "vendor.example/",
            "occurrence_count": 2,
            "references": ["evidence.log:22"],
        },
    ]
    assert constraint["observed_sibling_entities_truncated"] == 3
    assert "does not prove" in constraint["sibling_entity_note"].lower()

    gap = canonical["missing_evidence"][0]
    assert gap["kind"] == "scope_uniqueness_unverified"
    assert gap["identifier_value"] == "local-device"
    assert "actionable" not in gap
    assert "recommended_action" not in gap


def test_direct_multi_entity_observation_is_reported_as_identity_fact_not_action() -> None:
    projected = prioritize_actionable_retrieval(_result(entity_count=2))
    canonical = projected.canonical_result
    constraint = canonical["data"]["correlation_constraints"][0]

    assert constraint["source_uniqueness"] == "disproved"
    assert constraint["identifier_only_correlation_safe"] is False
    assert {row["entity"] for row in constraint["observed_sibling_entities"]} == {
        "vendor.example/device-run-3083",
        "vendor.example/device-run-5477",
    }
    assert "actionable_retrieval" not in canonical["data"]
    assert "next_queries" not in canonical
