from __future__ import annotations

import json
from types import SimpleNamespace

from tracecite.integrations import cli, stateful_cli
from tracecite.integrations.agent_projection import prefer_smaller_agent_view
from tracecite.runtime import EvidenceRequest, QueryTarget, RangeTarget


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
        "outcome": "not_assessed",
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
        "data": {"query": "target", "routing": {"route": "progressive"}},
    }


def _expand_payload() -> dict[str, object]:
    digest = "b" * 64
    return {
        "schema_version": 1,
        "operation": "expand",
        "status": "ok",
        "outcome": "not_assessed",
        "hypotheses": [],
        "evidence": [
            {
                "uri": f"evidence://sha256/{digest}#L8-L10",
                "source_path": "/tmp/events.log",
                "sha256": digest,
                "start_line": 8,
                "end_line": 10,
                "label": "bounded raw context",
            }
        ],
        "artifacts": [],
        "coverage": {"context_start_line": 6, "context_end_line": 14},
        "missing_evidence": [],
        "verification": {},
        "warnings": [],
        "next_queries": [],
        "data": {"routing": {"route": "progressive"}},
    }


def _install_retrieve(monkeypatch, canonical, calls: list[EvidenceRequest] | None = None) -> None:
    def fake_retrieve(request: EvidenceRequest):
        if calls is not None:
            calls.append(request)
        return SimpleNamespace(canonical_result=canonical)

    monkeypatch.setattr(stateful_cli, "retrieve", fake_retrieve)


def _argv(tmp_path, *, profile: str = "stateful-index", context_id: str = "case-1") -> list[str]:
    return [
        "search",
        "events.log",
        "target",
        "--ledger-dir",
        str(tmp_path),
        "--agent-profile",
        profile,
        "--context-id",
        context_id,
    ]


def test_public_search_routes_through_typed_retrieve(monkeypatch, capsys) -> None:
    calls: list[EvidenceRequest] = []
    _install_retrieve(monkeypatch, _search_payload(), calls)

    assert stateful_cli.main(
        [
            "search",
            "events.log",
            "target",
            "--regex",
            "--no-snapshot",
            "--segmenter",
            "rawtext",
            "--fold",
            "--no-cache",
        ]
    ) == 0

    assert len(calls) == 1
    request = calls[0]
    assert isinstance(request, EvidenceRequest)
    assert isinstance(request.target, QueryTarget)
    assert str(request.target.source) == "events.log"
    assert request.target.query == "target"
    assert request.target.regex is True
    assert request.target.snapshot is False
    assert request.target.segmenter == "rawtext"
    assert request.target.fold is True
    assert "max_evidence" not in request.target.__dataclass_fields__
    assert "max_line_chars" not in request.target.__dataclass_fields__
    assert request.cache is False
    payload = json.loads(capsys.readouterr().out)
    assert payload["outcome"] == "not_assessed"
    assert payload["data"]["routing"]["route"] == "progressive"


def test_public_expand_routes_through_typed_retrieve(monkeypatch, capsys) -> None:
    calls: list[EvidenceRequest] = []
    _install_retrieve(monkeypatch, _expand_payload(), calls)

    assert stateful_cli.main(
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

    assert len(calls) == 1
    request = calls[0]
    assert isinstance(request.target, RangeTarget)
    assert str(request.target.source) == "events.log"
    assert request.target.start_line == 8
    assert request.target.end_line == 10
    assert request.target.before == 2
    assert request.target.after == 4
    assert request.target.expected_sha256 == "abc"
    assert request.target.max_chars == 100
    assert json.loads(capsys.readouterr().out)["operation"] == "expand"


def test_search_output_path_is_explicit_legacy_fallback(monkeypatch, capsys, tmp_path) -> None:
    canonical = _search_payload()
    calls: dict[str, object] = {}

    def legacy_search(*args, **kwargs):
        calls["args"] = args
        calls.update(kwargs)
        return canonical

    def forbidden_retrieve(_request):
        raise AssertionError("output-path compatibility must stay on the legacy side-effect path")

    monkeypatch.setattr(cli, "search", legacy_search)
    monkeypatch.setattr(stateful_cli, "retrieve", forbidden_retrieve)
    output = tmp_path / "filtered.log"

    assert stateful_cli.main(
        ["search", "events.log", "target", "--output-path", str(output)]
    ) == 0
    assert calls["output_path"] == output
    assert json.loads(capsys.readouterr().out)["operation"] == "search"
    assert cli.search is legacy_search


def test_context_id_falls_back_when_delta_is_not_smaller_but_state_advances(
    tmp_path, monkeypatch, capsys
) -> None:
    canonical = _search_payload()
    _install_retrieve(monkeypatch, canonical)
    argv = _argv(tmp_path)

    assert stateful_cli.main(argv) == 0
    first_rendered = capsys.readouterr().out
    first = json.loads(first_rendered)
    assert len(first["evidence"]["rows"]) == 1
    assert "context" not in first["data"]

    assert stateful_cli.main(argv) == 0
    second_rendered = capsys.readouterr().out
    second = json.loads(second_rendered)

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
    _install_retrieve(monkeypatch, canonical)
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
    assert second["outcome"] == "not_assessed"
    assert second["data"]["context"]["new_evidence"] == 0
    assert second["data"]["context"]["repeated_evidence"] == 30
    assert second["data"]["result_id"] == result_id
    assert len(second_rendered) < len(first_rendered)

    stored = cli.EvidenceLedger(tmp_path).load(result_id)
    assert stored == canonical
    assert (tmp_path / "_contexts" / "case-1.json").is_file()


def test_frame_context_chooses_delta_by_frame_size(
    tmp_path, monkeypatch, capsys
) -> None:
    canonical = _search_payload(30, label_suffix=" " + ("x" * 200))
    _install_retrieve(monkeypatch, canonical)
    argv = _argv(tmp_path, profile="frame", context_id="frame-case")

    assert stateful_cli.main(argv) == 0
    first_rendered = capsys.readouterr().out
    assert first_rendered.startswith("@TCF 1 search")
    assert "target event" in first_rendered

    assert stateful_cli.main(argv) == 0
    second_rendered = capsys.readouterr().out
    assert second_rendered.startswith("@TCF 1 search")
    assert len(second_rendered) < len(first_rendered)
    assert "target event" not in second_rendered
    assert "already seen in the selected Agent context" in second_rendered

    state = json.loads(
        (tmp_path / "_contexts" / "frame-case.json").read_text(encoding="utf-8")
    )
    assert state["revision"] == 2
    assert len(state["seen_evidence"]) == 30


def test_smaller_agent_view_never_selects_a_larger_delta() -> None:
    baseline = {"evidence": ["short"]}
    larger_delta = {"evidence": [], "context": "x" * 100}
    smaller_delta = {"evidence": []}

    assert prefer_smaller_agent_view(larger_delta, baseline) == baseline
    assert prefer_smaller_agent_view(smaller_delta, baseline) == smaller_delta


def test_context_id_requires_ledger_and_stays_machine_readable(capsys) -> None:
    assert stateful_cli.main(
        ["search", "events.log", "target", "--context-id", "case-1"]
    ) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["operation"] == "search"
    assert payload["status"] == "error"
    assert "--ledger-dir" in payload["error"]["message"]


def test_without_context_id_uses_runtime_without_context_projection(monkeypatch, capsys) -> None:
    canonical = _search_payload()
    calls: list[EvidenceRequest] = []
    _install_retrieve(monkeypatch, canonical, calls)

    assert stateful_cli.main(["search", "events.log", "target"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(calls) == 1
    assert "context" not in payload["data"]
