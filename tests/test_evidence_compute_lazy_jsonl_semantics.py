from __future__ import annotations

import json

from tracecite.runtime import (
    EvidenceAnalysisSpec,
    EvidenceComputeRequest,
    EvidenceShellPolicy,
    run_evidence_compute,
)
from tracecite_core.segmenter import JsonLineSegmenter


def _policy() -> EvidenceShellPolicy:
    return EvidenceShellPolicy(
        max_evidence_tokens=10_000,
        max_evidence_bytes=100_000,
        source_mode="static",
    )


def _source(tmp_path, rows) -> str:
    path = tmp_path / "events.jsonl"
    path.write_text(
        "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )
    return str(path)


def _output(result, name):
    return next(item for item in result["data"]["outputs"] if item["name"] == name)


def test_semantic_sibling_does_not_force_segment_file_record_scan(tmp_path, monkeypatch) -> None:
    source = _source(
        tmp_path,
        [
            {"timestamp": "2026-09-05T10:00:00Z", "service": "edge"},
            {"timestamp": "2026-09-05T10:05:00Z", "service": "route"},
            {"timestamp": "2026-09-05T10:10:00Z", "service": "route"},
        ],
    )

    def fail_segment_file(*args, **kwargs):
        raise AssertionError("shared JSONL compute must not construct a whole Record scan")

    monkeypatch.setattr(JsonLineSegmenter, "segment_file", fail_segment_file)

    result = run_evidence_compute(
        EvidenceComputeRequest(
            source=source,
            analyses=(
                EvidenceAnalysisSpec("services", "group service"),
                EvidenceAnalysisSpec(
                    "first_time",
                    "sort timestamp asc | head 1 | project timestamp service",
                ),
            ),
        ),
        policy=_policy(),
    )

    assert result["status"] == "ok"
    assert result["data"]["execution_engine"] == "jsonl_shared_scan_batch"
    assert result["data"]["canonical_remainder_analyses"] == 0
    assert result["data"]["physical_plan"] == {
        "source_scan": "jsonl_raw_lines",
        "json_decode": "shared_once_per_candidate_line",
        "predicate_evaluation": "memoized_once_per_unique_stage_per_line",
        "topk_projection": "post_selection",
        "semantic_enrichment": "lazy_from_decoded_json",
    }
    assert _output(result, "first_time")["aggregate"]["rows"][0]["values"] == {
        "timestamp": "2026-09-05T10:00:00.000",
        "service": "edge",
    }


def test_semantic_and_normal_fields_share_one_json_decode_per_line(tmp_path, monkeypatch) -> None:
    rows = [
        {
            "timestamp": f"2026-09-05T10:{index:02d}:00Z",
            "service": "route" if index % 2 else "edge",
            "status": 500 if index % 3 == 0 else 200,
        }
        for index in range(20)
    ]
    source = _source(tmp_path, rows)

    import tracecite.runtime.evidence_compute as compute

    real_loads = compute.json.loads
    calls = 0

    def counted_loads(value):
        nonlocal calls
        calls += 1
        return real_loads(value)

    monkeypatch.setattr(compute.json, "loads", counted_loads)

    result = run_evidence_compute(
        EvidenceComputeRequest(
            source=source,
            segmenter="jsonline",
            analyses=(
                EvidenceAnalysisSpec("services", "group service"),
                EvidenceAnalysisSpec("failures", "where status >= 500 | count"),
                EvidenceAnalysisSpec(
                    "first_time",
                    "sort timestamp asc | head 1 | project timestamp service status",
                ),
            ),
        ),
        policy=_policy(),
    )

    assert result["status"] == "ok"
    assert calls == len(rows)


def test_absolute_time_scope_uses_shared_semantics_without_record_scan(tmp_path, monkeypatch) -> None:
    source = _source(
        tmp_path,
        [
            {"timestamp": "2026-09-05T10:00:00Z", "service": "edge"},
            {"timestamp": "2026-09-05T10:05:00Z", "service": "route"},
            {"service": "untimestamped"},
            {"timestamp": "2026-09-05T10:20:00Z", "service": "auth"},
        ],
    )

    def fail_segment_file(*args, **kwargs):
        raise AssertionError("absolute JSONL scope should reuse decoded semantic timestamp")

    monkeypatch.setattr(JsonLineSegmenter, "segment_file", fail_segment_file)

    result = run_evidence_compute(
        EvidenceComputeRequest(
            source=source,
            since="2026-09-05T10:04:00Z",
            until="2026-09-05T10:10:00Z",
            analyses=(EvidenceAnalysisSpec("services", "group service"),),
        ),
        policy=_policy(),
    )

    assert result["status"] == "ok"
    groups = _output(result, "services")["aggregate"]["groups"]
    # Preserve canonical time-scope semantics: records without a parseable
    # timestamp are retained rather than silently excluded.
    assert groups == [
        {"key": "route", "count": 1},
        {"key": "untimestamped", "count": 1},
    ]
