from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tracecite import InvestigationStore, sample
from tracecite.integrations import cli
from tracecite_core.sample import sample_file


def _lines(path: Path, count: int = 7) -> None:
    path.write_text("".join(f"line-{index}\n" for index in range(1, count + 1)), encoding="utf-8")


def test_head_tail_is_deterministic_and_reports_sampling_coverage(tmp_path: Path) -> None:
    source = tmp_path / "events.log"
    _lines(source)

    first = sample_file(source, snapshot=False, strategy="head-tail", count=4, max_chars=200)
    second = sample_file(source, snapshot=False, strategy="head-tail", count=4, max_chars=200)

    assert [row["start_line"] for row in first.samples] == [1, 2, 6, 7]
    assert first.to_dict() == second.to_dict()
    coverage = first.to_dict()["coverage"]
    assert coverage["scan_records"] == 7
    assert coverage["scoped_records"] == 7
    assert coverage["selected_records"] == 4
    assert coverage["records_returned"] == 4
    assert coverage["selection_omitted_records"] == 3
    assert coverage["omissions"][0]["kind"] == "sampling"


def test_uniform_sampling_uses_stable_endpoints(tmp_path: Path) -> None:
    source = tmp_path / "events.log"
    _lines(source)

    result = sample_file(source, snapshot=False, strategy="uniform", count=4, max_chars=200)

    assert [row["start_line"] for row in result.samples] == [1, 3, 5, 7]
    assert result.strategy == "uniform"


def test_snapshot_runtime_returns_hash_addressed_line_pointers(tmp_path: Path) -> None:
    source = tmp_path / "events.log"
    _lines(source)

    result = sample(source, strategy="head-tail", count=2, max_chars=100)

    assert result["operation"] == "sample"
    assert result["status"] == "ok"
    assert result["outcome"] == "not_assessed"
    assert len(result["evidence"]) == 2
    pointer = result["evidence"][0]
    snapshot = Path(pointer["source_path"])
    digest = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    assert snapshot != source
    assert pointer["sha256"] == digest
    assert pointer["uri"].startswith(f"evidence://sha256/{digest}#L")


def test_no_snapshot_withholds_immutable_evidence(tmp_path: Path) -> None:
    source = tmp_path / "events.log"
    _lines(source)

    result = sample(source, snapshot=False, count=2, max_chars=100)

    assert result["evidence"] == []
    assert result["coverage"]["evidence_withheld"] is True
    assert result["missing_evidence"][0]["kind"] == "immutable_snapshot"
    assert any("snapshot=false" in warning for warning in result["warnings"])


def test_character_budget_and_every_omission_are_explicit(tmp_path: Path) -> None:
    source = tmp_path / "events.log"
    source.write_text("abcdefghij\nklmnop\n", encoding="utf-8")

    result = sample_file(source, snapshot=False, strategy="head-tail", count=2, max_chars=5)
    payload = result.to_dict()
    coverage = payload["coverage"]

    assert coverage["returned_chars"] == 5
    assert coverage["truncated_records"] == 1
    assert coverage["output_omitted_records"] == 1
    assert coverage["omitted_chars"] == 13
    assert {row["kind"] for row in coverage["omissions"]} >= {
        "max_chars",
        "record_text_truncation",
        "characters",
    }
    assert len(payload["data"]["samples"]) == 1
    assert len(payload["data"]["samples"][0]["text"]) <= 5
    assert "samples" not in payload  # do not duplicate bounded text in Core output


def test_time_scope_and_auto_segmenter_are_reported(tmp_path: Path) -> None:
    source = tmp_path / "events.jsonl"
    rows = [
        {"ts": "2026-08-12T10:00:00Z", "msg": "zero"},
        {"ts": "2026-08-12T10:01:00Z", "msg": "one"},
        {"ts": "2026-08-12T10:02:00Z", "msg": "two"},
        {"ts": "2026-08-12T10:03:00Z", "msg": "three"},
    ]
    source.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    result = sample_file(
        source,
        snapshot=False,
        strategy="uniform",
        count=10,
        max_chars=200,
        segmenter="auto",
        since="2026-08-12T10:01:00",
        until="2026-08-12T10:02:00",
    )

    assert result.segmenter == "jsonline"
    assert result.scoped_records == 2
    assert [row["start_line"] for row in result.samples] == [2, 3]
    assert result.to_dict()["coverage"]["scope"]["since"].startswith("2026-08-12T10:01")


def test_runtime_sample_links_bounded_execution_without_raw_data(tmp_path: Path) -> None:
    source = tmp_path / "events.log"
    _lines(source, count=3)
    store = InvestigationStore(tmp_path / "investigation.json")
    store.create("inspect raw context")
    store.add_hypothesis("raw context is informative", hypothesis_id="H1")
    store.add_test(
        "H1",
        "sample context",
        expected_observation="records are visible",
        contradicting_observation="records are absent",
        test_id="T1",
    )

    result = sample(
        source,
        snapshot=False,
        count=2,
        max_chars=50,
        investigation_path=store.path,
        hypothesis_id="H1",
        test_id="T1",
    )

    assert result["investigation"]["test_id"] == "T1"
    persisted = json.dumps(store.load().to_dict(), ensure_ascii=False)
    assert "line-1" not in persisted
    assert "data" not in store.load().executions[0]


def test_cli_routes_sample_and_peek_to_one_adapter(monkeypatch, capsys) -> None:
    calls: list[dict[str, object]] = []

    def fake_sample(*args, **kwargs):
        calls.append({"args": args, **kwargs})
        return {
            "schema_version": 1,
            "operation": "sample",
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

    monkeypatch.setattr(cli, "sample", fake_sample)
    assert cli.main(
        [
            "peek",
            "events.log",
            "--strategy",
            "uniform",
            "--count",
            "3",
            "--max-chars",
            "100",
            "--no-snapshot",
            "--last",
            "5m",
        ]
    ) == 0
    assert calls[0]["strategy"] == "uniform"
    assert calls[0]["count"] == 3
    assert calls[0]["max_chars"] == 100
    assert calls[0]["snapshot"] is False
    assert calls[0]["last"] == "5m"
    assert json.loads(capsys.readouterr().out)["operation"] == "sample"
