from __future__ import annotations

import json

import tracecite.runtime.evidence_compute as legacy
from tracecite.runtime import (
    EvidenceAnalysisSpec,
    EvidenceComputeRequest,
    EvidenceShellPolicy,
    EvidenceShellRequest,
    run_evidence_compute,
    run_evidence_shell,
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


def test_group_and_distinct_post_topk_use_bounded_shared_scan(tmp_path, monkeypatch) -> None:
    path = tmp_path / "events.jsonl"
    rows = (
        [{"bucket": "hot", "value": "z"}] * 8
        + [{"bucket": "warm", "value": "a"}] * 5
        + [{"bucket": "cool", "value": "m"}] * 3
        + [
            {"bucket": f"tail-{index:04d}", "value": f"v-{index:04d}"}
            for index in range(2_000)
        ]
    )
    path.write_text(
        "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )

    import tracecite.runtime.evidence_compute_jsonl_physical as physical

    real_topk = physical.FixedCapacityTopK
    heaps = []

    class TrackingTopK(real_topk):
        def __init__(self, limit, *, descending):
            super().__init__(limit, descending=descending)
            heaps.append(self)

    monkeypatch.setattr(physical, "FixedCapacityTopK", TrackingTopK)

    real_finalize = legacy._finalize_aggregate

    def fail_unbounded_aggregate_finalize(item, *, policy):
        if item.aggregate_stage.command in {"group", "distinct"}:
            raise AssertionError("post-aggregate Top-K must not use full legacy sorting")
        return real_finalize(item, policy=policy)

    monkeypatch.setattr(legacy, "_finalize_aggregate", fail_unbounded_aggregate_finalize)

    result = run_evidence_compute(
        EvidenceComputeRequest(
            source=path,
            analyses=(
                EvidenceAnalysisSpec(name="count", program="count"),
                EvidenceAnalysisSpec(
                    name="groups",
                    program="group bucket | sort count desc | head 3",
                ),
                EvidenceAnalysisSpec(
                    name="values",
                    program="distinct value | sort value asc | head 4",
                ),
            ),
        ),
        policy=_policy(),
    )

    assert result["status"] == "ok"
    data = result["data"]
    assert data["execution_engine"] == "jsonl_shared_scan_batch"
    assert data["canonical_remainder_analyses"] == 0
    assert data["physical_plan"]["aggregate_topk"] == "fixed_capacity_heap"
    assert data["physical_plan"]["topk_projection"] == "none"
    assert [heap.limit for heap in heaps] == [3, 4]
    assert all(heap.retained <= heap.limit for heap in heaps)

    by_name = {item["name"]: item for item in data["outputs"]}
    assert by_name["count"]["aggregate"]["count"] == len(rows)
    assert by_name["groups"]["aggregate"]["groups"] == [
        {"key": "hot", "count": 8},
        {"key": "warm", "count": 5},
        {"key": "cool", "count": 3},
    ]
    assert by_name["groups"]["aggregate"]["group_total"] == 2_003
    assert by_name["values"]["aggregate"]["values"] == [
        "a",
        "m",
        "v-0000",
        "v-0001",
    ]
    assert by_name["values"]["aggregate"]["distinct_total"] == 2_003


def test_aggregate_post_topk_preserves_missing_ties_and_sort_fields(tmp_path) -> None:
    path = tmp_path / "events.jsonl"
    rows = [
        {"bucket": "z", "number": "10"},
        {"bucket": "a", "number": "2"},
        {"bucket": "y", "number": "1"},
        {"bucket": "b", "number": "1.0"},
        {"bucket": "z", "number": "2"},
        {"bucket": "a", "number": "10"},
        {"bucket": "y", "number": "1"},
        {"bucket": "b"},
        {"bucket": "c"},
        {},
        {"number": "1"},
    ]
    path.write_text(
        "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )

    programs = (
        "group bucket | sort count desc | head 3",
        "group bucket | sort count asc | head 3",
        "group bucket | sort key asc | head 3",
        "group bucket | sort key desc | head 3",
        "group number | sort key asc numeric | head 4",
        "distinct bucket | sort value asc | head 3",
        "distinct bucket | sort value desc | head 3",
        "distinct number | sort value asc numeric | head 4",
    )
    for index, program in enumerate(programs):
        name = f"analysis-{index}"
        batch = run_evidence_compute(
            EvidenceComputeRequest(
                source=path,
                analyses=(EvidenceAnalysisSpec(name=name, program=program),),
            ),
            policy=_policy(),
        )
        canonical = run_evidence_shell(
            EvidenceShellRequest(source=path, program=program),
            policy=_policy(),
        )

        assert batch["status"] == "ok"
        assert batch["data"]["canonical_remainder_analyses"] == 0
        assert batch["data"]["physical_plan"]["aggregate_topk"] == "fixed_capacity_heap"
        output = batch["data"]["outputs"][0]
        assert output["aggregate"] == canonical["data"]["aggregate"]
        assert output["coverage"]["match_records"] == canonical["coverage"]["match_records"]
