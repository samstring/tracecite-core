from __future__ import annotations

from tracecite.runtime.agent_api import RetrievalResult
from tracecite.runtime.evidence_progress import EvidenceProgressTracker
from tracecite.runtime.retrieval_guidance import prioritize_actionable_retrieval


def _result(canonical: dict) -> RetrievalResult:
    return RetrievalResult(
        operation="search",
        status=str(canonical.get("status") or "ok"),
        canonical_result=canonical,
        progress=EvidenceProgressTracker().snapshot(),
        new_evidence=(),
        repeated_evidence=(),
        stop_reason=None,
    )


def _identity_case(
    query: str,
    *,
    status: str = "uniqueness_unverified_with_sibling_scope_fanout",
) -> dict:
    return {
        "operation": "search",
        "status": "ok",
        "data": {
            "query": query,
            "evidence_integrity": {
                "scoped_identity": [
                    {
                        "source": "evidence.log",
                        "identity_verification": [
                            {
                                "kind": "scoped_identifier_verification",
                                "identifier_key": "resourceID",
                                "identifier_value": "local-device",
                                "status": status,
                                "source": "evidence.log",
                                "entity_count_observed": 1,
                                "entities": [
                                    {
                                        "entity": "vendor.example/device-run-3083",
                                        "scope": "vendor.example/",
                                    }
                                ],
                                "sibling_entities": [
                                    {
                                        "entity": "vendor.example/device-run-1097",
                                        "scope": "vendor.example/",
                                    },
                                    {
                                        "entity": "vendor.example/device-run-5477",
                                        "scope": "vendor.example/",
                                    },
                                ],
                                "sibling_entity_count_observed": 5,
                            }
                        ],
                    }
                ]
            },
        },
        "missing_evidence": [
            {
                "kind": "scope_uniqueness_unverified",
                "actionable": True,
                "source": "evidence.log",
                "identifier_key": "resourceID",
                "identifier_value": "local-device",
                "recommended_action": {
                    "operation": "search",
                    "query": "local-device",
                    "purpose": "verify_identifier_uniqueness_across_scopes",
                },
            }
        ],
        "next_queries": ["local-device", "generic"],
    }


def test_actionable_gap_becomes_explicit_prioritized_retrieval_action() -> None:
    result = prioritize_actionable_retrieval(
        _result(
            {
                "operation": "search",
                "status": "ok",
                "data": {},
                "missing_evidence": [
                    {
                        "kind": "scope_uniqueness_unverified",
                        "actionable": True,
                        "source": "evidence.log",
                        "recommended_action": {
                            "operation": "search",
                            "query": "local-device",
                            "purpose": "verify_identifier_uniqueness_across_scopes",
                        },
                    }
                ],
                "next_queries": ["generic", "local-device", "other"],
            }
        )
    )
    action = result.canonical_result["data"]["actionable_retrieval"]
    assert action == {
        "operation": "search",
        "query": "local-device",
        "purpose": "verify_identifier_uniqueness_across_scopes",
        "gap_kind": "scope_uniqueness_unverified",
        "source": "evidence.log",
    }
    assert result.canonical_result["next_queries"] == [
        "local-device",
        "generic",
        "other",
    ]


def test_guidance_never_invents_action_for_non_actionable_or_actionless_gap() -> None:
    canonical = {
        "operation": "search",
        "status": "ok",
        "data": {},
        "missing_evidence": [
            {"kind": "query_coverage", "actionable": False},
            {"kind": "identity_unknown", "actionable": True},
        ],
        "next_queries": ["existing"],
    }
    original = _result(canonical)
    guided = prioritize_actionable_retrieval(original)
    assert guided is original


def test_scoped_local_identifier_contract_never_promotes_negative_evidence_to_uniqueness() -> None:
    guided = prioritize_actionable_retrieval(_result(_identity_case("local-device")))
    contract = guided.canonical_result["data"]["correlation_constraints"][0]
    assert contract["source_uniqueness"] == "unverified"
    assert contract["identifier_only_correlation_safe"] is False
    assert contract["required_correlation_components"] == ["scoped_entity", "resourceID"]
    assert contract["unsafe_correlation_key"] == ["resourceID"]
    assert contract["minimum_safe_correlation_key"] == ["scoped_entity", "resourceID"]
    assert contract["scope_fanout_observed"] is True
    assert "does not prove" in contract["negative_evidence_note"]


def test_identifier_search_advances_to_observed_scoped_entity_instead_of_repeating() -> None:
    guided = prioritize_actionable_retrieval(_result(_identity_case("local-device")))
    action = guided.canonical_result["data"]["actionable_retrieval"]
    assert action["query"] == "vendor.example/device-run-3083"
    assert action["purpose"] == "trace_scoped_entity_references"


def test_scoped_entity_search_advances_to_observed_sibling_family() -> None:
    guided = prioritize_actionable_retrieval(
        _result(_identity_case("vendor.example/device-run-3083"))
    )
    action = guided.canonical_result["data"]["actionable_retrieval"]
    assert action["query"] == "vendor.example/device-run-"
    assert action["purpose"] == "trace_sibling_entity_family_references"
    assert guided.canonical_result["next_queries"][0] == "vendor.example/device-run-"
    assert action["query"] not in {
        "local-device",
        "vendor.example/device-run-3083",
    }


def test_scoped_family_search_finishes_without_dropping_scope() -> None:
    guided = prioritize_actionable_retrieval(
        _result(_identity_case("vendor.example/device-run-"))
    )
    gap = guided.canonical_result["missing_evidence"][0]
    assert gap["actionable"] is False
    assert "actionable_retrieval" not in guided.canonical_result["data"]
    constraint = guided.canonical_result["data"]["correlation_constraints"][0]
    assert constraint["identifier_only_correlation_safe"] is False
    assert "remains unsafe" in gap["detail"]
    assert "device-run-" not in guided.canonical_result["next_queries"][:1]


def test_direct_multi_entity_observation_closes_uniqueness_gap_without_causal_claim() -> None:
    canonical = _identity_case(
        "local-device", status="multiple_scoped_entities_observed"
    )
    verification = canonical["data"]["evidence_integrity"]["scoped_identity"][0][
        "identity_verification"
    ][0]
    verification["entity_count_observed"] = 2
    verification["entities"].append(
        {"entity": "vendor.example/device-run-5477"}
    )
    guided = prioritize_actionable_retrieval(_result(canonical))
    assert guided.canonical_result["missing_evidence"][0]["actionable"] is False
    assert "actionable_retrieval" not in guided.canonical_result["data"]
    assert (
        guided.canonical_result["data"]["correlation_constraints"][0][
            "source_uniqueness"
        ]
        == "disproved"
    )
