from __future__ import annotations

from tracecite.runtime.schema import AgentResult


def test_retrieval_operations_cannot_claim_semantic_support() -> None:
    for operation in ("probe", "search", "survey", "probe_format", "sample", "expand"):
        result = AgentResult(operation=operation, status="ok", outcome="supported")
        assert result.outcome == "not_assessed"
        assert result.to_dict()["outcome"] == "not_assessed"


def test_retrieval_operations_cannot_claim_semantic_contradiction() -> None:
    for operation in ("search", "expand"):
        result = AgentResult(operation=operation, status="ok", outcome="contradicted")
        assert result.outcome == "not_assessed"


def test_assertion_bearing_scenario_may_keep_decisive_outcome() -> None:
    result = AgentResult(operation="run", status="ok", outcome="supported")
    assert result.outcome == "supported"


def test_integrity_verification_may_keep_decisive_outcome() -> None:
    result = AgentResult(operation="verify", status="ok", outcome="supported")
    assert result.outcome == "supported"
