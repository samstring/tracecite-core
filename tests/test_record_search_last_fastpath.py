from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path

from tracecite_core.record_search import _last_timestamp, iter_matching_records
from tracecite_core.segmenter import JsonLineSegmenter


def _jsonl(tmp_path: Path, rows: list[dict | str]) -> Path:
    path = tmp_path / "events.jsonl"
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            if isinstance(row, str):
                handle.write(row + "\n")
            else:
                handle.write(json.dumps(row, separators=(",", ":")) + "\n")
    return path


def test_jsonl_last_timestamp_reads_from_tail_without_forward_segment_file(
    tmp_path: Path, monkeypatch
) -> None:
    path = _jsonl(
        tmp_path,
        [
            {"timestamp": "2026-09-05T10:00:00Z", "value": 1},
            {"timestamp": "2026-09-05T10:05:00Z", "value": 2},
            {"value": 3},
            "not-json",
        ],
    )
    segmenter = JsonLineSegmenter()

    def forbidden_forward_scan(*args, **kwargs):
        raise AssertionError("last timestamp lookup must not call segment_file for JSONL")

    monkeypatch.setattr(segmenter, "segment_file", forbidden_forward_scan)
    result = _last_timestamp(
        path,
        segmenter=segmenter,
        reference=datetime(2026, 9, 5, 10, 0, 0),
        encoding="utf-8",
    )

    assert result == datetime(2026, 9, 5, 10, 5, 0)


def test_jsonl_last_scope_keeps_canonical_file_order_semantics(tmp_path: Path) -> None:
    path = _jsonl(
        tmp_path,
        [
            {"timestamp": "2026-09-05T10:00:00Z", "value": "early"},
            {"timestamp": "2026-09-05T10:09:30Z", "value": "keep-a"},
            # Deliberately out of timestamp order. --last is anchored to the
            # last parseable Record in file order, not to max(timestamp).
            {"timestamp": "2026-09-05T10:20:00Z", "value": "out-of-order"},
            {"timestamp": "2026-09-05T10:10:00Z", "value": "keep-b"},
            {"value": "untimestamped-kept-by-canonical-semantics"},
        ],
    )

    rows = list(
        iter_matching_records(
            path,
            query=None,
            segmenter=JsonLineSegmenter(),
            last="1m",
        )
    )
    values = [json.loads(row.text)["value"] for row in rows]

    # Canonical time filtering keeps records whose timestamp cannot be parsed,
    # and anchors the last window to the final parseable Record (10:10), so the
    # earlier 10:20 record is outside the upper bound rather than becoming the
    # anchor itself.
    assert values == ["keep-a", "keep-b", "untimestamped-kept-by-canonical-semantics"]
