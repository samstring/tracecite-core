from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tracecite import survey
from tracecite.integrations import cli
from tracecite_core.survey import survey_file


def _write_jsonl(path: Path) -> None:
    rows = [
        {"ts": "2026-08-12T10:00:00Z", "level": "INFO", "msg": "worker id=1"},
        {"ts": "2026-08-12T10:01:00Z", "level": "INFO", "msg": "worker id=2"},
        {"ts": "2026-08-12T10:02:00Z", "level": "ERROR", "msg": "failed id=3"},
        {"ts": "2026-08-12T10:03:00Z", "level": "INFO", "msg": "worker id=4"},
    ]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_survey_streams_bounded_templates_and_freezes_evidence(tmp_path: Path) -> None:
    source = tmp_path / "events.jsonl"
    _write_jsonl(source)

    result = survey(source, max_templates=2, samples_per_template=1)

    assert result["operation"] == "survey"
    assert result["status"] == "ok"
    assert result["outcome"] == "not_assessed"
    assert result["coverage"]["records_scanned"] == 4
    assert result["coverage"]["timestamp_parse_coverage"] == 1.0
    assert len(result["data"]["top_templates"]) <= 2
    assert result["data"]["time_range"]["from"].startswith("2026-08-12T10:00")
    assert result["evidence"]

    pointer = result["evidence"][0]
    snapshot = Path(pointer["source_path"])
    assert ".snapshots" in str(snapshot)
    digest = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    assert pointer["sha256"] == digest
    assert pointer["uri"].startswith(f"evidence://sha256/{digest}#L")
    assert pointer["start_line"] >= 1


def test_survey_time_scope_and_no_snapshot_warning(tmp_path: Path) -> None:
    source = tmp_path / "events.jsonl"
    _write_jsonl(source)

    result = survey(
        source,
        snapshot=False,
        since="2026-08-12T10:02:00",
        until="2026-08-12T10:03:00",
        samples_per_template=1,
    )

    assert result["status"] == "ok"
    assert result["coverage"]["records_scoped"] == 2
    assert result["data"]["time_range"]["scoped_from"].startswith("2026-08-12T10:02")
    assert not result["evidence"]
    assert result["missing_evidence"]
    assert any("snapshot=false" in warning for warning in result["warnings"])


def test_core_survey_returns_summary_without_runtime_dependency(tmp_path: Path) -> None:
    source = tmp_path / "events.log"
    source.write_text("INFO worker id=1\nINFO worker id=2\n", encoding="utf-8")

    summary = survey_file(source, snapshot=True, segmenter="rawtext", max_templates=1)

    assert summary.scan_records == 2
    assert summary.scoped_records == 2
    assert summary.to_dict()["data"]["top_templates"][0]["count"] == 2


def test_survey_exposes_bounded_counter_error_instead_of_implying_exact_counts(
    tmp_path: Path,
) -> None:
    source = tmp_path / "high-cardinality.log"
    source.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")

    summary = survey_file(
        source,
        snapshot=False,
        segmenter="rawtext",
        max_templates=1,
        samples_per_template=0,
    ).to_dict()

    template = summary["data"]["top_templates"][0]
    assert template["approximate"] is True
    assert template["count"] == 3
    assert template["count_lower_bound"] == 1
    assert template["count_error"] == 2


def test_survey_cli_routes_budget_and_scope(monkeypatch, capsys) -> None:
    calls: dict[str, object] = {}

    def fake_survey(*args, **kwargs):
        calls["args"] = args
        calls.update(kwargs)
        return {
            "schema_version": 1,
            "operation": "survey",
            "status": "ok",
            "outcome": "not_assessed",
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

    monkeypatch.setattr(cli, "survey", fake_survey)
    assert cli.main(
        [
            "survey",
            "events.log",
            "--no-snapshot",
            "--segmenter",
            "rawtext",
            "--last",
            "5m",
            "--max-templates",
            "3",
            "--samples-per-template",
            "1",
        ]
    ) == 0

    assert calls["snapshot"] is False
    assert calls["segmenter"] == "rawtext"
    assert calls["last"] == "5m"
    assert calls["max_templates"] == 3
    assert calls["samples_per_template"] == 1
    assert json.loads(capsys.readouterr().out)["operation"] == "survey"
