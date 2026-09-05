from __future__ import annotations

import hashlib
import json

from tracecite.runtime import (
    EvidenceAnalysisSpec,
    EvidenceComputeRequest,
    EvidenceShellPolicy,
    run_evidence_compute,
)


def test_oversized_distinct_values_use_recoverable_descriptors(tmp_path) -> None:
    source = tmp_path / "events.jsonl"
    values = ["ERROR stack\n" + "frame\n" * 180, "WARN stack\n" + "frame\n" * 180]
    source.write_text(
        "".join(json.dumps({"message": value}) + "\n" for value in values),
        encoding="utf-8",
    )

    result = run_evidence_compute(
        EvidenceComputeRequest(
            source=source,
            analyses=(
                EvidenceAnalysisSpec(
                    "messages",
                    "distinct message | sort value asc | head 2",
                ),
            ),
        ),
        policy=EvidenceShellPolicy(
            max_evidence_tokens=20_000,
            max_evidence_bytes=200_000,
            source_mode="static",
        ),
    )

    assert result["status"] == "ok"
    aggregate = result["data"]["outputs"][0]["aggregate"]
    assert aggregate["derived_value_representation"] == "compact_descriptor"
    descriptors = aggregate["values"]
    assert [item["length"] for item in descriptors] == [len(value) for value in values]
    assert [item["value_sha256"] for item in descriptors] == [
        hashlib.sha256(value.encode("utf-8")).hexdigest() for value in values
    ]
    assert all(
        item["evidence_ref"].startswith("evidence://sha256/")
        and item["evidence_ref"].endswith(f"#L{index}")
        for index, item in enumerate(descriptors, 1)
    )
    assert all(len(item["preview"]) == 240 for item in descriptors)
    assert len(json.dumps(result, ensure_ascii=False)) < 4_000


def test_short_distinct_values_keep_scalar_transport_shape(tmp_path) -> None:
    source = tmp_path / "events.jsonl"
    source.write_text(
        json.dumps({"message": "short"}) + "\n",
        encoding="utf-8",
    )

    result = run_evidence_compute(
        EvidenceComputeRequest(
            source=source,
            analyses=(EvidenceAnalysisSpec("messages", "distinct message"),),
        ),
        policy=EvidenceShellPolicy(source_mode="static"),
    )

    assert result["data"]["outputs"][0]["aggregate"]["values"] == ["short"]
    assert "derived_value_representation" not in result["data"]["outputs"][0]["aggregate"]
