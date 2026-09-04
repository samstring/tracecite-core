from __future__ import annotations

from pathlib import Path

import pytest

from tracecite.runtime.candidate_search import (
    LocalRecoveryUnsupported,
    candidate_first_literal_search,
    recover_record,
    scan_literal,
)
from tracecite_core.segmenter import FormatSegmenter, JsonLineSegmenter, RawTextSegmenter


def _legacy_matches(path: Path, segmenter, query: str):
    return [record for record in segmenter.segment_file(path) if query in record.text]


def _ranges(records):
    return [(record.start_line, record.end_line) for record in records]


def test_jsonl_candidate_first_matches_full_segmentation(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text(
        '{"service":"api","status":200}\n'
        '{"service":"route","status":503}\n'
        '{"service":"route","status":200}\n'
        '{"service":"route","status":503}\n',
        encoding="utf-8",
    )
    segmenter = JsonLineSegmenter()
    legacy = _legacy_matches(path, segmenter, "503")
    fast = candidate_first_literal_search(
        path, "503", segmenter=segmenter, max_evidence=20
    )

    assert fast.match_records == len(legacy) == 2
    assert fast.match_lines == 2
    assert fast.physical_hit_lines == 2
    assert fast.total_lines == 4
    assert _ranges(fast.records) == _ranges(legacy)
    assert [record.text for record in fast.records] == [record.text for record in legacy]


def test_raw_line_candidate_first_bounds_evidence_without_losing_count(tmp_path: Path) -> None:
    path = tmp_path / "plain.log"
    path.write_text("hit one\nmiss\nhit two\nhit three\n", encoding="utf-8")
    fast = candidate_first_literal_search(
        path,
        "hit",
        segmenter=RawTextSegmenter(mode="line"),
        max_evidence=2,
    )

    assert fast.match_records == 3
    assert fast.match_lines == 3
    assert fast.physical_hit_lines == 3
    assert _ranges(fast.records) == [(1, 1), (3, 3)]


def test_no_match_still_reports_exact_scan_coverage(tmp_path: Path) -> None:
    path = tmp_path / "plain.log"
    path.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    fast = candidate_first_literal_search(
        path,
        "missing",
        segmenter=RawTextSegmenter(mode="line"),
    )

    assert fast.status == "no_match"
    assert fast.match_records == 0
    assert fast.match_lines == 0
    assert fast.physical_hit_lines == 0
    assert fast.total_lines == 3
    assert fast.records == []


def test_format_local_recovery_restores_complete_multiline_record(tmp_path: Path) -> None:
    path = tmp_path / "app.log"
    path.write_text(
        "2026-09-03 12:00:00 ERROR request failed\n"
        "java.lang.NullPointerException\n"
        "    at Foo.java:123\n"
        "caused by timeout\n"
        "2026-09-03 12:00:01 INFO request ok\n"
        "done\n",
        encoding="utf-8",
    )
    segmenter = FormatSegmenter(
        start=r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})",
        timestamp_formats=["%Y-%m-%d %H:%M:%S"],
        multiline=True,
    )
    legacy = _legacy_matches(path, segmenter, "timeout")
    hits, hit_count, total_lines = scan_literal(path, "timeout")
    assert hit_count == 1
    assert total_lines == 6

    local = recover_record(path, hits[0], segmenter)
    assert len(legacy) == 1
    assert (local.start_line, local.end_line, local.text) == (
        legacy[0].start_line,
        legacy[0].end_line,
        legacy[0].text,
    )
    assert (local.start_line, local.end_line) == (1, 4)


def test_format_multiple_hit_lines_are_deduped_to_one_record(tmp_path: Path) -> None:
    path = tmp_path / "app.log"
    path.write_text(
        "2026-09-03 12:00:00 ERROR timeout\n"
        "timeout in retry\n"
        "timeout again\n"
        "2026-09-03 12:00:01 INFO ok\n",
        encoding="utf-8",
    )
    segmenter = FormatSegmenter(
        start=r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})",
        timestamp_formats=["%Y-%m-%d %H:%M:%S"],
        multiline=True,
    )
    fast = candidate_first_literal_search(path, "timeout", segmenter=segmenter)

    assert fast.physical_hit_lines == 3
    assert fast.match_records == 1
    assert fast.match_lines == 3
    assert _ranges(fast.records) == [(1, 3)]


def test_format_local_recovery_expands_backward_window(tmp_path: Path) -> None:
    path = tmp_path / "large-record.log"
    filler = "x" * 1024 + "\n"
    path.write_text(
        "2026-09-03 12:00:00 ERROR start\n"
        + filler * 80
        + "needle near the end\n"
        + "2026-09-03 12:00:01 INFO next\n",
        encoding="utf-8",
    )
    segmenter = FormatSegmenter(
        start=r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})",
        timestamp_formats=["%Y-%m-%d %H:%M:%S"],
        multiline=True,
    )
    legacy = _legacy_matches(path, segmenter, "needle")
    fast = candidate_first_literal_search(path, "needle", segmenter=segmenter)

    assert len(legacy) == 1
    assert _ranges(fast.records) == _ranges(legacy)
    assert fast.records[0].text == legacy[0].text


def test_continuation_segmenter_requires_legacy_fallback(tmp_path: Path) -> None:
    path = tmp_path / "continued.log"
    path.write_text(
        "2026-09-03 12:00:00 {\n"
        "needle\n"
        "2026-09-03 12:00:01 }\n",
        encoding="utf-8",
    )
    segmenter = FormatSegmenter(
        start=r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})",
        timestamp_formats=["%Y-%m-%d %H:%M:%S"],
        multiline=True,
        continuation={"kind": "unclosed_start", "max_lines": 100},
    )

    with pytest.raises(LocalRecoveryUnsupported):
        candidate_first_literal_search(path, "needle", segmenter=segmenter)
