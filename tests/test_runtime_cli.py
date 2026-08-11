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
