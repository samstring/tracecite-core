from __future__ import annotations

import json

from tracecite.runtime import EvidenceShellPolicy, EvidenceShellRequest, run_evidence_shell


def _write_jsonl(tmp_path, rows: list[dict]) -> str:
    path = tmp_path / "unix-compat.jsonl"
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    return str(path)


def _policy() -> EvidenceShellPolicy:
    return EvidenceShellPolicy(max_evidence_tokens=10_000, max_evidence_bytes=100_000)


def test_rg_uses_regex_semantics_and_common_flags(tmp_path) -> None:
    source = _write_jsonl(
        tmp_path,
        [
            {"message": "ERROR one"},
            {"message": "failed two"},
            {"message": "ordinary"},
        ],
    )
    result = run_evidence_shell(
        EvidenceShellRequest(source=source, program="rg -i 'error|failed'"),
        policy=_policy(),
    )
    assert result["status"] == "ok"
    assert len(result["evidence"]) == 2


def test_rg_count_and_wc_lines_are_runtime_aggregates(tmp_path) -> None:
    source = _write_jsonl(
        tmp_path,
        [{"message": "ERROR"}, {"message": "ok"}, {"message": "ERROR again"}],
    )
    rg = run_evidence_shell(
        EvidenceShellRequest(source=source, program="rg -c ERROR"),
        policy=EvidenceShellPolicy(max_evidence_tokens=1, max_evidence_bytes=64),
    )
    wc = run_evidence_shell(
        EvidenceShellRequest(source=source, program="grep ERROR | wc -l"),
        policy=EvidenceShellPolicy(max_evidence_tokens=1, max_evidence_bytes=64),
    )
    assert rg["data"]["aggregate"]["count"] == 2
    assert wc["data"]["aggregate"]["count"] == 2
    assert rg["evidence"] == []
    assert wc["evidence"] == []


def test_unix_sort_flags_sort_record_text(tmp_path) -> None:
    source = _write_jsonl(
        tmp_path,
        [{"message": "a"}, {"message": "c"}, {"message": "b"}],
    )
    result = run_evidence_shell(
        EvidenceShellRequest(source=source, program="all | sort -r | head 1"),
        policy=_policy(),
    )
    assert result["status"] == "ok"
    assert len(result["evidence"]) == 1
    assert '"message": "c"' in result["evidence"][0]["label"]


def test_unix_numeric_sort_accepts_nr_combination(tmp_path) -> None:
    source = _write_jsonl(tmp_path, [3, 20, 1])
    result = run_evidence_shell(
        EvidenceShellRequest(source=source, program="all | sort -nr | head 1"),
        policy=_policy(),
    )
    assert result["status"] == "ok"
    assert len(result["evidence"]) == 1
    assert result["evidence"][0]["label"] == "20"


def test_uniq_and_uniq_count_map_to_distinct_and_group(tmp_path) -> None:
    source = _write_jsonl(tmp_path, ["x", "x", "y"])
    distinct = run_evidence_shell(
        EvidenceShellRequest(source=source, program="all | uniq"),
        policy=_policy(),
    )
    counted = run_evidence_shell(
        EvidenceShellRequest(source=source, program="all | uniq -c"),
        policy=_policy(),
    )
    assert distinct["data"]["aggregate"]["distinct_total"] == 2
    groups = counted["data"]["aggregate"]["groups"]
    assert groups[0]["count"] == 2
    assert counted["data"]["aggregate"]["group_total"] == 2


def test_sed_n_line_range_maps_to_record_line_filter(tmp_path) -> None:
    source = _write_jsonl(tmp_path, [{"n": 1}, {"n": 2}, {"n": 3}, {"n": 4}])
    result = run_evidence_shell(
        EvidenceShellRequest(source=source, program="sed -n '2,3p'"),
        policy=_policy(),
    )
    assert result["status"] == "ok"
    assert len(result["evidence"]) == 2
    assert [item["start_line"] for item in result["evidence"]] == [2, 3]


def test_project_is_terminal_derived_output_with_provenance(tmp_path) -> None:
    source = _write_jsonl(
        tmp_path,
        [
            {"serviceName": "route", "statusCode": 500},
            {"serviceName": "other", "statusCode": 503},
        ],
    )
    result = run_evidence_shell(
        EvidenceShellRequest(source=source, program="all | project serviceName"),
        policy=_policy(),
    )
    aggregate = result["data"]["aggregate"]
    assert aggregate["field"] == "serviceName"
    assert [item["value"] for item in aggregate["rows"]] == ["route", "other"]
    assert all(item["uri"].startswith("evidence://sha256/") for item in aggregate["rows"])
    assert result["evidence"] == []


def test_simple_jq_select_maps_to_where(tmp_path) -> None:
    source = _write_jsonl(
        tmp_path,
        [
            {"statusCode": 200, "serviceName": "ok"},
            {"statusCode": 500, "serviceName": "route"},
            {"statusCode": 503, "serviceName": "other"},
        ],
    )
    result = run_evidence_shell(
        EvidenceShellRequest(source=source, program="jq 'select(.statusCode >= 500)'"),
        policy=_policy(),
    )
    assert result["status"] == "ok"
    assert len(result["evidence"]) == 2


def test_simple_jq_projection_maps_to_project(tmp_path) -> None:
    source = _write_jsonl(
        tmp_path,
        [
            {"serviceName": "route"},
            {"serviceName": "other"},
        ],
    )
    result = run_evidence_shell(
        EvidenceShellRequest(source=source, program="jq -r '.serviceName'"),
        policy=_policy(),
    )
    assert result["status"] == "ok"
    assert [item["value"] for item in result["data"]["aggregate"]["rows"]] == [
        "route",
        "other",
    ]


def test_simple_jq_select_then_projection_stays_runtime_side(tmp_path) -> None:
    source = _write_jsonl(
        tmp_path,
        [
            {"statusCode": 200, "serviceName": "ok"},
            {"statusCode": 500, "serviceName": "route"},
            {"statusCode": 503, "serviceName": "other"},
        ],
    )
    result = run_evidence_shell(
        EvidenceShellRequest(
            source=source,
            program="jq 'select(.statusCode >= 500) | .serviceName'",
        ),
        policy=_policy(),
    )
    assert [item["value"] for item in result["data"]["aggregate"]["rows"]] == [
        "route",
        "other",
    ]
