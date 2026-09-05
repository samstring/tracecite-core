from __future__ import annotations

import json

import tracecite.runtime.evidence_compute as legacy
from tracecite.runtime import (
    EvidenceAnalysisSpec,
    EvidenceComputeRequest,
    EvidenceShellPolicy,
    run_evidence_compute,
)


def _policy() -> EvidenceShellPolicy:
    return EvidenceShellPolicy(
        max_evidence_tokens=20_000,
        max_evidence_bytes=200_000,
        source_mode="static",
    )


def test_raw_selection_is_rejected_before_source_resolution(tmp_path) -> None:
    missing = tmp_path / "does-not-exist.jsonl"

    result = run_evidence_compute(
        EvidenceComputeRequest(
            source=missing,
            analyses=(
                EvidenceAnalysisSpec(
                    name="raw_top",
                    program="sort duration desc numeric | head 1",
                ),
            ),
        ),
        policy=_policy(),
    )

    assert result["status"] == "partial"
    assert result["data"]["execution_engine"] == "analysis_contract_preflight"
    assert result["data"]["contract_rejected_analyses"] == 1
    output = result["data"]["outputs"][0]
    assert output["status"] == "error"
    assert output["error_code"] == "analysis_requires_bounded_aggregate"
    assert output["execution_engine"] == "analysis_contract_preflight"


def test_invalid_raw_sibling_does_not_execute_shell_fallback(tmp_path, monkeypatch) -> None:
    source = tmp_path / "events.jsonl"
    source.write_text(
        "".join(
            json.dumps({"duration": index, "service": "svc"}) + "\n"
            for index in range(10)
        ),
        encoding="utf-8",
    )

    def fail_shell(*args, **kwargs):
        raise AssertionError("contract-rejected sibling must not execute Evidence Shell")

    monkeypatch.setattr(legacy, "run_evidence_shell", fail_shell)

    result = run_evidence_compute(
        EvidenceComputeRequest(
            source=source,
            analyses=(
                EvidenceAnalysisSpec(name="count", program="count"),
                EvidenceAnalysisSpec(
                    name="raw_top",
                    program="where service == svc | sort duration desc numeric | head 1",
                ),
            ),
        ),
        policy=_policy(),
    )

    assert result["status"] == "partial"
    assert result["data"]["contract_rejected_analyses"] == 1
    by_name = {item["name"]: item for item in result["data"]["outputs"]}
    assert by_name["count"]["status"] == "ok"
    assert by_name["count"]["aggregate"]["count"] == 10
    assert by_name["raw_top"]["status"] == "error"
    assert by_name["raw_top"]["error_code"] == "analysis_requires_bounded_aggregate"


def test_projected_topk_remains_valid_analyze_program(tmp_path) -> None:
    source = tmp_path / "events.jsonl"
    source.write_text(
        "".join(json.dumps({"duration": index}) + "\n" for index in range(5)),
        encoding="utf-8",
    )

    result = run_evidence_compute(
        EvidenceComputeRequest(
            source=source,
            analyses=(
                EvidenceAnalysisSpec(
                    name="top",
                    program="sort duration desc numeric | head 2 | project duration",
                ),
            ),
        ),
        policy=_policy(),
    )

    assert result["status"] == "ok"
    output = result["data"]["outputs"][0]
    assert output["status"] == "ok"
    assert [row["value"] for row in output["aggregate"]["rows"]] == [4, 3]
