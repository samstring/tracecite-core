from __future__ import annotations

from pathlib import Path

from tracecite.evidence_investigation_benchmarking import run_investigation_benchmark


CASE = (
    Path(__file__).resolve().parents[1]
    / "benchmarks"
    / "evidence-intelligence"
    / "cases"
    / "mobile-payment-crash"
)


def test_multi_source_investigation_reduces_structural_agent_rounds() -> None:
    result = run_investigation_benchmark(CASE)
    assert result["status"] == "ok"
    assert result["coverage_complete"] is True
    assert result["required_recall"] == 1.0
    assert result["structural_agent_rounds_without_orchestrator"] >= 4
    assert result["structural_agent_calls_with_orchestrator"] == 1
    assert result["structural_loop_reduction"] >= 0.75
    assert result["package_estimated_tokens"] <= result["package_max_tokens"]
    assert result["citation_uris"]
