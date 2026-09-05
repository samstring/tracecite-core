from __future__ import annotations

import json

from tracecite.runtime import EvidenceShellPolicy, EvidenceShellRequest, run_evidence_shell
from tracecite.runtime.evidence_shell import run_evidence_shell as run_canonical_evidence_shell


def _policy() -> EvidenceShellPolicy:
    return EvidenceShellPolicy(max_evidence_tokens=10_000, max_evidence_bytes=100_000)


def _jsonl(tmp_path, rows: list[dict]) -> str:
    path = tmp_path / "traces.jsonl"
    path.write_text(
        "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )
    return str(path)


def test_large_jsonl_field_group_uses_single_pass_engine(tmp_path) -> None:
    source = _jsonl(
        tmp_path,
        [
            {
                "serviceName": "route" if index % 3 else "auth",
                "statusCode": 503 if index % 2 else None,
                "spanId": index,
            }
            for index in range(5000)
        ],
    )

    result = run_evidence_shell(
        EvidenceShellRequest(
            source=source,
            program="where statusCode != null | group serviceName | sort count desc numeric | head 1",
        ),
        policy=_policy(),
    )

    assert result["status"] == "ok"
    assert result["data"]["execution_engine"] == "jsonl_single_pass_field_aggregate"
    aggregate = result["data"]["aggregate"]
    assert aggregate["group_total"] == 2
    assert aggregate["groups_returned"] == 1
    assert aggregate["groups"][0]["key"] == "route"
    assert aggregate["groups"][0]["count"] > 0


def test_absolute_time_scoped_jsonl_group_stays_on_streaming_fast_path(tmp_path) -> None:
    source = _jsonl(
        tmp_path,
        [
            {"timestamp": "2026-09-05T10:00:00Z", "serviceName": "edge", "statusCode": 200},
            {"timestamp": "2026-09-05T10:05:00Z", "serviceName": "route", "statusCode": 503},
            {"timestamp": "2026-09-05T10:10:00Z", "serviceName": "route", "statusCode": 503},
            {"timestamp": "2026-09-05T10:20:00Z", "serviceName": "auth", "statusCode": 503},
        ],
    )
    request = EvidenceShellRequest(
        source=source,
        program="where statusCode >= 500 | group serviceName",
        since="2026-09-05T10:04:00Z",
        until="2026-09-05T10:15:00Z",
    )

    fast = run_evidence_shell(request, policy=_policy())
    canonical = run_canonical_evidence_shell(request, policy=_policy())

    assert fast["status"] == "ok"
    assert fast["data"]["execution_engine"] == "jsonl_single_pass_time_scoped_field_aggregate"
    assert fast["data"]["aggregate"] == canonical["data"]["aggregate"]
    assert fast["data"]["aggregate"]["groups"] == [{"key": "route", "count": 2}]
    assert fast["coverage"]["match_records"] == 2


def test_reference_relative_clock_scope_remains_canonical(tmp_path) -> None:
    source = _jsonl(
        tmp_path,
        [
            {"timestamp": "2026-09-05T10:00:00", "serviceName": "edge"},
            {"timestamp": "2026-09-05T10:10:00", "serviceName": "route"},
        ],
    )
    result = run_evidence_shell(
        EvidenceShellRequest(
            source=source,
            program="group serviceName",
            since="10:05:00",
        ),
        policy=_policy(),
    )

    assert result["status"] == "ok"
    assert result.get("data", {}).get("execution_engine") != "jsonl_single_pass_time_scoped_field_aggregate"


def test_jsonl_distinct_sort_head_stays_in_one_call(tmp_path) -> None:
    source = _jsonl(
        tmp_path,
        [
            {"serviceName": "route", "statusCode": 200},
            {"serviceName": "auth", "statusCode": 200},
            {"serviceName": "route", "statusCode": 503},
        ],
    )

    result = run_evidence_shell(
        EvidenceShellRequest(
            source=source,
            program="distinct serviceName | sort value asc | head 1",
        ),
        policy=_policy(),
    )

    assert result["status"] == "ok"
    assert result["data"]["execution_engine"] == "jsonl_single_pass_field_aggregate"
    aggregate = result["data"]["aggregate"]
    assert aggregate["distinct_total"] == 2
    assert aggregate["values_returned"] == 1
    assert aggregate["values"] == ["auth"]


def test_projection_sort_uniq_count_topn_rewrites_to_group(tmp_path) -> None:
    source = _jsonl(
        tmp_path,
        [
            {"serviceName": "route"},
            {"serviceName": "auth"},
            {"serviceName": "route"},
            {"serviceName": "route"},
        ],
    )

    result = run_evidence_shell(
        EvidenceShellRequest(
            source=source,
            program="jq -r '.serviceName' | sort | uniq -c | sort -nr | head 1",
        ),
        policy=_policy(),
    )

    assert result["status"] == "ok"
    aggregate = result["data"]["aggregate"]
    assert aggregate["groups"] == [{"key": "route", "count": 3}]
    assert result["data"]["requested_program"].startswith("jq -r")


def test_compound_group_sort_head_works_for_non_json_text(tmp_path) -> None:
    source = tmp_path / "plain.log"
    source.write_text("beta\nalpha\nbeta\ngamma\nbeta\n", encoding="utf-8")

    result = run_evidence_shell(
        EvidenceShellRequest(
            source=str(source),
            segmenter="rawtext",
            program="group text | sort count desc numeric | head 1",
        ),
        policy=_policy(),
    )

    assert result["status"] == "ok"
    assert result["data"]["compound_postprocess"] is True
    assert result["data"]["aggregate"]["groups"] == [{"key": "beta", "count": 3}]


def test_projection_followed_by_head_is_reordered_before_terminal_project(tmp_path) -> None:
    source = _jsonl(tmp_path, [{"serviceName": "route"}, {"serviceName": "auth"}])
    result = run_evidence_shell(
        EvidenceShellRequest(source=source, program="jq -r '.serviceName' | head -1"),
        policy=_policy(),
    )

    assert result["status"] == "ok"
    rows = result["data"]["aggregate"]["rows"]
    assert len(rows) == 1
    assert rows[0]["value"] == "route"
