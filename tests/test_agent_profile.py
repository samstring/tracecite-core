from __future__ import annotations

import json

import pytest

from tracecite.integrations import cli
from tracecite.integrations.agent_profile import (
    AgentCapabilities,
    get_agent_profile,
    render_frame,
    select_agent_profile,
)


def _canonical_search() -> dict[str, object]:
    digest = "a" * 64
    return {
        "schema_version": 1,
        "operation": "search",
        "status": "ok",
        "outcome": "supported",
        "evidence": [
            {
                "uri": f"evidence://sha256/{digest}#L8",
                "source_path": "/tmp/frozen.log",
                "sha256": digest,
                "start_line": 8,
                "end_line": 8,
                "label": "reloadData invoked",
            }
        ],
        "artifacts": [],
        "coverage": {"match_records": 1, "match_lines": 1},
        "data": {},
        "warnings": [],
        "hypotheses": [],
        "missing_evidence": [],
        "verification": {},
        "next_queries": [],
    }


def test_auto_profile_prefers_smallest_declared_stateful_transport() -> None:
    assert select_agent_profile("auto").name == "agent"
    assert select_agent_profile(
        "auto", AgentCapabilities(stateful_history=True, batch_expand=True)
    ).name == "stateful-index"
    assert select_agent_profile(
        "auto",
        AgentCapabilities(
            stateful_history=True,
            batch_expand=True,
            text_frame=True,
        ),
    ).name == "frame"

    with pytest.raises(ValueError, match="requires capabilities"):
        select_agent_profile("frame", AgentCapabilities(stateful_history=True))


def test_frame_keeps_columnar_identity_and_context() -> None:
    payload = {
        "operation": "expand_many",
        "status": "ok",
        "outcome": "supported",
        "result_id": "b" * 64,
        "evidence": {
            "columns": ["ref", "start", "end", "context"],
            "rows": [["#L8", 8, 8, "c1"]],
        },
        "contexts": [
            {"id": "c1", "lines": [5, 11], "text": "8: reloadData", "truncated": False}
        ],
        "coverage": {"requested": 1, "returned": 1, "truncated": False},
    }

    frame = render_frame(payload)

    assert frame.startswith("@TCF 1 expand_many status=ok outcome=supported")
    assert f"@R {'b' * 64}" in frame
    assert "@E ref\tstart\tend\tcontext" in frame
    assert "#L8\t8\t8\tc1" in frame
    assert "@CTX c1 5-11 truncated=False" in frame
    assert "8: reloadData" in frame


def test_profile_selection_changes_transport_not_canonical_result(tmp_path, monkeypatch, capsys) -> None:
    canonical = _canonical_search()
    monkeypatch.setattr(cli, "search", lambda *_args, **_kwargs: canonical)

    assert cli.main(
        ["search", "events.log", "reloadData", "--agent-profile", "portable-json"]
    ) == 0
    portable = json.loads(capsys.readouterr().out)
    assert portable["evidence"]["columns"][0] == "ref"

    assert cli.main(
        [
            "search",
            "events.log",
            "reloadData",
            "--agent-profile",
            "frame",
            "--ledger-dir",
            str(tmp_path),
        ]
    ) == 0
    frame = capsys.readouterr().out
    assert frame.startswith("@TCF 1 search status=ok outcome=supported")
    assert "@R " in frame
    assert "@E ref\tstart\tend\tlabel" in frame

    result_id = next(line[3:] for line in frame.splitlines() if line.startswith("@R "))
    assert cli.EvidenceLedger(tmp_path).load(result_id) == canonical


def test_stateful_profile_requires_private_ledger(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "search", lambda *_args, **_kwargs: _canonical_search())

    assert cli.main(
        ["search", "events.log", "reloadData", "--agent-profile", "stateful-index"]
    ) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "error"
    assert "requires --ledger-dir" in payload["error"]["message"]


def test_frame_preserves_structured_error_message() -> None:
    frame = render_frame(
        {
            "operation": "search",
            "status": "error",
            "outcome": "unknown",
            "error": {"message": "ledger is required"},
        }
    )

    assert "@ERR ledger is required" in frame


def test_profile_registry_keeps_existing_json_profile() -> None:
    assert get_agent_profile("portable-json").transport == "columnar-json"
