from __future__ import annotations

import json

from tracecite.integrations import cli, stateful_cli


def _search_payload() -> dict[str, object]:
    digest = "a" * 64
    evidence = [
        {
            "uri": f"evidence://sha256/{digest}#L1",
            "source_path": "/tmp/frozen.log",
            "sha256": digest,
            "start_line": 1,
            "end_line": 1,
            "label": "target event",
        }
    ]
    return {
        "schema_version": 1,
        "operation": "search",
        "status": "ok",
        "outcome": "supported",
        "hypotheses": [],
        "evidence": evidence,
        "artifacts": [],
        "coverage": {
            "scoped_lines": 1,
            "match_records": 1,
            "match_lines": 1,
            "evidence_returned": 1,
            "evidence_truncated": False,
        },
        "missing_evidence": [],
        "verification": {},
        "warnings": [],
        "next_queries": [],
        "data": {"query": "target"},
    }


def test_context_id_returns_only_new_evidence_across_cli_turns(
    tmp_path, monkeypatch, capsys
) -> None:
    canonical = _search_payload()
    monkeypatch.setattr(cli, "search", lambda *_args, **_kwargs: canonical)
    argv = [
        "search",
        "events.log",
        "target",
        "--ledger-dir",
        str(tmp_path),
        "--agent-profile",
        "stateful-index",
        "--context-id",
        "case-1",
    ]

    assert stateful_cli.main(argv) == 0
    first = json.loads(capsys.readouterr().out)
    assert len(first["evidence"]["rows"]) == 1
    assert first["data"]["context"]["new_evidence"] == 1
    assert first["data"]["context"]["repeated_evidence"] == 0
    result_id = first["data"]["result_id"]

    assert stateful_cli.main(argv) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["evidence"]["rows"] == []
    assert second["outcome"] == "supported"
    assert second["data"]["context"]["new_evidence"] == 0
    assert second["data"]["context"]["repeated_evidence"] == 1
    assert second["data"]["result_id"] == result_id

    stored = cli.EvidenceLedger(tmp_path).load(result_id)
    assert stored == canonical
    assert (tmp_path / "_contexts" / "case-1.json").is_file()


def test_context_id_requires_ledger_and_stays_machine_readable(capsys) -> None:
    assert stateful_cli.main(
        ["search", "events.log", "target", "--context-id", "case-1"]
    ) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["operation"] == "search"
    assert payload["status"] == "error"
    assert "--ledger-dir" in payload["error"]["message"]


def test_without_context_id_delegates_unchanged(monkeypatch, capsys) -> None:
    canonical = _search_payload()
    monkeypatch.setattr(cli, "search", lambda *_args, **_kwargs: canonical)

    assert stateful_cli.main(["search", "events.log", "target"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert "context" not in payload["data"]
