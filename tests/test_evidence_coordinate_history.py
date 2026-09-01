from __future__ import annotations

import hashlib
from pathlib import Path

from tracecite.runtime import EvidenceCoordinate, EvidenceRequest, QueryTarget, RangeTarget
from tracecite.runtime.evidence_coordinates import attach_seen_evidence_distances
from tracecite.runtime.retrieval_session import RetrievalSessionState, RetrievalSessionStore
from tracecite.runtime.session_retrieval import retrieve_with_session


def _store(tmp_path: Path) -> RetrievalSessionStore:
    return RetrievalSessionStore(
        tmp_path,
        "geometry",
        namespace="_retrieval_sessions",
        legacy_evidence_context=False,
    )


def _write_source(path: Path, line_count: int = 40) -> str:
    lines = [f"line-{index}" for index in range(1, line_count + 1)]
    lines[14] = "TARGET evidence-candidate"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_seen_coordinates_remain_distinct_when_coverage_ranges_merge(tmp_path: Path) -> None:
    source = tmp_path / "runtime.log"
    digest = _write_source(source)
    store = _store(tmp_path)

    retrieve_with_session(
        EvidenceRequest(RangeTarget(source, 10, expected_sha256=digest)),
        store,
    )
    retrieve_with_session(
        EvidenceRequest(RangeTarget(source, 11, expected_sha256=digest)),
        store,
    )

    state = store.load()
    covered = [
        ranges
        for source_key, ranges in state.covered_ranges.items()
        if source_key.endswith(f"@sha256:{digest}")
    ]
    assert covered == [((10, 11),)]
    assert [(item.start_line, item.end_line) for item in state.seen_evidence_coordinates] == [
        (10, 10),
        (11, 11),
    ]
    assert state.seen_evidence_coordinates[0].ref != state.seen_evidence_coordinates[1].ref


def test_query_reports_sparse_distance_to_materialized_evidence_refs(tmp_path: Path) -> None:
    source = tmp_path / "runtime.log"
    digest = _write_source(source)
    store = _store(tmp_path)

    retrieve_with_session(
        EvidenceRequest(RangeTarget(source, 10, expected_sha256=digest)),
        store,
    )
    retrieve_with_session(
        EvidenceRequest(RangeTarget(source, 11, expected_sha256=digest)),
        store,
    )
    result = retrieve_with_session(
        EvidenceRequest(QueryTarget(source, "TARGET", snapshot=True)),
        store,
    )

    rows = [
        row
        for row in result.canonical_result.get("evidence", [])
        if row.get("start_line") == 15
    ]
    assert rows
    nearest = rows[0]["position"]["nearest_seen"]
    assert [(item["range"], item["line_gap"]) for item in nearest] == [
        ([11, 11], 3),
        ([10, 10], 4),
    ]
    assert all("ref" in item for item in nearest)

    # Search candidates are not promoted into materialized Evidence history.
    state = store.load()
    assert len(state.seen_evidence_coordinates) == 2


def test_radius_and_top_k_bound_neighbor_output() -> None:
    digest = "a" * 64
    seen = (
        EvidenceCoordinate("A", digest, 10, 10),
        EvidenceCoordinate("B", digest, 20, 20),
        EvidenceCoordinate("far", digest, 1000, 1000),
    )
    rows = attach_seen_evidence_distances(
        [{"uri": "current", "sha256": digest, "start_line": 25, "end_line": 25}],
        seen,
        radius_lines=20,
        neighbor_limit=1,
    )

    nearest = rows[0]["position"]["nearest_seen"]
    assert nearest == [
        {"ref": "B", "range": [20, 20], "line_gap": 4, "direction": "before"}
    ]


def test_old_session_without_coordinate_history_remains_readable() -> None:
    state = RetrievalSessionState.from_dict(
        {
            "schema_version": 1,
            "context_id": "legacy",
            "revision": 2,
            "seen_evidence": [],
            "seen_results": [],
            "seen_groups": [],
            "seen_relations": [],
            "covered_ranges": {},
            "source_observations": {},
            "operation_counts": {},
            "recent_operations": [],
            "request_fingerprints": [],
            "exact_duplicate_requests": 0,
        }
    )

    assert state.seen_evidence_coordinates == ()
    assert state.to_dict()["seen_evidence_coordinates"] == []
