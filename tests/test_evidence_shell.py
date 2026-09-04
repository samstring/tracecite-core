from __future__ import annotations

import json

import pytest

from tracecite.runtime import (
    EvidenceShellPolicy,
    EvidenceShellRequest,
    RetrievalSessionStore,
    run_evidence_shell,
)


def _write_jsonl(tmp_path, rows: list[dict]) -> str:
    path = tmp_path / "trace.jsonl"
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    return str(path)


def test_shell_request_does_not_allow_agent_budget_override(tmp_path) -> None:
    source = _write_jsonl(tmp_path, [{"message": "ERROR one"}])

    with pytest.raises(TypeError):
        EvidenceShellRequest(  # type: ignore[call-arg]
            source=source,
            program="search ERROR",
            max_evidence_tokens=999999,
        )


def test_under_budget_search_returns_all_matched_evidence_without_index(tmp_path) -> None:
    source = _write_jsonl(
        tmp_path,
        [
            {"message": "ERROR one", "service": "route"},
            {"message": "ok", "service": "other"},
            {"message": "ERROR two", "service": "route"},
        ],
    )

    result = run_evidence_shell(
        EvidenceShellRequest(source=source, program="search ERROR"),
        policy=EvidenceShellPolicy(max_evidence_tokens=10_000, max_evidence_bytes=100_000),
    )

    assert result["status"] == "ok"
    assert len(result["evidence"]) == 2
    assert result["coverage"]["evidence_returned"] == 2
    assert result["coverage"]["complete"] is True
    assert "evidence_index" not in result["data"]
    assert result["artifacts"] == []


def test_literal_search_preserves_regex_metacharacters_as_literal_text(tmp_path) -> None:
    source = _write_jsonl(
        tmp_path,
        [
            {"message": "worker[3].ready"},
            {"message": "worker333ready"},
        ],
    )

    result = run_evidence_shell(
        EvidenceShellRequest(source=source, program="search 'worker[3].ready'"),
        policy=EvidenceShellPolicy(max_evidence_tokens=1_000, max_evidence_bytes=16_000),
    )

    assert result["status"] == "ok"
    assert len(result["evidence"]) == 1


def test_over_budget_search_returns_too_broad_and_no_partial_evidence(tmp_path) -> None:
    source = _write_jsonl(
        tmp_path,
        [
            {"message": "ERROR " + ("x" * 300), "n": index}
            for index in range(20)
        ],
    )

    result = run_evidence_shell(
        EvidenceShellRequest(source=source, program="search ERROR"),
        policy=EvidenceShellPolicy(max_evidence_tokens=20, max_evidence_bytes=100_000),
    )

    assert result["status"] == "too_broad"
    assert result["evidence"] == []
    assert result["coverage"]["too_broad"] is True
    assert result["coverage"]["evidence_returned"] == 0
    assert result["coverage"]["observed_at_least_tokens"] > 20
    assert result["data"]["refine_query"] is True
    assert result["data"]["reason"] == "MATCHED_EVIDENCE_BUDGET_EXCEEDED"
    assert result["data"]["evidence_budget"]["owner"] == "user_policy"


def test_pipeline_refines_broad_first_search_before_budget_gate(tmp_path) -> None:
    rows = [
        {"message": "ERROR ordinary", "serviceName": "other", "n": index}
        for index in range(100)
    ]
    rows.append(
        {"message": "ERROR selected", "serviceName": "ts-route-service", "n": 101}
    )
    source = _write_jsonl(tmp_path, rows)

    result = run_evidence_shell(
        EvidenceShellRequest(
            source=source,
            program="search ERROR | search ts-route-service",
        ),
        policy=EvidenceShellPolicy(max_evidence_tokens=100, max_evidence_bytes=4096),
    )

    assert result["status"] == "ok"
    assert len(result["evidence"]) == 1
    assert result["coverage"]["too_broad"] is False


def test_structured_where_refines_json_records(tmp_path) -> None:
    source = _write_jsonl(
        tmp_path,
        [
            {"statusCode": 200, "serviceName": "ts-route-service"},
            {"statusCode": 500, "serviceName": "other"},
            {"statusCode": 500, "serviceName": "ts-route-service"},
        ],
    )

    result = run_evidence_shell(
        EvidenceShellRequest(
            source=source,
            program="search statusCode | where statusCode == 500 | where serviceName == ts-route-service",
        ),
        policy=EvidenceShellPolicy(max_evidence_tokens=100, max_evidence_bytes=4096),
    )

    assert result["status"] == "ok"
    assert len(result["evidence"]) == 1


def test_aggregate_can_process_broad_match_without_exposing_record_bodies(tmp_path) -> None:
    source = _write_jsonl(
        tmp_path,
        [{"message": "ERROR", "service": "route", "n": index} for index in range(250)],
    )

    result = run_evidence_shell(
        EvidenceShellRequest(source=source, program="search ERROR | count"),
        policy=EvidenceShellPolicy(max_evidence_tokens=1, max_evidence_bytes=1),
    )

    assert result["status"] == "ok"
    assert result["evidence"] == []
    assert result["data"]["aggregate"]["count"] == 250
    assert result["coverage"]["match_records"] == 250


def test_explicit_take_is_marked_as_selection_not_complete_search(tmp_path) -> None:
    source = _write_jsonl(
        tmp_path,
        [{"message": "ERROR", "n": index} for index in range(10)],
    )

    result = run_evidence_shell(
        EvidenceShellRequest(source=source, program="search ERROR | take 2"),
        policy=EvidenceShellPolicy(max_evidence_tokens=100, max_evidence_bytes=4096),
    )

    assert result["status"] == "ok"
    assert len(result["evidence"]) == 2
    assert result["coverage"]["selection_explicit"] is True
    assert result["coverage"]["complete"] is False


def test_retrieval_session_suppresses_repeated_shell_evidence(tmp_path) -> None:
    source = _write_jsonl(
        tmp_path,
        [
            {"message": "ERROR one"},
            {"message": "ERROR two"},
        ],
    )
    session = RetrievalSessionStore(tmp_path / "sessions", "shell-test")
    policy = EvidenceShellPolicy(max_evidence_tokens=1_000, max_evidence_bytes=16_000)
    request = EvidenceShellRequest(source=source, program="search ERROR")

    first = run_evidence_shell(request, policy=policy, session=session)
    second = run_evidence_shell(request, policy=policy, session=session)

    assert first["status"] == "ok"
    assert len(first["evidence"]) == 2
    assert second["status"] == "ok"
    assert second["evidence"] == []
    assert second["data"]["novelty"]["state"] == "no_new_evidence"
    assert second["coverage"]["repeated_evidence"] == 2
    assert len(second["data"]["matched_existing_evidence"]) == 2


def test_too_broad_does_not_pollute_retrieval_session(tmp_path) -> None:
    source = _write_jsonl(
        tmp_path,
        [{"message": "ERROR " + ("x" * 300), "n": index} for index in range(5)],
    )
    session = RetrievalSessionStore(tmp_path / "sessions", "too-broad")

    result = run_evidence_shell(
        EvidenceShellRequest(source=source, program="search ERROR"),
        policy=EvidenceShellPolicy(max_evidence_tokens=10, max_evidence_bytes=100_000),
        session=session,
    )

    assert result["status"] == "too_broad"
    state = session.load()
    assert state.seen_evidence == ()
    assert state.recent_operations == ()
