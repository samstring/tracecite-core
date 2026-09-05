from __future__ import annotations

import json

import tracecite.runtime.evidence_compute as legacy
from tracecite.runtime import (
    EvidenceAnalysisSpec,
    EvidenceComputeRequest,
    EvidenceShellPolicy,
    run_evidence_compute,
)
from tracecite_core.segmenter import JsonLineSegmenter


def _policy() -> EvidenceShellPolicy:
    return EvidenceShellPolicy(
        max_evidence_tokens=40_000,
        max_evidence_bytes=400_000,
        source_mode="static",
    )


def test_public_compute_uses_fixed_capacity_topk_for_mixed_jsonl_batch(tmp_path, monkeypatch) -> None:
    path = tmp_path / "events.jsonl"
    rows = [
        {"service": "a" if index % 2 == 0 else "b", "duration": index, "timestamp": index}
        for index in range(10_000)
    ]
    path.write_text(
        "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )

    def fail_record_scan(*args, **kwargs):
        raise AssertionError("public JSONL compute must not construct canonical Records")

    def fail_legacy_trim(*args, **kwargs):
        raise AssertionError("public JSONL compute must not use repeated nsmallest/nlargest trimming")

    monkeypatch.setattr(JsonLineSegmenter, "segment_file", fail_record_scan)
    monkeypatch.setattr(legacy, "_trim_topn", fail_legacy_trim)

    result = run_evidence_compute(
        EvidenceComputeRequest(
            source=path,
            analyses=(
                EvidenceAnalysisSpec(name="count", program="count"),
                EvidenceAnalysisSpec(
                    name="max",
                    program="sort duration desc numeric | head 7 | project duration service",
                ),
                EvidenceAnalysisSpec(
                    name="min",
                    program="sort duration asc numeric | head 7 | project duration service",
                ),
            ),
        ),
        policy=_policy(),
    )

    assert result["status"] == "ok"
    data = result["data"]
    assert data["execution_engine"] == "jsonl_shared_scan_batch"
    assert data["canonical_remainder_analyses"] == 0
    assert data["physical_plan"] == {
        "source_scan": "jsonl_raw_lines",
        "json_decode": "shared_once_per_candidate_line",
        "predicate_evaluation": "memoized_once_per_unique_stage_per_line",
        "topk_projection": "post_selection",
        "semantic_enrichment": "lazy_from_decoded_json",
    }
    by_name = {item["name"]: item for item in data["outputs"]}
    assert by_name["count"]["aggregate"]["count"] == 10_000
    assert [row["values"]["duration"] for row in by_name["max"]["aggregate"]["rows"]] == [
        9_999, 9_998, 9_997, 9_996, 9_995, 9_994, 9_993
    ]
    assert [row["values"]["duration"] for row in by_name["min"]["aggregate"]["rows"]] == [
        0, 1, 2, 3, 4, 5, 6
    ]


def test_public_compute_memoizes_shared_predicates_for_aggregate_only_batch(tmp_path, monkeypatch) -> None:
    path = tmp_path / "events.jsonl"
    rows = [
        {"service": "a" if index % 2 == 0 else "b", "kind": str(index % 5)}
        for index in range(1000)
    ]
    path.write_text(
        "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )

    def fail_legacy_partition(*args, **kwargs):
        raise AssertionError("compatible aggregate-only JSONL batches must use the shared physical executor")

    monkeypatch.setattr(legacy, "_try_partitioned_jsonl", fail_legacy_partition)

    import tracecite.runtime.jsonl_physical as physical

    real_matches = physical._matches
    shared_predicate_evaluations = 0

    def counted_matches(obj, raw, stage):
        nonlocal shared_predicate_evaluations
        if stage.command == "where" and tuple(stage.args) == ("service", "==", "a"):
            shared_predicate_evaluations += 1
        return real_matches(obj, raw, stage)

    monkeypatch.setattr(physical, "_matches", counted_matches)

    result = run_evidence_compute(
        EvidenceComputeRequest(
            source=path,
            analyses=(
                EvidenceAnalysisSpec(name="count", program="where service == a | count"),
                EvidenceAnalysisSpec(name="group", program="where service == a | group kind"),
                EvidenceAnalysisSpec(name="distinct", program="where service == a | distinct kind"),
            ),
        ),
        policy=_policy(),
    )

    assert result["status"] == "ok"
    assert result["data"]["physical_plan"]["topk_projection"] == "none"
    by_name = {item["name"]: item for item in result["data"]["outputs"]}
    assert by_name["count"]["aggregate"]["count"] == 500
    assert by_name["group"]["aggregate"]["group_total"] == 5
    assert by_name["distinct"]["aggregate"]["distinct_total"] == 5
    assert shared_predicate_evaluations == 1000


def test_unsupported_sibling_does_not_downgrade_supported_topk(tmp_path, monkeypatch) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text(
        "".join(
            json.dumps({"duration": index, "service": "svc"}, separators=(",", ":")) + "\n"
            for index in range(1000)
        ),
        encoding="utf-8",
    )

    def fail_legacy_trim(*args, **kwargs):
        raise AssertionError("supported Top-K sibling must retain fixed-capacity physical plan")

    monkeypatch.setattr(legacy, "_trim_topn", fail_legacy_trim)

    result = run_evidence_compute(
        EvidenceComputeRequest(
            source=path,
            analyses=(
                EvidenceAnalysisSpec(
                    name="top",
                    program="sort duration desc numeric | head 3 | project duration service",
                ),
                # Valid Analyze output, but not part of the shared sort+head+project
                # compiler. It should become only the canonical remainder.
                EvidenceAnalysisSpec(
                    name="first",
                    program="head 1 | project duration service",
                ),
            ),
        ),
        policy=_policy(),
    )

    assert result["status"] == "ok"
    data = result["data"]
    assert data["execution_engine"] == "jsonl_partitioned_batch"
    assert data["shared_scan_analyses"] == 1
    assert data["canonical_remainder_analyses"] == 1
    by_name = {item["name"]: item for item in data["outputs"]}
    assert by_name["top"]["execution_engine"] == "jsonl_shared_scan_topn_project"
    assert [row["values"]["duration"] for row in by_name["top"]["aggregate"]["rows"]] == [
        999,
        998,
        997,
    ]
    assert by_name["first"]["status"] == "ok"
    assert by_name["first"]["aggregate"]["rows"][0]["values"]["duration"] == 0
