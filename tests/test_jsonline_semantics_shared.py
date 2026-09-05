from __future__ import annotations

import json
from datetime import datetime

import tracecite_core.jsonline_semantics as jsonline_semantics
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


def test_repeated_scalar_timestamp_values_use_bounded_parse_cache(monkeypatch) -> None:
    jsonline_semantics._parse_scalar_timestamp.cache_clear()
    real_parse = jsonline_semantics._parse_timestamp
    calls = 0

    def counted_parse(value):
        nonlocal calls
        calls += 1
        return real_parse(value)

    monkeypatch.setattr(jsonline_semantics, "_parse_timestamp", counted_parse)

    for message in ("first", "second", "third"):
        semantics = extract_jsonline_semantics({"time": "16:04", "msg": message})
        assert semantics.timestamp is None
        assert semantics.fields["msg"] == message

    assert calls == 1


def test_timestamp_parse_cache_keeps_bool_and_number_semantics_distinct() -> None:
    jsonline_semantics._parse_scalar_timestamp.cache_clear()

    boolean = extract_jsonline_semantics({"time": True})
    number = extract_jsonline_semantics({"time": 1})

    assert boolean.timestamp is None
    assert "布尔值" in boolean.fields["timestamp_parse_error"]
    assert number.timestamp is not None
