from __future__ import annotations

from tracecite_core.segmenter import JsonLineSegmenter


def test_jsonline_timestamp_parsing_remains_enabled_by_default() -> None:
    segmenter = JsonLineSegmenter()
    assert segmenter._parse_timestamps is True
