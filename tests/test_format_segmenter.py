# -*- coding: utf-8 -*-
"""声明式格式分段器：任意文本格式一条 start 正则接入。"""

import warnings
from datetime import datetime

import pytest

from tracecite_core.segmenter import FormatSegmenter, JsonLineSegmenter, build_segmenter

CUSTOM_SAMPLE = """\
[2026-08-08 10:00:01.123] INFO  user-42 action=login
[2026-08-08 10:00:02.456] ERROR user-42 action=purchase amount=99
    stack line 1
    stack line 2
[2026-08-08 10:00:03.789] DEBUG svc-worker retry=1
"""

CUSTOM_FORMAT = {
    "start": (
        r"^\[(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+)\]"
        r"\s+(?P<level>\w+)\s+(?P<user>\S+)"
    ),
    "timestamp_formats": ["%Y-%m-%d %H:%M:%S.%f"],
    "multiline": True,
}


class TestFormatSegmenter:
    def test_custom_format_segments(self, tmp_path):
        path = tmp_path / "custom.log"
        path.write_text(CUSTOM_SAMPLE, encoding="utf-8")
        seg = build_segmenter(CUSTOM_FORMAT)
        records = list(seg.segment_file(path))
        assert len(records) == 3
        # 字段与时间戳提取
        r0 = records[0]
        assert r0.fields["level"] == "INFO"
        assert r0.fields["user"] == "user-42"
        assert r0.timestamp is not None
        assert r0.timestamp.strftime("%Y-%m-%d %H:%M:%S") == "2026-08-08 10:00:01"
        # 多行块：ERROR 记录并入 2 行 stack
        r1 = records[1]
        assert r1.fields["level"] == "ERROR"
        assert r1.text.count("stack line") == 2
        assert r1.end_line - r1.start_line + 1 == 3
        # 行号
        assert records[2].start_line == 5

    def test_build_by_name_format(self):
        seg = build_segmenter("format", **CUSTOM_FORMAT)
        assert isinstance(seg, FormatSegmenter)

    def test_unknown_kind_lists_available(self):
        with pytest.raises(ValueError, match="format"):
            build_segmenter("no-such-kind")

    def test_multiline_false_each_line_separate(self):
        seg = build_segmenter({**CUSTOM_FORMAT, "multiline": False})
        records = list(
            seg.segment_lines(
                (i + 1, line if line.endswith("\n") else line + "\n")
                for i, line in enumerate(CUSTOM_SAMPLE.splitlines())
            )
        )
        # 每行独立（含 stack 行）
        assert len(records) == len(CUSTOM_SAMPLE.splitlines())

    def test_ts_parse_failure_not_fatal(self):
        seg = build_segmenter(
            {"start": r"^(?P<ts>\S+)", "timestamp_formats": ["%Y-%m-%d"]}
        )
        records = list(
            seg.segment_lines([(1, "not-a-date\n"), (2, "other\n")])
        )
        assert records[0].timestamp is None
        assert records[1].timestamp is None


def test_jsonline_preserves_invalid_rows_as_evidence() -> None:
    segmenter = JsonLineSegmenter()
    records = list(
        segmenter.segment_lines(
            [
                (1, '{"message":"ok"}\n'),
                (2, "not-json\n"),
                (3, "[1, 2]\n"),
            ]
        )
    )

    assert len(records) == 3
    assert records[1].fields["raw_fallback"] is True
    assert records[2].fields["raw_fallback"] is True


def test_jsonline_honors_custom_level_and_message_fields() -> None:
    segmenter = JsonLineSegmenter(level_field="severity_name", msg_field="body")
    record = next(
        segmenter.segment_lines(
            [(1, '{"severity_name":"WARN","body":"custom"}\n')]
        )
    )

    assert record.fields == {"level": "WARN", "msg": "custom"}


def test_jsonline_parses_rfc3339_offsets_to_utc_naive() -> None:
    segmenter = JsonLineSegmenter()
    records = list(
        segmenter.segment_lines(
            [
                (1, '{"ts":"2026-08-19T10:00:00Z","msg":"z"}\n'),
                (2, '{"ts":"2026-08-19T10:00:00+08:00","msg":"offset"}\n'),
            ]
        )
    )

    assert records[0].timestamp == datetime(2026, 8, 19, 10, 0, 0)
    assert records[1].timestamp == datetime(2026, 8, 19, 2, 0, 0)
    assert records[0].timestamp.tzinfo is None
    assert records[1].timestamp.tzinfo is None


def test_jsonline_invalid_numeric_timestamps_keep_rows() -> None:
    segmenter = JsonLineSegmenter()
    records = list(
        segmenter.segment_lines(
            [
                (1, '{"ts":NaN,"msg":"nan"}\n'),
                (2, '{"ts":1e309,"msg":"inf"}\n'),
                (3, '{"ts":1e100,"msg":"overflow"}\n'),
                (4, '{"ts":"2026-08-19T10:00:00Z","msg":"ok"}\n'),
                (5, '{"ts":"' + ("x" * 1_000) + '","msg":"bounded"}\n'),
            ]
        )
    )

    assert len(records) == 5
    assert all(record.timestamp is None for record in records[:3])
    assert all(record.fields.get("timestamp_parse_error") for record in records[:3])
    assert records[3].timestamp == datetime(2026, 8, 19, 10, 0, 0)
    assert records[4].timestamp is None
    assert len(records[4].fields["timestamp_parse_error"]) <= 200


def test_yearless_timestamp_does_not_emit_deprecation_warning() -> None:
    segmenter = FormatSegmenter(
        start=r"^(?P<ts>[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})",
        timestamp_formats=["%b %d %H:%M:%S"],
    )
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        record = next(
            segmenter.segment_lines([(1, "Aug  8 14:10:00 message\n")])
        )

    # Core keeps the historical yearless value.  A format/application layer
    # may resolve it against a reference timestamp later.
    assert record.timestamp == datetime(1900, 8, 8, 14, 10, 0)
