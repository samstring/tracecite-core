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
