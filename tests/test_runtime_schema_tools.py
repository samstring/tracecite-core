from __future__ import annotations

import hashlib
from pathlib import Path

from tracecite.runtime import tools
from tracecite.runtime.schema import RESULT_SCHEMA_VERSION, AgentResult, ScenarioDocument
from tracecite.runtime.tools import expand, probe, run, search, verify


def _scenario(source: Path, run_dir: Path) -> dict:
    return {
        "schema_version": 2,
        "name": "generic-agent-test",
        "source": {"type": "file", "path": str(source)},
        "parse": {"segmenter": "rawtext"},
        "filter": {"grep": "target"},
        "assert": {
            "rules": [
                {
                    "name": "has-target",
                    "type": "count",
                    "event": {"match": "target"},
                    "min": 1,
                }
            ]
        },
        "output": {"run_dir": str(run_dir)},
    }


def test_result_schema_rejects_unknown_status() -> None:
    try:
        AgentResult(operation="test", status="unknown")
    except ValueError as exc:
        assert "status" in str(exc)
    else:
        raise AssertionError("unknown result status must fail")


def test_result_schema_separates_execution_from_epistemic_outcome() -> None:
    payload = AgentResult(
        operation="test",
        status="ok",
        outcome="unknown",
        missing_evidence=[{"kind": "coverage", "detail": "device logs absent"}],
    ).to_dict()

    assert payload["status"] == "ok"
    assert payload["outcome"] == "unknown"
    assert payload["missing_evidence"][0]["kind"] == "coverage"


def test_scenario_document_is_versioned_and_strict(tmp_path: Path) -> None:
    source = tmp_path / "source.log"
    source.write_text("target\n", encoding="utf-8")
    document = ScenarioDocument.from_dict(_scenario(source, tmp_path / "runs"))

    assert document.to_dict()["schema_version"] == 2


def test_probe_search_expand_and_verify(tmp_path: Path) -> None:
    source = tmp_path / "source.log"
    source.write_text("alpha\ntarget value\nomega\n", encoding="utf-8")

    inspected = probe(source)
    assert inspected["schema_version"] == RESULT_SCHEMA_VERSION
    assert inspected["status"] == "ok"
    assert inspected["data"]["source_count"] == 1

    found = search(source, "target", output_path=tmp_path / "evidence.log")
    assert found["status"] == "ok"
    assert found["outcome"] == "not_assessed"
    assert found["coverage"]["match_records"] == 1
    pointer = found["evidence"][0]
    assert pointer["uri"].startswith("evidence://sha256/")
    assert ".snapshots" in pointer["source_path"]

    context = expand(
        pointer["source_path"],
        pointer["start_line"],
        end_line=pointer["end_line"],
        expected_sha256=pointer["sha256"],
        before=1,
        after=1,
    )
    assert context["status"] == "ok"
    assert context["outcome"] == "not_assessed"
    assert "target value" in context["data"]["text"]

    scenario_result = run(_scenario(source, tmp_path / "runs"), base_dir=tmp_path)
    assert scenario_result["status"] == "ok"
    assert scenario_result["verdict"] == "passed"
    assert scenario_result["outcome"] == "supported"
    assert scenario_result["hypotheses"][0]["outcome"] == "supported"
    assert scenario_result["evidence"][0]["uri"].startswith("evidence://sha256/")
    assert scenario_result["coverage"]["evidence_truncated"] is False
    checked = verify(scenario_result["data"]["manifest_path"])
    assert checked["status"] == "ok"


def test_no_match_is_a_successful_structured_branch(tmp_path: Path) -> None:
    source = tmp_path / "source.log"
    source.write_text("alpha\n", encoding="utf-8")

    result = search(source, "missing", output_path=tmp_path / "none.log")

    assert result["status"] == "no_match"
    assert result["outcome"] == "unknown"
    assert "error" not in result
    assert result["warnings"]
    assert result["missing_evidence"]


def test_run_without_assertions_does_not_claim_support(tmp_path: Path) -> None:
    source = tmp_path / "source.log"
    source.write_text("target\n", encoding="utf-8")
    spec = _scenario(source, tmp_path / "runs")
    spec.pop("assert")

    result = run(spec, base_dir=tmp_path)

    assert result["status"] == "ok"
    assert result["outcome"] == "not_assessed"
    assert result["warnings"]
    assert result["missing_evidence"]


def test_default_runtime_blocks_command_capabilities(tmp_path: Path) -> None:
    spec = {
        "schema_version": 2,
        "name": "unsafe",
        "source": {"type": "command", "cmd": ["echo", "target"]},
        "filter": {"grep": "target"},
    }

    result = run(spec, base_dir=tmp_path)

    assert result["status"] == "error"
    assert "未授权" in result["error"]["message"]


def test_search_bounds_inline_evidence_but_preserves_full_artifact(tmp_path: Path) -> None:
    source = tmp_path / "many.log"
    source.write_text("".join(f"target {index}\n" for index in range(105)), encoding="utf-8")

    result = search(
        source,
        "target",
        output_path=tmp_path / "evidence.log",
        max_evidence=1_000,
    )

    assert result["coverage"]["match_records"] == 105
    assert result["coverage"]["evidence_returned"] == 100
    assert result["coverage"]["evidence_truncated"] is True
    assert len(result["evidence"]) == 100


def test_expand_hashes_and_reads_through_one_stable_descriptor(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "source.log"
    source.write_text("old\n", encoding="utf-8")
    expected = hashlib.sha256(source.read_bytes()).hexdigest()
    original_sha256 = tools._sha256

    def mutate_after_separate_hash(path: Path) -> str:
        digest = original_sha256(path)
        source.write_text("new\n", encoding="utf-8")
        return digest

    monkeypatch.setattr(tools, "_sha256", mutate_after_separate_hash)

    result = expand(source, 1, expected_sha256=expected, before=0, after=0)

    assert result["status"] == "ok"
    assert result["outcome"] == "not_assessed"
    assert result["data"]["text"] == "1: old\n"
    assert result["evidence"][0]["sha256"] == expected


def test_expand_rejects_out_of_range_citation(tmp_path: Path) -> None:
    source = tmp_path / "short.log"
    source.write_text("one line\n", encoding="utf-8")

    result = expand(source, 2)

    assert result["status"] == "error"
    assert result["outcome"] == "unknown"
    assert "超出" in result["error"]["message"]
