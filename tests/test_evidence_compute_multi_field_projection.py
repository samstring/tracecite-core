from __future__ import annotations

import json
from pathlib import Path

from tracecite.runtime import (
    EvidenceAnalysisSpec,
    EvidenceComputeRequest,
    EvidenceShellPolicy,
    EvidenceShellRequest,
    run_evidence_compute,
    run_evidence_shell,
)


def _policy() -> EvidenceShellPolicy:
    return EvidenceShellPolicy(
        max_evidence_tokens=10_000,
        max_evidence_bytes=100_000,
        source_mode="static",
    )


def test_canonical_project_supports_multiple_fields(tmp_path: Path) -> None:
    source = tmp_path / "rows.jsonl"
    rows = [
        {"rank": 3, "service": "edge", "operation": "c"},
        {"rank": 1, "service": "route", "operation": "a"},
        {"rank": 2, "service": "route", "operation": "b"},
    ]
    source.write_text(
        "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )

    result = run_evidence_shell(
        EvidenceShellRequest(
            source=source,
            program="sort rank asc numeric | head 2 | project rank service operation",
        ),
        policy=_policy(),
    )

    assert result["status"] == "ok"
    aggregate = result["data"]["aggregate"]
    assert aggregate["fields"] == ["rank", "service", "operation"]
    assert [row["values"] for row in aggregate["rows"]] == [
        {"rank": 1, "service": "route", "operation": "a"},
        {"rank": 2, "service": "route", "operation": "b"},
    ]


def test_compute_multi_field_topk_matches_canonical_without_remainder(tmp_path: Path) -> None:
    source = tmp_path / "rows.jsonl"
    rows = [
        {"rank": 3, "service": "edge", "operation": "c"},
        {"rank": 1, "service": "route", "operation": "a"},
        {"rank": 2, "service": "route", "operation": "b"},
    ]
    source.write_text(
        "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )
    program = "sort rank asc numeric | head 2 | project rank service operation"

    batch = run_evidence_compute(
        EvidenceComputeRequest(
            source=source,
            analyses=(
                EvidenceAnalysisSpec("rows", "count"),
                EvidenceAnalysisSpec("first", program),
            ),
        ),
        policy=_policy(),
    )
    canonical = run_evidence_shell(
        EvidenceShellRequest(source=source, program=program),
        policy=_policy(),
    )

    assert batch["status"] == "ok"
    assert batch["data"]["execution_engine"] == "jsonl_shared_scan_batch"
    assert batch["data"]["shared_scan_analyses"] == 2
    assert batch["data"]["canonical_remainder_analyses"] == 0
    output = next(item for item in batch["data"]["outputs"] if item["name"] == "first")
    assert output["execution_engine"] == "jsonl_shared_scan_topn_project"
    assert output["aggregate"] == canonical["data"]["aggregate"]
