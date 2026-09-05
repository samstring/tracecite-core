from __future__ import annotations

import json

from tracecite.runtime import (
    EvidenceShellPolicy,
    EvidenceShellRequest,
    RetrievalSessionStore,
    run_evidence_shell,
)


def _write_jsonl(tmp_path, rows: list[dict]) -> str:
    path = tmp_path / "agent-regression.jsonl"
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    return str(path)


def _policy() -> EvidenceShellPolicy:
    return EvidenceShellPolicy(max_evidence_tokens=10_000, max_evidence_bytes=100_000)


def test_repeated_evidence_returns_compact_receipt_and_query_memory(tmp_path) -> None:
    source = _write_jsonl(
        tmp_path,
        [{"message": "ERROR", "n": index} for index in range(10)],
    )
    session = RetrievalSessionStore(tmp_path / "sessions", "compact-repeat")
    request = EvidenceShellRequest(source=source, program="search ERROR")

    first = run_evidence_shell(request, policy=_policy(), session=session)
    repeated = run_evidence_shell(request, policy=_policy(), session=session)

    assert len(first["evidence"]) == 10
    assert repeated["evidence"] == []
    novelty = repeated["data"]["novelty"]
    assert novelty["state"] == "no_new_evidence"
    assert novelty["matched_evidence"] == 10
    assert novelty["query_repeated"] is True
    assert "evidence boundary" in novelty["guidance"]

    summary = repeated["data"]["existing_evidence_summary"]
    assert summary["count"] == 10
    assert summary["all_matches_previously_seen"] is True
    assert len(summary["representative"]) <= 2
    assert len(repeated["data"]["matched_existing_evidence"]) <= 2
    for item in summary["representative"]:
        assert item["uri"].startswith("evidence://sha256/")
        assert item["source"] == source
        assert item["start_line"] >= 1
        assert len(item["sha256"]) == 64


def test_different_query_can_hit_only_old_evidence_without_being_exact_duplicate(tmp_path) -> None:
    source = _write_jsonl(
        tmp_path,
        [
            {"message": "ERROR route", "service": "route"},
            {"message": "ERROR other", "service": "other"},
        ],
    )
    session = RetrievalSessionStore(tmp_path / "sessions", "different-query")

    run_evidence_shell(
        EvidenceShellRequest(source=source, program="search ERROR"),
        policy=_policy(),
        session=session,
    )
    result = run_evidence_shell(
        EvidenceShellRequest(source=source, program="search ERROR | where service == route"),
        policy=_policy(),
        session=session,
    )

    assert result["evidence"] == []
    assert result["data"]["novelty"]["state"] == "no_new_evidence"
    assert result["data"]["novelty"]["query_repeated"] is False
    assert result["data"]["existing_evidence_summary"]["count"] == 1


def _timestamp_values(result) -> list[str]:
    return [str(row["value"]) for row in result["data"]["aggregate"]["rows"]]


def test_project_sort_head_is_reordered_before_terminal_projection(tmp_path) -> None:
    source = _write_jsonl(
        tmp_path,
        [{"timestamp": 30}, {"timestamp": 10}, {"timestamp": 20}],
    )
    result = run_evidence_shell(
        EvidenceShellRequest(
            source=source,
            program="project timestamp | sort timestamp asc numeric | head 2",
        ),
        policy=_policy(),
    )

    assert result["status"] == "ok"
    assert _timestamp_values(result) == [
        "1970-01-01T00:00:10.000",
        "1970-01-01T00:00:20.000",
    ]
    assert result["data"]["requested_program"].startswith("project timestamp")
    assert result["data"]["normalized_program"].endswith("project timestamp")


def test_jq_projection_sort_head_uses_projected_field_not_record_text(tmp_path) -> None:
    source = _write_jsonl(
        tmp_path,
        [{"timestamp": 30}, {"timestamp": 10}, {"timestamp": 20}],
    )
    result = run_evidence_shell(
        EvidenceShellRequest(
            source=source,
            program="jq -r '.timestamp' | sort -n | head -2",
        ),
        policy=_policy(),
    )

    assert result["status"] == "ok"
    assert _timestamp_values(result) == [
        "1970-01-01T00:00:10.000",
        "1970-01-01T00:00:20.000",
    ]


def test_simple_jq_test_maps_to_structured_regex_filter(tmp_path) -> None:
    source = _write_jsonl(
        tmp_path,
        [
            {"message": "upstream 503"},
            {"message": "healthy 200"},
            {"message": "another 503"},
        ],
    )
    result = run_evidence_shell(
        EvidenceShellRequest(source=source, program="jq 'select(.message | test(\"503\"))'"),
        policy=_policy(),
    )

    assert result["status"] == "ok"
    assert len(result["evidence"]) == 2


def test_count_followed_by_head_is_accepted_as_scalar_count(tmp_path) -> None:
    source = _write_jsonl(
        tmp_path,
        [{"message": "route"}, {"message": "other"}, {"message": "route"}],
    )
    result = run_evidence_shell(
        EvidenceShellRequest(source=source, program="grep -c route | head 5"),
        policy=EvidenceShellPolicy(max_evidence_tokens=1, max_evidence_bytes=64),
    )

    assert result["status"] == "ok"
    assert result["data"]["aggregate"]["count"] == 2


def test_unsupported_program_returns_actionable_error_instead_of_tool_exception(tmp_path) -> None:
    source = _write_jsonl(tmp_path, [{"message": "ERROR"}])
    result = run_evidence_shell(
        EvidenceShellRequest(source=source, program="awk '{print $1}'"),
        policy=_policy(),
    )

    assert result["status"] == "error"
    assert result["error_code"] == "unsupported_program"
    assert "unsupported" in result["error"].lower()
    assert "supported_hint" in result["data"]
    assert result["evidence"] == []
