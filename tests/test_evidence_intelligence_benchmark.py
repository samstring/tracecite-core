from __future__ import annotations

from tracecite.evidence_benchmarking import run_component_benchmark


def test_component_benchmark_keeps_required_cross_source_evidence_with_large_reduction() -> None:
    result = run_component_benchmark(max_tokens=1200)

    assert result["pass"] is True
    assert result["quality"]["required_recall"] == 1.0
    assert result["context_cost"]["token_reduction_ratio"] > 0.8
    assert result["context_cost"]["package_evidence"] < result["context_cost"]["canonical_evidence"]
