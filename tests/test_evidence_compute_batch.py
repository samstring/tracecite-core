from __future__ import annotations

import json

from tracecite.runtime import (
    EvidenceAnalysisSpec,
    EvidenceComputeRequest,
    EvidenceShellPolicy,
    EvidenceShellRequest,
    RetrievalSessionStore,
    run_evidence_compute,
    run_evidence_shell,
)


def _jsonl(tmp_path, rows) -> str:
    path = tmp_path / "compute.jsonl"
    path.write_text(
        "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )
    return str(path)


def _policy(**overrides) -> EvidenceShellPolicy:
    values = {
        "max_evidence_tokens": 10_000,
        "max_evidence_bytes": 100_000,
        "source_mode": "static",
    }
    values.update(overrides)
    return EvidenceShellPolicy(**values)


def _aggregate(result, name):
    outputs = result["data"]["outputs"]
    return next(item["aggregate"] for item in outputs if item["name"] == name)


def _output(result, name):
    return next(item for item in result["data"]["outputs"] if item["name"] == name)


def test_jsonl_batch_matches_independent_canonical_aggregates(tmp_path) -> None:
    source = _jsonl(
        tmp_path,
        [
            {"service": "route", "status": 200, "operation": "get"},
            {"service": "route", "status": 503, "operation": "get"},
            {"service": "route", "status": 500, "operation": "update"},
            {"service": "order", "status": 503, "operation": "create"},
        ],
    )
    specs = (
        EvidenceAnalysisSpec("route_count", "where service == route | count"),
        EvidenceAnalysisSpec(
            "failed_services",
            "where status >= 500 | group service | sort count desc | head 2",
        ),
        EvidenceAnalysisSpec(
            "operations",
            "distinct operation | sort value asc | head 3",
        ),
    )

    result = run_evidence_compute(
        EvidenceComputeRequest(source=source, analyses=specs),
        policy=_policy(),
    )

    assert result["status"] == "ok"
    assert result["data"]["execution_engine"] == "jsonl_shared_scan_batch"
    assert result["data"]["analysis_count"] == 3

    for spec in specs:
        independent = run_evidence_shell(
            EvidenceShellRequest(source=source, program=spec.program),
            policy=_policy(),
        )
        assert independent["status"] == "ok"
        assert _aggregate(result, spec.name) == independent["data"]["aggregate"]


def test_batch_decodes_each_json_line_once_for_multiple_field_analyses(tmp_path, monkeypatch) -> None:
    source = _jsonl(
        tmp_path,
        [{"service": "route", "status": 500 if i % 2 else 200, "n": i} for i in range(40)],
    )

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
                EvidenceAnalysisSpec("numbers", "distinct n | head 5"),
            ),
        ),
        policy=_policy(),
    )

    assert result["status"] == "ok"
    assert calls == 40


def test_batch_shares_generic_bounded_min_max_projection_with_aggregates(tmp_path) -> None:
    source = _jsonl(
        tmp_path,
        [
            {"service": "edge", "startTimeMillis": 3000},
            {"service": "route", "startTimeMillis": 1000},
            {"service": "route", "startTimeMillis": 2000},
        ],
    )

    result = run_evidence_compute(
        EvidenceComputeRequest(
            source=source,
            analyses=(
                EvidenceAnalysisSpec("rows", "count"),
                EvidenceAnalysisSpec(
                    "first",
                    "sort startTimeMillis asc numeric | head 1 | project startTimeMillis",
                ),
                EvidenceAnalysisSpec(
                    "last",
                    "sort startTimeMillis desc numeric | head 1 | project startTimeMillis",
                ),
            ),
        ),
        policy=_policy(),
    )

    assert result["status"] == "ok"
    assert result["data"]["execution_engine"] == "jsonl_shared_scan_batch"
    assert result["data"]["shared_scan_analyses"] == 3
    assert result["data"]["canonical_remainder_analyses"] == 0
    assert _aggregate(result, "rows")["count"] == 3
    assert _aggregate(result, "first")["rows"][0]["value"] == 1000
    assert _aggregate(result, "last")["rows"][0]["value"] == 3000
    assert _output(result, "first")["execution_engine"] == "jsonl_shared_scan_topn_project"


def test_unsupported_sibling_does_not_poison_shared_scan_batch(tmp_path) -> None:
    source = _jsonl(
        tmp_path,
        [
            {"service": "route", "n": 3},
            {"service": "auth", "n": 1},
            {"service": "route", "n": 2},
        ],
    )

    result = run_evidence_compute(
        EvidenceComputeRequest(
            source=source,
            analyses=(
                EvidenceAnalysisSpec("services", "group service"),
                # Sorting before a scalar count is mechanically valid but is
                # intentionally outside the shared-scan compiler. It exercises
                # partitioning without relying on any domain-specific pattern.
                EvidenceAnalysisSpec("sorted_count", "sort n asc numeric | count"),
            ),
        ),
        policy=_policy(),
    )

    assert result["status"] == "ok"
    assert result["data"]["execution_engine"] == "jsonl_partitioned_batch"
    assert result["data"]["shared_scan_analyses"] == 1
    assert result["data"]["canonical_remainder_analyses"] == 1
    assert _aggregate(result, "services")["groups"][0] == {"key": "route", "count": 2}
    assert _aggregate(result, "sorted_count")["count"] == 3
    assert _output(result, "services")["execution_engine"] == "jsonl_shared_scan_aggregate"


def test_compute_absolute_time_scope_is_explicit_and_shared(tmp_path) -> None:
    source = _jsonl(
        tmp_path,
        [
            {"timestamp": "2026-09-05T10:00:00Z", "service": "edge", "status": 200},
            {"timestamp": "2026-09-05T10:05:00Z", "service": "route", "status": 503},
            {"timestamp": "2026-09-05T10:10:00Z", "service": "route", "status": 500},
            {"timestamp": "2026-09-05T10:20:00Z", "service": "auth", "status": 503},
        ],
    )

    result = run_evidence_compute(
        EvidenceComputeRequest(
            source=source,
            since="2026-09-05T10:04:00Z",
            until="2026-09-05T10:15:00Z",
            analyses=(
                EvidenceAnalysisSpec("failures", "where status >= 500 | count"),
                EvidenceAnalysisSpec("services", "where status >= 500 | group service"),
            ),
        ),
        policy=_policy(),
    )

    assert result["status"] == "ok"
    assert result["data"]["execution_engine"] == "jsonl_shared_scan_batch"
    assert result["data"]["time_scope"] == {
        "last": None,
        "since": "2026-09-05T10:04:00Z",
        "until": "2026-09-05T10:15:00Z",
    }
    assert _aggregate(result, "failures")["count"] == 2
    assert _aggregate(result, "services")["groups"] == [{"key": "route", "count": 2}]


def test_batch_records_one_session_operation_and_reuses_bound_source_version(tmp_path) -> None:
    source = _jsonl(
        tmp_path,
        [
            {"service": "route", "status": 200},
            {"service": "route", "status": 503},
        ],
    )
    session = RetrievalSessionStore(tmp_path / "state", "compute-session")
    request = EvidenceComputeRequest(
        source=source,
        segmenter="jsonline",
        analyses=(EvidenceAnalysisSpec("services", "group service"),),
    )
    mutable_policy = _policy(source_mode="mutable")

    first = run_evidence_compute(request, policy=mutable_policy, session=session)
    first_state = session.load()
    first_version = first["data"]["source_version"]

    assert first_state.revision == 1
    assert first_state.operation_counts["evidence_compute"] == 1
    assert first_state.recent_operations[-1].source_version == first_version
    assert _aggregate(first, "services")["groups"] == [{"key": "route", "count": 2}]

    with open(source, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"service": "order", "status": 500}, separators=(",", ":")) + "\n")

    same_session = run_evidence_compute(request, policy=mutable_policy, session=session)
    second_state = session.load()

    assert same_session["data"]["source_version"] == first_version
    assert _aggregate(same_session, "services")["groups"] == [{"key": "route", "count": 2}]
    assert second_state.revision == 2
    assert second_state.operation_counts["evidence_compute"] == 2
    assert second_state.exact_duplicate_requests == 1

    independent = RetrievalSessionStore(tmp_path / "state", "compute-session-2")
    new_session = run_evidence_compute(request, policy=mutable_policy, session=independent)
    assert new_session["data"]["source_version"] != first_version
    assert _aggregate(new_session, "services")["groups"] == [
        {"key": "route", "count": 2},
        {"key": "order", "count": 1},
    ]


def test_non_jsonl_batch_keeps_one_agent_boundary_via_canonical_fallback(tmp_path) -> None:
    source = tmp_path / "runtime.log"
    source.write_text("ok\nERROR one\nERROR two\n", encoding="utf-8")

    result = run_evidence_compute(
        EvidenceComputeRequest(
            source=str(source),
            analyses=(
                EvidenceAnalysisSpec("errors", "search ERROR | count"),
                EvidenceAnalysisSpec("all", "all | count"),
            ),
            segmenter="rawtext",
        ),
        policy=_policy(),
    )

    assert result["status"] == "ok"
    assert result["data"]["execution_engine"] == "canonical_batch_fallback"
    assert _aggregate(result, "errors")["count"] == 2
    assert _aggregate(result, "all")["count"] == 3


def test_batch_rejects_raw_evidence_program_as_analysis_output(tmp_path) -> None:
    source = tmp_path / "runtime.log"
    source.write_text("ERROR one\nERROR two\n", encoding="utf-8")

    result = run_evidence_compute(
        EvidenceComputeRequest(
            source=str(source),
            analyses=(EvidenceAnalysisSpec("raw", "search ERROR | head 1"),),
            segmenter="rawtext",
        ),
        policy=_policy(),
    )

    assert result["status"] == "partial"
    output = result["data"]["outputs"][0]
    assert output["status"] == "error"
    assert output["error_code"] == "analysis_requires_bounded_aggregate"
    assert "evidence" not in output


def test_batch_transport_gate_does_not_return_large_partial_outputs(tmp_path) -> None:
    source = _jsonl(tmp_path, [{"value": f"value-{i:04d}"} for i in range(200)])

    result = run_evidence_compute(
        EvidenceComputeRequest(
            source=source,
            analyses=(EvidenceAnalysisSpec("values", "distinct value"),),
        ),
        policy=_policy(max_evidence_tokens=20, max_evidence_bytes=128),
    )

    assert result["status"] == "too_broad"
    assert result["data"]["reason"] == "BATCH_OUTPUT_BUDGET_EXCEEDED"
    assert "outputs" not in result["data"]
