from __future__ import annotations

from copy import deepcopy

import pytest

from tracecite.integrations.context_engine import (
    ContextEngine,
    ContextState,
    ContextStateStore,
    project_search_delta,
)


def _search_result(*lines: int) -> dict[str, object]:
    digest = "a" * 64
    evidence = [
        {
            "uri": f"evidence://sha256/{digest}#L{line}",
            "source_path": "/tmp/frozen.log",
            "sha256": digest,
            "start_line": line,
            "end_line": line,
            "label": f"line {line}",
        }
        for line in lines
    ]
    return {
        "schema_version": 1,
        "operation": "search",
        "status": "ok",
        "outcome": "supported",
        "evidence": evidence,
        "artifacts": [],
        "coverage": {"match_records": len(evidence), "evidence_returned": len(evidence)},
        "data": {},
        "warnings": [],
        "missing_evidence": [],
        "next_queries": [],
    }


def test_first_projection_returns_all_evidence_without_mutating_canonical() -> None:
    canonical = _search_result(2, 5)
    original = deepcopy(canonical)
    state = ContextState(context_id="investigation-1")

    projected, next_state = project_search_delta(
        canonical,
        state,
        result_id="b" * 64,
    )

    assert canonical == original
    assert [row["start_line"] for row in projected["evidence"]] == [2, 5]
    assert projected["data"]["context"]["new_evidence"] == 2
    assert projected["data"]["context"]["repeated_evidence"] == 0
    assert projected["coverage"]["canonical_evidence_returned"] == 2
    assert projected["coverage"]["evidence_returned"] == 2
    assert next_state.revision == 1
    assert len(next_state.seen_evidence) == 2
    assert next_state.seen_results == ("b" * 64,)


def test_repeated_result_emits_empty_evidence_delta() -> None:
    canonical = _search_result(2, 5)
    first, state = project_search_delta(
        canonical,
        ContextState(context_id="investigation-1"),
        result_id="b" * 64,
    )
    assert len(first["evidence"]) == 2

    second, state = project_search_delta(
        canonical,
        state,
        result_id="b" * 64,
    )

    assert second["evidence"] == []
    assert second["outcome"] == "supported"
    assert second["data"]["context"]["result_repeated"] is True
    assert second["data"]["context"]["repeated_evidence"] == 2
    assert second["coverage"]["evidence_returned"] == 0
    assert second["coverage"]["context_evidence_repeated"] == 2
    assert any("already seen" in item for item in second["warnings"])
    assert state.revision == 2


def test_overlapping_search_returns_only_new_evidence() -> None:
    _, state = project_search_delta(
        _search_result(2, 5),
        ContextState(context_id="investigation-1"),
    )

    delta, state = project_search_delta(_search_result(5, 8, 13), state)

    assert [row["start_line"] for row in delta["evidence"]] == [8, 13]
    assert delta["data"]["context"]["new_evidence"] == 2
    assert delta["data"]["context"]["repeated_evidence"] == 1
    assert len(state.seen_evidence) == 4


def test_engine_persists_seen_state_between_instances(tmp_path) -> None:
    result_id = "c" * 64
    first = ContextEngine(tmp_path, "agent-session")
    first_view = first.project_search(_search_result(3), result_id=result_id)
    assert len(first_view["evidence"]) == 1

    second = ContextEngine(tmp_path, "agent-session")
    second_view = second.project_search(_search_result(3), result_id=result_id)

    assert second_view["evidence"] == []
    assert second.state().revision == 2
    assert second.state().seen_results == (result_id,)


def test_bounded_state_prunes_oldest_transport_memory() -> None:
    engine_state = ContextState(context_id="small")
    first, engine_state = project_search_delta(
        _search_result(1, 2, 3),
        engine_state,
        max_seen_evidence=2,
        max_seen_results=2,
    )

    assert first["data"]["context"]["state_pruned"] is True
    assert tuple(uri.rsplit("L", 1)[-1] for uri in engine_state.seen_evidence) == ("2", "3")

    second, _ = project_search_delta(
        _search_result(1),
        engine_state,
        max_seen_evidence=2,
        max_seen_results=2,
    )
    assert [row["start_line"] for row in second["evidence"]] == [1]


def test_unidentified_evidence_is_never_silently_deduplicated() -> None:
    payload = _search_result()
    payload["evidence"] = [{"start_line": 9, "end_line": 9, "label": "no uri"}]

    first, state = project_search_delta(payload, ContextState(context_id="unknown-uri"))
    second, _ = project_search_delta(payload, state)

    assert len(first["evidence"]) == 1
    assert len(second["evidence"]) == 1
    assert second["data"]["context"]["unidentified_evidence"] == 1


def test_store_rejects_invalid_context_ids(tmp_path) -> None:
    with pytest.raises(ValueError, match="context_id"):
        ContextStateStore(tmp_path, "../escape")
