from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tracecite.runtime.candidate_filter import (
    CandidateFilterUnsupported,
    filter_literal_single_line,
)
from tracecite_core.segmenter import JsonLineSegmenter, RawTextSegmenter
from tracecite_core.text_filter import filter_text, strip_filter_header


def _lines(path: Path | None):
    if path is None or not path.exists():
        return None
    return path.read_text(encoding="utf-8").splitlines()


def _assert_parity(legacy, fast) -> None:
    assert fast.total_lines == legacy.total_lines
    assert fast.match_records == legacy.match_records
    assert fast.match_lines == legacy.match_lines
    assert fast.engine == legacy.engine
    assert fast.unmatched_summary == legacy.unmatched_summary
    assert fast.term_usage == legacy.term_usage
    assert fast.pattern_components == legacy.pattern_components
    assert fast.matched_by_counts == legacy.matched_by_counts
    assert fast.matched_by_fallback == legacy.matched_by_fallback
    assert fast.lines_truncated == legacy.lines_truncated
    assert _lines(fast.records_path) == _lines(legacy.records_path)
    assert _lines(fast.hits_path) == _lines(legacy.hits_path)
    assert strip_filter_header(fast.output_path.read_text(encoding="utf-8")) == strip_filter_header(
        legacy.output_path.read_text(encoding="utf-8")
    )


def test_jsonl_fast_filter_matches_legacy_including_unmatched_summary(tmp_path: Path) -> None:
    source = tmp_path / "events.jsonl"
    source.write_text(
        '{"timestamp":"2026-09-03T12:00:00Z","service":"route","status":200}\n'
        '\n'
        '{"timestamp":"2026-09-03T12:00:01Z","service":"route","status":503}\n'
        '{"service":"seat","message":"retry timeout"}\n'
        '{bad json with status 503}\n',
        encoding="utf-8",
    )
    pattern = re.escape("503")
    segmenter = JsonLineSegmenter()
    legacy = filter_text(
        source,
        pattern=pattern,
        output_path=tmp_path / "legacy" / "evidence.log",
        snapshot=False,
        segmenter=segmenter,
        template_threshold=0,
    )
    fast = filter_literal_single_line(
        source,
        pattern=pattern,
        output_path=tmp_path / "fast" / "evidence.log",
        snapshot=False,
        segmenter=JsonLineSegmenter(),
        template_threshold=0,
    )

    _assert_parity(legacy, fast)
    assert fast.original_total_lines_at_run == legacy.original_total_lines_at_run == 5
    assert fast.match_records == 2
    rows = [json.loads(line) for line in fast.records_path.read_text().splitlines()]
    assert rows[0]["metadata"]["start_line"] == 3
    assert rows[0]["metadata"]["timestamp"] == "2026-09-03T12:00:01.000"
    assert rows[1]["metadata"]["start_line"] == 5


def test_raw_line_fast_filter_matches_legacy(tmp_path: Path) -> None:
    source = tmp_path / "plain.log"
    source.write_text(
        "alpha request=one\n"
        "needle request=two\n"
        "beta request=three\n"
        "needle request=four\n",
        encoding="utf-8",
    )
    pattern = re.escape("needle")
    legacy = filter_text(
        source,
        pattern=pattern,
        output_path=tmp_path / "legacy" / "evidence.log",
        snapshot=False,
        segmenter=RawTextSegmenter(mode="line"),
        template_threshold=0,
        max_line_chars=12,
    )
    fast = filter_literal_single_line(
        source,
        pattern=pattern,
        output_path=tmp_path / "fast" / "evidence.log",
        snapshot=False,
        segmenter=RawTextSegmenter(mode="line"),
        template_threshold=0,
        max_line_chars=12,
    )

    _assert_parity(legacy, fast)


def test_snapshot_fast_filter_preserves_snapshot_boundary(tmp_path: Path) -> None:
    source = tmp_path / "events.jsonl"
    source.write_text('{"message":"needle"}\n{"message":"other"}\n', encoding="utf-8")
    pattern = re.escape("needle")
    fast = filter_literal_single_line(
        source,
        pattern=pattern,
        output_path=tmp_path / "fast" / "evidence.log",
        snapshot=True,
        segmenter=JsonLineSegmenter(),
    )

    assert fast.snapshot_path is not None
    assert fast.snapshot_path.read_bytes() == source.read_bytes()
    assert fast.snapshot_lines == 2
    assert fast.original_total_lines_at_run == 2
    assert fast.work_input == fast.snapshot_path


def test_fast_filter_rejects_semantics_not_yet_covered(tmp_path: Path) -> None:
    source = tmp_path / "plain.log"
    source.write_text("needle\n", encoding="utf-8")

    with pytest.raises(CandidateFilterUnsupported):
        filter_literal_single_line(
            source,
            pattern="need.*",
            segmenter=RawTextSegmenter(mode="line"),
        )
    with pytest.raises(CandidateFilterUnsupported):
        filter_literal_single_line(
            source,
            pattern=re.escape("needle"),
            segmenter=RawTextSegmenter(mode="line"),
            since="12:00",
        )
    with pytest.raises(CandidateFilterUnsupported):
        filter_literal_single_line(
            source,
            pattern=re.escape("needle"),
            segmenter=RawTextSegmenter(mode="line"),
            template_threshold=10,
        )
