# -*- coding: utf-8 -*-
"""声明式格式分段器：任意文本格式一条 start 正则接入。"""

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
