from __future__ import annotations

import dataclasses
import json
import subprocess
import sys
from pathlib import Path

from tracecite.runtime import schema_compat


ROOT = Path(__file__).parents[1]


def _spec(schema_id: str):
    return next(item for item in schema_compat.registry() if item.schema_id == schema_id)


def test_registry_is_explicit_and_fixture_readers_are_clean() -> None:
    report = schema_compat.compatibility_report(ROOT)

    assert report["ok"] is True
    assert report["findings"] == []
    ids = [item["schema_id"] for item in report["schemas"]]
    assert len(ids) == len(set(ids))
    assert "tracecite.filter.records_artifact" in ids
    assert "tracecite.knowledge_governance" in ids


def test_report_is_deterministic_machine_readable() -> None:
    first = schema_compat.compatibility_report(ROOT)
    second = schema_compat.compatibility_report(ROOT)

    assert json.dumps(first, ensure_ascii=False, sort_keys=True) == json.dumps(
        second, ensure_ascii=False, sort_keys=True
    )
    assert json.loads(json.dumps(first)) == first


def test_checker_reports_missing_fixture_and_fixture_version_drift(tmp_path: Path) -> None:
    original = _spec("tracecite.agent_result")
    missing = dataclasses.replace(
        original,
        fixtures=(("tests/fixtures/schema_compat/not-present.json", 1),),
    )
    findings = schema_compat.check_registry(ROOT, specs=(missing,))
    assert any("fixture missing" in finding for finding in findings)

    wrong_fixture = tmp_path / "wrong-version.json"
    wrong_fixture.write_text('{"schema_version": 7}\n', encoding="utf-8")
    wrong = dataclasses.replace(
        original,
        fixtures=((str(wrong_fixture), 1),),
    )
    findings = schema_compat.check_registry(ROOT, specs=(wrong,))
    assert any("fixture version 7 != declared 1" in finding for finding in findings)


def test_checker_reports_source_drift_and_missing_legacy_handler() -> None:
    original = _spec("tracecite.agent_result")
    drifted = dataclasses.replace(original, current_version=99)
    findings = schema_compat.check_registry(ROOT, specs=(drifted,))
    assert any("registry version 99 != source 1" in finding for finding in findings)

    knowledge = _spec("tracecite.knowledge_governance")
    no_handler = dataclasses.replace(knowledge, migration_handler="")
    findings = schema_compat.check_registry(ROOT, specs=(no_handler,))
    assert any("legacy versions require migration_handler" in finding for finding in findings)


def test_checker_rejects_version_fields_for_unversioned_additive_artifact() -> None:
    original = _spec("tracecite.filter.records_artifact")
    invalid = dataclasses.replace(original, current_version=1)

    findings = schema_compat.check_registry(ROOT, specs=(invalid,))

    assert any("unversioned additive schema cannot declare versions" in finding for finding in findings)


def test_checker_rejects_source_path_escape(tmp_path: Path) -> None:
    original = _spec("tracecite.agent_result")
    escaped = dataclasses.replace(original, source_path="../outside.py")

    findings = schema_compat.check_registry(tmp_path, specs=(escaped,))

    assert any("source path escapes repository root" in finding for finding in findings)


def test_cli_emits_json_and_returns_success() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/check_schema_compat.py", "--root", str(ROOT)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["ok"] is True
    assert report["findings"] == []
