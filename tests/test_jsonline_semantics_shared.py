from __future__ import annotations

import json
from datetime import datetime

from tracecite_core.jsonline_semantics import extract_jsonline_semantics
from tracecite_core.segmenter import JsonLineSegmenter


def test_extracted_semantics_match_jsonline_segmenter_records() -> None:
    rows = [
        {"timestamp": "2026-09-05T10:00:00Z", "level": "WARN", "message": "hello"},
        {"ts": 1725530400000, "severity": "ERROR", "content": "world"},
        {"time": True, "lvl": "INFO", "text": "bad timestamp"},
        {"eventTime": [1, 2, 3]},
        {"service": "route"},
    ]
    segmenter = JsonLineSegmenter()

    records = list(
        segmenter.segment_lines(
            iter(
                (index, json.dumps(row, separators=(",", ":")) + "\n")
                for index, row in enumerate(rows, start=1)
            )
        )
    )

    assert len(records) == len(rows)
    for row, record in zip(rows, records):
        semantics = extract_jsonline_semantics(row)
        assert semantics.timestamp == record.timestamp
        assert semantics.fields == record.fields


def test_custom_jsonline_aliases_share_the_same_semantics() -> None:
    row = {
        "created_at": "2026-09-05T10:00:00+08:00",
        "priority": "high",
        "body": "payload",
    }
    segmenter = JsonLineSegmenter(
        time_field="created_at",
        level_field="priority",
        msg_field="body",
    )
    record = next(
        segmenter.segment_lines(
            iter([(1, json.dumps(row, separators=(",", ":")) + "\n")])
        )
    )
    semantics = extract_jsonline_semantics(
        row,
        time_field="created_at",
        level_field="priority",
        msg_field="body",
    )

    assert semantics.timestamp == datetime(2026, 9, 5, 2, 0, 0)
    assert semantics.timestamp == record.timestamp
    assert semantics.fields == record.fields == {"level": "high", "msg": "payload"}
