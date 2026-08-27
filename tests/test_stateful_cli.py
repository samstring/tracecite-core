from __future__ import annotations

import json

from tracecite.integrations import cli, stateful_cli


def _search_payload(count: int = 1, *, label_suffix: str = "") -> dict[str, object]:
    digest = "a" * 64
    evidence = [
        {
            "uri": f"evidence://sha256/{digest}#L{line}",
            "source_path": "/tmp/frozen.log",
            "sha256": digest,
            "start_line": line,
            "end_line": line,
            "label": f"target event {line}{label_suffix}",
        }
        for line in range(1, count + 1)
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
            "scoped_lines": count,
            "match_records": count,
            "match_lines": count,
            "evidence_returned": count,
            "evidence_truncated": False,
        },
        "missing_evidence": [],
        "verification": {},
        "warnings": [],
        "next_queries": [],
        "data": {"query": "target"},
    }


def _argv(tmp_path) -> list[str]:
    return [
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


def test_context_id_falls_back_when_delta_is_not_smaller_but_state_advances(
    tmp_path, monkeypatch, capsys
) -> None:
    canonical = _search_payload()
    monkeypatch.setattr(cli, "search", lambda *_args, **_kwargs: canonical)
    argv = _argv(tmp_path)

    assert stateful_cli.main(argv) == 0
    first_rendered = capsys.readouterr().out
    first = json.loads(first_rendered)
    assert len(first["evidence"]["rows"]) == 1
    assert "context" not in first["data"]

    assert stateful_cli.main(argv) == 0
    second_rendered = capsys.readouterr().out
    second = json.loads(second_rendered)

    # Suppressing one tiny Evidence row costs more metadata than it saves, so
    # the Agent sees the ordinary compact view while private seen-state still
    # advances. Context optimization therefore never makes this turn larger.
    assert len(second["evidence"]["rows"]) == 1
    assert "context" not in second["data"]
    assert len(second_rendered) <= len(first_rendered)

    state = json.loads((tmp_path / "_contexts" / "case-1.json").read_text(encoding="utf-8"))
    assert state["revision"] == 2
    assert len(state["seen_evidence"]) == 1


def test_context_id_uses_delta_when_repeated_evidence_savings_are_real(
    tmp_path, monkeypatch, capsys
) -> None:
    canonical = _search_payload(30, label_suffix=" " + ("x" * 200))
    monkeypatch.setattr(cli, "search", lambda *_args, **_kwargs: canonical)
    argv = _argv(tmp_path)

    assert stateful_cli.main(argv) == 0
    first_rendered = capsys.readouterr().out
    first = json.loads(first_rendered)
    assert len(first["evidence"]["rows"]) == 30
    assert "context" not in first["data"]
    result_id = first["data"]["result_id"]

    assert stateful_cli.main(argv) == 0
    second_rendered = capsys.readouterr().out
    second = json.loads(second_rendered)

    assert second["evidence"]["rows"] == []
    assert second["outcome"] == "supported"
    assert second["data"]["context"]["new_evidence"] == 0
    assert second["data"]["context"]["repeated_evidence"] == 30
    assert second["data"]["result_id"] == result_id
    assert len(second_rendered) < len(first_rendered)

    stored = cli.EvidenceLedger(tmp_path).load(result_id)
    assert stored == canonical
    assert (tmp_path / "_contexts" / "case-1.json").is_file()


def test_smaller_agent_view_never_selects_a_larger_delta() -> None:
    baseline = {"evidence": ["short"]}
    larger_delta = {"evidence": [], "context": "x" * 100}
    smaller_delta = {"evidence": []}

    assert stateful_cli._smaller_agent_view(larger_delta, baseline) is baseline
    assert stateful_cli._smaller_agent_view(smaller_delta, baseline) is smaller_delta


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
