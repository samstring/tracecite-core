from __future__ import annotations

import json
from pathlib import Path

from tracecite.integrations import cli


def _write_log(path: Path) -> None:
    rows = [
        "2026-08-12T10:00:00 INFO worker id=1 started",
        "2026-08-12T10:01:00 INFO worker id=2 started",
        "2026-08-12T10:02:00 ERROR worker id=3 failed badly",
        "2026-08-12T10:03:00 INFO worker id=4 started",
    ]
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def test_survey_brief_removes_sample_text_and_marks_data(tmp_path: Path, capsys) -> None:
    source = tmp_path / "events.log"
    _write_log(source)

    assert cli.main(["survey", str(source), "--brief", "--no-snapshot", "--max-templates", "2"]) == 0
    result = json.loads(capsys.readouterr().out.strip())

    assert result["data"]["brief"] is True
    assert "work_input" not in result["data"]
    for template in result["data"]["top_templates"]:
        for sample in template.get("samples") or []:
            assert "text" not in sample
    for item in result["evidence"]:
        assert "text" not in (item.get("metadata") or {})


def test_survey_cli_brief_emits_minified_json(tmp_path: Path, capsys) -> None:
    source = tmp_path / "events.log"
    _write_log(source)

    assert cli.main(["survey", str(source), "--brief", "--no-snapshot"]) == 0
    rendered = capsys.readouterr().out.strip()
    payload = json.loads(rendered)

    assert payload["data"]["brief"] is True
    assert "\n  " not in rendered
