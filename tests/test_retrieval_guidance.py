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
    assert result.canonical_result["next_queries"] == ["local-device", "generic", "other"]
    assert "root-cause recommendation" in result.canonical_result["data"]["actionable_retrieval_note"]


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
    assert "actionable_retrieval" not in original.canonical_result["data"]
    assert original.canonical_result["next_queries"] == ["existing"]


def test_scoped_local_identifier_contract_never_promotes_negative_evidence_to_uniqueness() -> None:
    canonical = {
        "operation": "search",
        "status": "ok",
        "data": {
            "query": "local-device",
            "evidence_integrity": {
                "scoped_identity": [
                    {
                        "source": "evidence.log",
                        "identity_verification": [
                            {
                                "kind": "scoped_identifier_verification",
                                "identifier_key": "resourceID",
                                "identifier_value": "local-device",
                                "status": "uniqueness_unverified_with_sibling_scope_fanout",
                                "source": "evidence.log",
                                "entity_count_observed": 1,
                                "entities": [
                                    {"entity": "vendor.example/device-a", "scope": "vendor.example/"}
                                ],
                                "sibling_entity_count_observed": 4,
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

    guided = prioritize_actionable_retrieval(_result(canonical))
    data = guided.canonical_result["data"]
    contract = data["correlation_constraints"][0]
    assert contract["kind"] == "scoped_local_identifier"
    assert contract["source_uniqueness"] == "unverified"
    assert contract["identifier_only_correlation_safe"] is False
    assert contract["required_correlation_components"] == ["scoped_entity", "resourceID"]
    assert "does not prove" in contract["negative_evidence_note"]

    verification = data["evidence_integrity"]["scoped_identity"][0]["identity_verification"][0]
    assert verification["identity_contract"] == contract


def test_identifier_search_advances_to_observed_scoped_entity_instead_of_repeating() -> None:
    canonical = {
        "operation": "search",
        "status": "ok",
        "data": {
            "query": "local-device",
            "evidence_integrity": {
                "scoped_identity": [
                    {
                        "source": "evidence.log",
                        "identity_verification": [
                            {
                                "kind": "scoped_identifier_verification",
                                "identifier_key": "resourceID",
                                "identifier_value": "local-device",
                                "status": "uniqueness_unverified_with_sibling_scope_fanout",
                                "source": "evidence.log",
                                "entity_count_observed": 1,
                                "entities": [
                                    {"entity": "vendor.example/device-a", "scope": "vendor.example/"}
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

    guided = prioritize_actionable_retrieval(_result(canonical))
    action = guided.canonical_result["data"]["actionable_retrieval"]
    assert action["query"] == "vendor.example/device-a"
    assert action["purpose"] == "trace_scoped_entity_references"
    assert guided.canonical_result["next_queries"][0] == "vendor.example/device-a"
    assert guided.canonical_result["missing_evidence"][0]["correlation_constraint"][
        "identifier_only_correlation_safe"
    ] is False


def test_direct_multi_entity_observation_closes_uniqueness_gap_without_causal_claim() -> None:
    canonical = {
        "operation": "search",
        "status": "ok",
        "data": {
            "query": "local-device",
            "evidence_integrity": {
                "scoped_identity": [
                    {
                        "source": "evidence.log",
                        "identity_verification": [
                            {
                                "kind": "scoped_identifier_verification",
                                "identifier_key": "resourceID",
                                "identifier_value": "local-device",
                                "status": "multiple_scoped_entities_observed",
                                "source": "evidence.log",
                                "entity_count_observed": 2,
                                "entities": [
                                    {"entity": "vendor.example/device-a"},
                                    {"entity": "vendor.example/device-b"},
                                ],
                                "sibling_entity_count_observed": 2,
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
                "recommended_action": {"operation": "search", "query": "local-device"},
            }
        ],
        "next_queries": ["local-device"],
    }

    guided = prioritize_actionable_retrieval(_result(canonical))
    assert guided.canonical_result["missing_evidence"][0]["actionable"] is False
    assert "actionable_retrieval" not in guided.canonical_result["data"]
    contract = guided.canonical_result["data"]["correlation_constraints"][0]
    assert contract["source_uniqueness"] == "disproved"
    assert contract["identifier_only_correlation_safe"] is False
    assert "root cause" in guided.canonical_result["data"]["correlation_constraints_note"]
