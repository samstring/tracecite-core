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
    # The transport projection remains byte-for-byte compatible.  The stronger
    # invariant is above: the legacy repeated trim is forbidden and this mixed
    # batch must still complete through the public API.
    assert data["physical_plan"] == {
        "source_scan": "jsonl_raw_lines",
        "json_decode": "shared_once_per_candidate_line",
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