# -*- coding: utf-8 -*-
"""filter 时间定界：--last / --since / --until。"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from tracecite_core.text_filter import (
    FilterError,
    filter_text,
    parse_last_duration,
    parse_time_arg,
    pattern_from_terms,
)
from tracecite_core.segmenter import FormatSegmenter, RawTextSegmenter


SAMPLE_LOG = """\
2026-07-25 18:41:50 I Early: before window
2026-07-25 18:42:10 I Action: click home
2026-07-25 18:42:30 I Action: enter room
2026-07-25 18:42:50 I Action: exit room
2026-07-25 18:43:10 I Late: after window
"""


def _segmenter() -> FormatSegmenter:
    return FormatSegmenter(
        start=r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})",
        timestamp_formats=["%Y-%m-%d %H:%M:%S"],
    )


class RelativeTimeSegmenter(RawTextSegmenter):
    def parse_time_argument(self, raw: str, *, reference: datetime):
        if raw == "next-minute":
            return reference.replace(minute=reference.minute + 1, second=0)
        return None


class LogFilterTimeScopeTest(unittest.TestCase):
    def test_parse_last_duration(self) -> None:
        self.assertEqual(parse_last_duration("60s").total_seconds(), 60)
        self.assertEqual(parse_last_duration("1m").total_seconds(), 60)
        self.assertEqual(parse_last_duration("5m").total_seconds(), 300)
        self.assertEqual(parse_last_duration("1h").total_seconds(), 3600)
        self.assertEqual(parse_last_duration("90").total_seconds(), 90)
        with self.assertRaises(FilterError):
            parse_last_duration("abc")

    def test_parse_time_arg_clock(self) -> None:
        ref = datetime(2026, 7, 25, 19, 0, 0)
        self.assertEqual(
            parse_time_arg("18:42:00", ref=ref),
            datetime(2026, 7, 25, 18, 42, 0),
        )
        self.assertEqual(
            parse_time_arg("2026-07-25T18:42:30", ref=ref),
            datetime(2026, 7, 25, 18, 42, 30),
        )

    def test_last_one_minute_keeps_recent_actions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "sample.log"
            src.write_text(SAMPLE_LOG, encoding="utf-8")
            # 末条 18:43:10，--last 40s => [18:42:30, 18:43:10]
            result = filter_text(
                src,
                pattern=r"Action:",
                tag="last40s",
                last="40s",
                segmenter=_segmenter(),
            )
            body = result.output_path.read_text(encoding="utf-8").split("# ---\n", 1)[1]
            self.assertIn("enter room", body)
            self.assertIn("exit room", body)
            self.assertNotIn("click home", body)
            self.assertNotIn("before window", body)
            self.assertNotIn("after window", body)
            self.assertEqual(result.match_records, 2)
            self.assertIsNotNone(result.time_from)
            self.assertIsNotNone(result.time_to)
            self.assertIn("last=40s", result.scope or "")

    def test_since_until_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "sample.log"
            src.write_text(SAMPLE_LOG, encoding="utf-8")
            result = filter_text(
                src,
                pattern=r"Action:",
                tag="range",
                since="18:42:00",
                until="18:42:40",
                segmenter=_segmenter(),
            )
            body = result.output_path.read_text(encoding="utf-8").split("# ---\n", 1)[1]
            self.assertIn("click home", body)
            self.assertIn("enter room", body)
            self.assertNotIn("exit room", body)
            self.assertEqual(result.match_records, 2)

    def test_zero_match_returns_empty_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "sample.log"
            src.write_text(SAMPLE_LOG, encoding="utf-8")
            result = filter_text(
                src,
                pattern=r"DoesNotExistMarker",
                tag="empty",
                last="1m",
                segmenter=_segmenter(),
            )
            self.assertEqual(result.match_records, 0)
            self.assertEqual(result.match_lines, 0)
            self.assertTrue(result.output_path.is_file())
            header = result.output_path.read_text(encoding="utf-8")
            self.assertIn("# match_records: 0", header)

    def test_terms_are_literal_not_regex(self) -> None:
        self.assertEqual(pattern_from_terms(["a.b", "[tag]"]), r"a\.b|\[tag\]")

    def test_format_specific_time_argument_is_delegated(self) -> None:
        ref = datetime(2026, 7, 25, 18, 42, 30)
        parsed = parse_time_arg(
            "next-minute", ref=ref, segmenter=RelativeTimeSegmenter()
        )
        self.assertEqual(parsed, datetime(2026, 7, 25, 18, 43, 0))


if __name__ == "__main__":
    unittest.main()
