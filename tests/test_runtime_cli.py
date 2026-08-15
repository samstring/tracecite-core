from __future__ import annotations

import json

from tracecite.integrations import cli


def _payload(status: str = "ok", operation: str = "search") -> dict[str, object]:
    return {
        "schema_version": 1,
        "operation": operation,
        "status": status,
        "outcome": "unknown" if status in {"no_match", "error"} else "not_assessed",
        "hypotheses": [],
        "evidence": [],
        "artifacts": [],
        "coverage": {},
        "missing_evidence": [],
        "verification": {},
        "warnings": [],
        "next_queries": [],
        "data": {},
    }


def test_search_no_match_is_json_and_success(monkeypatch, capsys) -> None:
    calls: dict[str, object] = {}

    def fake_search(*args, **kwargs):
        calls["args"] = args
        calls.update(kwargs)
        return _payload("no_match")

    monkeypatch.setattr(cli, "search", fake_search)

    assert cli.main(
        [
            "search",
            "events.log",
            "OOM",
            "--regex",
            "--no-snapshot",
            "--segmenter",
            "rawtext",
            "--fold",
        ]
    ) == 0

    output = capsys.readouterr().out
    assert json.loads(output)["status"] == "no_match"
    assert calls["regex"] is True
    assert calls["snapshot"] is False
    assert calls["fold"] is True
    assert output.index('"artifacts"') < output.index('"coverage"')


def test_structured_error_returns_one_and_stays_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "verify", lambda *_args, **_kwargs: _payload("error", "verify"))

    assert cli.main(["verify", "manifest.json"]) == 1

    payload = json.loads(capsys.readouterr().out)
    assert payload["operation"] == "verify"
    assert payload["status"] == "error"


def test_expand_routes_context_and_hash_options(monkeypatch, capsys) -> None:
    calls: dict[str, object] = {}

    def fake_expand(*args, **kwargs):
        calls["args"] = args
        calls.update(kwargs)
        return _payload("ok", "expand")

    monkeypatch.setattr(cli, "expand", fake_expand)

    assert cli.main(
        [
            "expand",
            "events.log",
            "8",
            "--end-line",
            "10",
            "--before",
            "2",
            "--after",
            "4",
            "--expected-sha256",
            "abc",
            "--max-chars",
            "100",
        ]
    ) == 0

    assert calls["end_line"] == 10
    assert calls["before"] == 2
    assert calls["after"] == 4
    assert calls["expected_sha256"] == "abc"
    assert calls["max_chars"] == 100
    assert json.loads(capsys.readouterr().out)["operation"] == "expand"


def _search_payload(count: int = 2) -> dict[str, object]:
    payload = _payload("ok")
    digest = "a" * 64
    payload["evidence"] = [
        {
            "uri": f"evidence://sha256/{digest}#L{index}",
            "source_path": "/tmp/frozen.log",
            "sha256": digest,
            "start_line": index,
            "label": f"matching evidence {index} " + ("x" * 120),
            "metadata": {"term": "matching"},
        }
        for index in range(1, count + 1)
    ]
    payload["artifacts"] = [
        {"role": "filtered_log", "path": "/tmp/evidence.log"},
        {"role": "matched_records", "path": "/tmp/evidence.log.records.jsonl"},
    ]
    payload["coverage"] = {
        "scoped_lines": 100,
        "match_records": count,
        "match_lines": count,
        "evidence_returned": count,
        "evidence_truncated": False,
        "unmatched": {"samples": ["large descriptive payload"] * 20},
    }
    payload["data"] = {
        "query": "matching",
        "source_sha256": digest,
    }
    return payload


def test_search_compact_is_cli_projection_not_runtime_argument(monkeypatch, capsys) -> None:
    calls: dict[str, object] = {}

    def fake_search(*args, **kwargs):
        calls.update(kwargs)
        return _search_payload()

    monkeypatch.setattr(cli, "search", fake_search)

    assert cli.main(["search", "events.log", "matching", "--compact"]) == 0
    rendered = capsys.readouterr().out
    payload = json.loads(rendered)
    columns = payload["evidence"]["columns"]
    first = dict(zip(columns, payload["evidence"]["rows"][0]))

    assert "compact" not in calls
    assert "source_path" not in columns
    assert "sha256" not in columns
    assert "uri" not in columns
    assert first["ref"] == "#L1"
    assert first["start"] == 1
    assert payload["data"]["evidence_source"] == {
        "path": "/tmp/frozen.log",
        "sha256": "a" * 64,
        "uri_base": f"evidence://sha256/{'a' * 64}",
    }
    assert payload["artifacts"] == []
    assert "unmatched" not in payload["coverage"]
    assert "\n  " not in rendered


def test_search_compact_budget_trims_structurally_and_keeps_recovery(
    monkeypatch, capsys
) -> None:
    monkeypatch.setattr(cli, "search", lambda *_args, **_kwargs: _search_payload(40))

    assert cli.main(
        ["search", "events.log", "matching", "--max-output-chars", "1200"]
    ) == 0
    rendered = capsys.readouterr().out.strip()
    payload = json.loads(rendered)

    assert len(rendered) <= 1200
    assert payload["coverage"]["evidence_truncated"] is True
    assert payload["coverage"]["evidence_returned"] == len(
        payload["evidence"]["rows"]
    )
    assert payload["coverage"]["evidence_available"] == 40
    assert payload["artifacts"] == [
        {"role": "matched_records", "path": "/tmp/evidence.log.records.jsonl"}
    ]


def test_search_compact_keeps_full_identity_when_sources_are_not_shared() -> None:
    payload = _search_payload(2)
    second = payload["evidence"][1]
    second["source_path"] = "/tmp/other.log"
    second["sha256"] = "b" * 64
    second["uri"] = f"evidence://sha256/{'b' * 64}#L2"

    compact = cli._compact_search_result(payload)

    assert "evidence_source" not in compact["data"]
    columns = compact["evidence"]["columns"]
    rows = [dict(zip(columns, row)) for row in compact["evidence"]["rows"]]
    assert rows[0]["uri"].startswith("evidence://sha256/")
    assert rows[0]["source_path"] == "/tmp/frozen.log"
    assert rows[1]["sha256"] == "b" * 64


def test_search_ledger_stores_canonical_result_before_projection(
    tmp_path, monkeypatch, capsys
) -> None:
    canonical = _search_payload()
    monkeypatch.setattr(cli, "search", lambda *_args, **_kwargs: canonical)

    assert cli.main(
        ["search", "events.log", "matching", "--ledger-dir", str(tmp_path)]
    ) == 0
    projected = json.loads(capsys.readouterr().out)
    result_id = projected["data"]["result_id"]
    stored = cli.EvidenceLedger(tmp_path).load(result_id)

    assert stored == canonical
    assert "result_id" not in stored["data"]
    assert "source_path" in stored["evidence"][0]
    columns = projected["evidence"]["columns"]
    first = dict(zip(columns, projected["evidence"]["rows"][0]))
    assert first["ref"] == "#L1"
