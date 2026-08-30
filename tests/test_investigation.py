from __future__ import annotations

import json
from pathlib import Path

import pytest

from tracecite.runtime import InvestigationError, InvestigationStore, tools
from tracecite.runtime.test_assessment import assess_test
from tracecite.runtime.tools import search
from tracecite.integrations import cli


VALID_REF = "evidence://sha256/" + ("a" * 64) + "#L2"


def _store(tmp_path: Path) -> InvestigationStore:
    store = InvestigationStore(tmp_path / "investigation.json")
    store.create("why did the request fail?", scope={"sources": ["app.log"]})
    return store


def test_investigation_lifecycle_persists_version_and_links(tmp_path: Path) -> None:
    store = _store(tmp_path)
    hypothesis = store.add_hypothesis("the request timed out", hypothesis_id="H1")
    test = store.add_test(
        "H1",
        "inspect timeout records",
        expected_observation="timeout is present",
        contradicting_observation="request completed successfully",
        test_id="T1",
    )
    execution = store.record_execution(
        "search",
        {
            "status": "ok",
            "outcome": "supported",
            "data": {"raw": "x" * 100_000},
            "evidence": [
                {
                    "uri": VALID_REF,
                    "metadata": {"text": "raw log " * 100_000},
                }
            ],
            "coverage": {"complete": True},
            "verification": {"integrity_checked": True},
        },
        hypothesis_id="H1",
        test_id="T1",
    )
    assessment = assess_test(
        store,
        "T1",
        "supported",
        evidence_refs=[VALID_REF],
        coverage={"complete": True},
    )
    finding = store.add_finding(
        "H1",
        "supported",
        "timeout evidence was found",
        supporting_evidence=[VALID_REF],
        coverage={"complete": True},
    )
    completed = store.stop("the hypothesis was evaluated")

    payload = json.loads(store.path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["revision"] == 6
    assert payload["status"] == "completed"
    assert payload["stop_reason"]["kind"] == "completed"
    assert payload["hypotheses"][0]["test_ids"] == [test["id"]]
    assert payload["tests"][0]["execution_ids"] == [
        execution["id"],
        assessment["execution_id"],
    ]
    assert payload["findings"][0]["id"] == finding["id"]
    assert "data" not in payload["executions"][0]
    assert "raw" not in json.dumps(payload["executions"][0], ensure_ascii=False)
    assert completed.revision == 6

    with pytest.raises(InvestigationError, match="不能继续修改"):
        store.add_hypothesis("another claim")


def test_cross_links_and_ids_are_validated(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.add_hypothesis("claim", hypothesis_id="H1")
    with pytest.raises(InvestigationError, match="未知 hypothesis"):
        store.add_test(
            "H2",
            "intent",
            expected_observation="yes",
            contradicting_observation="no",
        )
    with pytest.raises(InvestigationError, match="格式无效"):
        store.add_hypothesis("bad id", hypothesis_id="bad id")

    raw = json.loads(store.path.read_text(encoding="utf-8"))
    raw["hypotheses"].append(
        {
            "id": "H2",
            "claim": "other",
            "status": "open",
            "test_ids": ["T-does-not-exist"],
            "supporting_evidence": [],
            "contradicting_evidence": [],
            "created_at": "now",
        }
    )
    store.path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(InvestigationError, match="未知 test"):
        store.load()


def test_tool_link_is_optional_and_execution_is_bounded(tmp_path: Path) -> None:
    source = tmp_path / "source.log"
    source.write_text("target\n", encoding="utf-8")
    store = _store(tmp_path)
    store.add_hypothesis("target exists", hypothesis_id="H1")
    store.add_test(
        "H1",
        "search",
        expected_observation="target appears",
        contradicting_observation="target is absent",
        test_id="T1",
    )

    unlinked = search(source, "target")
    assert "investigation" not in unlinked
    linked = search(
        source,
        "target",
        investigation_path=store.path,
        hypothesis_id="H1",
        test_id="T1",
    )
    assert linked["investigation"]["test_id"] == "T1"
    assert "data" not in store.load().executions[0]


def test_investigation_cli_lifecycle(tmp_path: Path, capsys) -> None:
    path = tmp_path / "state.json"
    assert cli.main(["investigation", "create", str(path), "question", "--id", "INV-1"]) == 0
    json.loads(capsys.readouterr().out)
    assert cli.main(
        ["investigation", "add-hypothesis", str(path), "claim", "--id", "H1"]
    ) == 0
    json.loads(capsys.readouterr().out)
    assert cli.main(
        [
            "investigation",
            "add-test",
            str(path),
            "H1",
            "inspect",
            "--expected",
            "present",
            "--contradicting",
            "absent",
            "--id",
            "T1",
        ]
    ) == 0
    json.loads(capsys.readouterr().out)
    assert cli.main(
        ["investigation", "add-finding", str(path), "H1", "unknown", "insufficient"]
    ) == 0
    json.loads(capsys.readouterr().out)
    assert cli.main(["investigation", "stop", str(path), "done"]) == 0
    stopped = json.loads(capsys.readouterr().out)
    assert stopped["status"] == "completed"
    assert cli.main(["investigation", "show", str(path)]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["investigation_id"] == "INV-1"


def test_user_state_json_is_rejected_instead_of_silently_truncated(tmp_path: Path) -> None:
    store = InvestigationStore(tmp_path / "state.json")
    with pytest.raises(InvestigationError, match="字段过多"):
        store.create("question", scope={str(i): i for i in range(101)})
    store.create("question")
    with pytest.raises(InvestigationError, match="不能超过"):
        store.add_hypothesis("claim", rationale="x" * 4_097)


def test_execution_keeps_small_error_run_metadata_and_truncation_flags(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    store.add_hypothesis("claim", hypothesis_id="H1")
    store.add_test(
        "H1",
        "intent",
        expected_observation="yes",
        contradicting_observation="no",
        test_id="T1",
    )
    execution = store.record_execution(
        "run",
        {
            "status": "error",
            "outcome": "unknown",
            "error": {"type": "ValueError", "message": "bad input"},
            "run_id": "run-1",
            "verdict": "error",
            "verification": {"integrity_checked": False},
            "warnings": ["w" * 5_000],
            "evidence": [{"uri": f"evidence://{i}"} for i in range(101)],
            "data": {"secret": "must not persist"},
        },
        hypothesis_id="H1",
        test_id="T1",
    )
    assert execution["error"]["message"] == "bad input"
    assert execution["run_id"] == "run-1"
    assert execution["verdict"] == "error"
    assert execution["verification"]["integrity_checked"] is False
    assert execution["recording"]["data_omitted"] is True
    assert execution["recording"]["evidence_truncated"] is True
    assert execution["recording"]["warnings_truncated"] is True
    assert execution["recording"]["error_truncated"] is False
    persisted = json.dumps(store.load().to_dict(), ensure_ascii=False)
    assert "must not persist" not in persisted


def test_finding_outcomes_require_matching_evidence(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.add_hypothesis("claim", hypothesis_id="H1")
    store.add_test(
        "H1",
        "intent",
        expected_observation="yes",
        contradicting_observation="no",
        test_id="T1",
    )
    with pytest.raises(InvestigationError, match="supporting_evidence"):
        store.add_finding("H1", "supported", "missing support")
    with pytest.raises(InvestigationError, match="contradicting_evidence"):
        store.add_finding("H1", "contradicted", "missing contradiction")
    finding = store.add_finding("H1", "unknown", "evidence is inconclusive")
    assert finding["supporting_evidence"] == []
    assert finding["contradicting_evidence"] == []


def test_external_error_is_bounded_with_an_explicit_flag(tmp_path: Path) -> None:
    store = _store(tmp_path)
    execution = store.record_execution(
        "search",
        {
            "status": "error",
            "error": {
                "type": "ValueError",
                "message": "m" * 5_000,
                "code": "c" * 5_000,
            },
        },
    )
    assert len(execution["error"]["message"]) == 4_096
    assert len(execution["error"]["code"]) == 4_096
    assert execution["recording"]["error_truncated"] is True
    assert store.load().executions[0]["recording"]["error_truncated"] is True


def test_persisted_execution_over_budget_is_rejected(tmp_path: Path) -> None:
    store = _store(tmp_path)
    execution = store.record_execution(
        "search",
        {"status": "ok", "evidence": [{"uri": "evidence://one"}]},
    )
    raw = json.loads(store.path.read_text(encoding="utf-8"))
    raw["executions"][0]["evidence"] = [
        {"uri": f"evidence://{index}"} for index in range(101)
    ]
    store.path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(InvestigationError, match="execution.evidence 元素过多"):
        store.load()

    raw["executions"][0]["evidence"] = [{"uri": "evidence://one"}]
    raw["executions"][0]["error"] = {"message": "x" * 4_097}
    raw["executions"][0]["recording"]["error_truncated"] = True
    store.path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(InvestigationError, match="execution.error.message 不能超过预算"):
        store.load()


def test_tool_boundary_returns_structured_error_when_recording_cannot_write(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "source.log"
    source.write_text("target\n", encoding="utf-8")

    def fail(*_args, **_kwargs):
        raise OSError("permission denied")

    monkeypatch.setattr(tools, "attach_investigation_result", fail)
    result = search(source, "target", investigation_path=tmp_path / "state.json")
    assert result["status"] == "error"
    assert result["error"]["type"] == "InvestigationError"
