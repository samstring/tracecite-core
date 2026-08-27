from __future__ import annotations

import json
from pathlib import Path

from tracecite_core import (
    AnalysisEvent,
    AnalysisRun,
    EventRef,
    events_from_filter_result,
    write_events_jsonl,
)
from tracecite_core import build_segmenter
from tracecite_core.text_filter import filter_text


def test_event_serialization_keeps_reference_but_omits_raw_text(tmp_path: Path) -> None:
    event = AnalysisEvent(
        timestamp="2026-08-09 10:00:00.123",
        category="network",
        name="request_failed",
        source="filter",
        attributes={"status": 500},
        raw_ref=EventRef(str(tmp_path / "app.log"), 12, 14),
        text="very long raw log",
    )
    payload = event.to_dict()
    assert payload["event_id"]
    assert payload["raw_ref"]["start_line"] == 12
    assert "text" not in payload

    path = write_events_jsonl(tmp_path / "events.jsonl", [event])
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored == payload


def test_analysis_run_manifest_hashes_inputs_and_artifacts(tmp_path: Path) -> None:
    source = tmp_path / "source.log"
    artifact = tmp_path / "filtered.log"
    source.write_text("source\n", encoding="utf-8")
    artifact.write_text("evidence\n", encoding="utf-8")

    run = AnalysisRun(name="unit", platform="ios")
    run.add_input(source)
    run.add_artifact(artifact, role="filtered_log")
    running_manifest = run.write_manifest(tmp_path / "runs")
    assert json.loads(running_manifest.read_text(encoding="utf-8"))["status"] == "running"

    run.finish(status="succeeded", metrics={"match_records": 1})
    manifest = run.write_manifest(tmp_path / "runs")
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["status"] == "succeeded"
    assert payload["metrics"]["match_records"] == 1
    assert len(payload["inputs"][0]["sha256"]) == 64
    assert len(payload["artifacts"][0]["sha256"]) == 64


def test_analysis_run_hashes_directory_artifacts(tmp_path: Path) -> None:
    trace = tmp_path / "capture.trace"
    trace.mkdir()
    (trace / "data.bin").write_bytes(b"trace-data")

    run = AnalysisRun(name="capture", kind="device_collection", platform="ios")
    run.add_artifact(trace, role="performance_trace")
    run.finish(status="completed", verdict="passed")
    manifest = run.write_manifest(tmp_path / "runs")
    payload = json.loads(manifest.read_text(encoding="utf-8"))

    artifact = payload["artifacts"][0]
    assert artifact["metadata"]["path_type"] == "directory"
    assert artifact["size"] == len(b"trace-data")
    assert len(artifact["sha256"]) == 64


def test_filter_events_preserve_millisecond_timestamp(tmp_path: Path) -> None:
    source = tmp_path / "app.log"
    source.write_text(
        "2026-08-09 10:00:00.123 I Test : target\n",
        encoding="utf-8",
    )
    result = filter_text(
        source,
        pattern="target",
        output_path=tmp_path / "out.log",
        segmenter=build_segmenter({
            "start": r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+)",
            "timestamp_formats": ["%Y-%m-%d %H:%M:%S.%f"],
        }),
    )
    assert events_from_filter_result(result)[0].timestamp == "2026-08-09T10:00:00.123"


def test_filter_events_reference_frozen_snapshot(tmp_path: Path) -> None:
    source = tmp_path / "live.log"
    source.write_text("target\n", encoding="utf-8")
    result = filter_text(
        source,
        pattern="target",
        output_path=tmp_path / "out.log",
        snapshot=True,
    )

    event = events_from_filter_result(result)[0]
    assert result.snapshot_path is not None
    assert event.raw_ref is not None
    assert event.raw_ref.source_path == str(result.snapshot_path)
    assert event.attributes["original_source"] == str(source)
