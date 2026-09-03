# -*- coding: utf-8 -*-
"""log_filter 增强：命中元数据 / 模板折叠 / term_usage。

验证核心承诺：**正文零污染** —— .filtered/ 正文与改动前完全一致，
新信息全部走独立产物（.hits.jsonl / .templates.jsonl）与头部指针。
"""

import json

import pytest

from tracecite_core import FormatSegmenter, build_segmenter
from tracecite_core.text_filter import (
    HEADER_TERMINATOR,
    filter_text,
    text_time_range,
    pattern_from_terms,
    strip_filter_header,
)

try:
    import ahocorasick  # noqa: F401

    HAVE_AC = True
except ImportError:  # pragma: no cover
    HAVE_AC = False

requires_ac = pytest.mark.skipif(not HAVE_AC, reason="pyahocorasick 未安装")


def _write_sample_log(path, *, hit_count=12, miss_count=5):
    lines = []
    t = 10
    for i in range(hit_count):
        num = i * 100 + 1
        lines.append(
            f"Aug  8 14:10:{t:02d}.000 app[123] <Notice>: user {num} login success"
        )
        t += 1
    for i in range(miss_count):
        lines.append(
            f"Aug  8 14:11:{i:02d}.000 app[123] <Notice>: heartbeat ok seq={i}"
        )
    lines.append("Aug  8 14:12:00.000 app[123] <Error>: connect 192.0.2.1 timeout 3000ms")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class TestPureLiteralEngine:
    @requires_ac
    def test_engine_is_aho_corasick(self, tmp_path):
        src = tmp_path / "sample.log"
        _write_sample_log(src)
        result = filter_text(
            src,
            pattern=pattern_from_terms(["login", "timeout"]),
            output_path=tmp_path / "out.log",
        )
        assert result.engine == "aho-corasick"

    def test_engine_is_literal_or_ac(self, tmp_path):
        src = tmp_path / "sample.log"
        _write_sample_log(src)
        result = filter_text(
            src,
            pattern=pattern_from_terms(["login", "timeout"]),
            output_path=tmp_path / "out.log",
        )
        assert result.engine in ("aho-corasick", "ac-python", "literal")
        assert result.match_records == 13

    def test_regex_pattern_keeps_re_engine(self, tmp_path):
        src = tmp_path / "sample.log"
        _write_sample_log(src)
        result = filter_text(
            src,
            pattern=r"connect\s+\d+\.\d+\.\d+\.\d+",
            output_path=tmp_path / "out.log",
        )
        assert result.engine == "regex"
        assert result.match_records == 1
        # 正则路径无词级信息
        assert result.hits_path is None
        assert result.term_usage is None


class TestHitMetadata:
    def test_hits_jsonl_generated(self, tmp_path):
        src = tmp_path / "sample.log"
        _write_sample_log(src)
        out = tmp_path / "out.log"
        result = filter_text(
            src,
            pattern=pattern_from_terms(["login", "timeout"]),
            output_path=out,
            segmenter=FormatSegmenter(
                start=r"^(?P<ts>[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}(?:\.\d+)?)",
                timestamp_formats=["%b %d %H:%M:%S.%f"],
                header_strip=(
                    r"^[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}(?:\.\d+)?"
                    r"\s+\S+\s+<[^>]+>:\s*"
                ),
            ),
        )
        assert result.hits_path is not None
        rows = [json.loads(line) for line in result.hits_path.read_text().splitlines()]
        assert len(rows) == 13
        for row in rows:
            assert row["term"] in ("login", "timeout")
            assert row["start_line"] >= 1
            assert row["end_line"] >= row["start_line"]
            assert row["hit_lines"]
        login_rows = [r for r in rows if r["term"] == "login"]
        timeout_rows = [r for r in rows if r["term"] == "timeout"]
        assert len(login_rows) == 12
        assert len(timeout_rows) == 1

    def test_header_points_to_hits(self, tmp_path):
        src = tmp_path / "sample.log"
        _write_sample_log(src)
        out = tmp_path / "out.log"
        result = filter_text(
            src,
            pattern=pattern_from_terms(["login"]),
            output_path=out,
            segmenter=build_segmenter(
                {
                    "start": r"^[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}",
                    "timestamp_formats": ["%b %d %H:%M:%S"],
                    "multiline": True,
                }
            ),
        )
        header = out.read_text().split(HEADER_TERMINATOR, 1)[0]
        assert "# engine:" in header
        assert f"# hits: {result.hits_path}" in header

    def test_body_zero_contamination(self, tmp_path):
        """核心承诺：正文不含 hits 信息，断言统计不受影响。"""
        src = tmp_path / "sample.log"
        _write_sample_log(src)
        out = tmp_path / "out.log"
        result = filter_text(
            src,
            pattern=pattern_from_terms(["login", "timeout"]),
            output_path=out,
        )
        body = strip_filter_header(out.read_text())
        assert "# hits:" not in body
        assert "# templates:" not in body
        assert body.count("login success") == 12
        assert body.count("timeout 3000ms") == 1
        # 正文物理行 == 命中记录行
        assert len(body.splitlines()) == 13


class TestTermUsage:
    def test_term_usage_counts(self, tmp_path):
        src = tmp_path / "sample.log"
        _write_sample_log(src)
        out = tmp_path / "out.log"
        result = filter_text(
            src,
            pattern=pattern_from_terms(["login", "timeout"]),
            output_path=out,
        )
        assert result.term_usage == {"login": 12, "timeout": 1}


class TestTemplateFold:
    def test_templates_jsonl_generated_above_threshold(self, tmp_path):
        src = tmp_path / "sample.log"
        _write_sample_log(src, hit_count=12)
        out = tmp_path / "out.log"
        result = filter_text(
            src,
            pattern=pattern_from_terms(["login", "timeout"]),
            output_path=out,
            template_threshold=10,
        )
        assert result.templates_path is not None
        entries = [json.loads(line) for line in result.templates_path.read_text().splitlines()]
        by_template = {e["template"]: e for e in entries}

        def _find(substr):
            return next((e for t, e in by_template.items() if substr in t), None)

        login_tpl = _find("user <NUM> login success")
        assert login_tpl is not None
        assert login_tpl["count"] == 12
        assert login_tpl["matched_terms"] == ["login"]
        assert "login" in login_tpl["sample"]
        vd = login_tpl["value_distribution"]
        assert vd and "<NUM>" in vd
        assert len(vd["<NUM>"]) >= 2
        timeout_tpl = _find("connect <IP> timeout <NUM>ms")
        assert timeout_tpl is not None
        assert timeout_tpl["count"] == 1
        assert timeout_tpl["matched_terms"] == ["timeout"]
        assert timeout_tpl["value_distribution"] == {}

    def test_template_stats_fold_ratio(self, tmp_path):
        src = tmp_path / "sample.log"
        _write_sample_log(src, hit_count=12)
        out = tmp_path / "out.log"
        result = filter_text(
            src,
            pattern=pattern_from_terms(["login", "timeout"]),
            output_path=out,
            template_threshold=10,
        )
        stats = result.template_stats
        assert stats is not None
        assert stats["templates"] == 2
        assert stats["folded_records"] == 12
        assert stats["singleton_templates"] == 1
        assert stats["fold_ratio"] == round(12 / 13, 4)

    def test_value_distribution_exposes_status_like_values(self, tmp_path):
        lines = [
            f"2026-08-08 14:10:{i:02d}.000 INFO http callStatus={200 if i < 8 else 500}"
            for i in range(10)
        ]
        src = tmp_path / "status.log"
        src.write_text("\n".join(lines) + "\n", encoding="utf-8")
        out = tmp_path / "out.log"
        result = filter_text(
            src,
            pattern=pattern_from_terms(["callStatus"]),
            output_path=out,
            template_threshold=10,
            segmenter=FormatSegmenter(
                start=r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+)",
            ),
        )
        entries = [json.loads(line) for line in result.templates_path.read_text().splitlines()]
        assert len(entries) == 1
        vd = entries[0]["value_distribution"]
        nums = {v["value"]: v["count"] for v in vd.get("<NUM>", [])}
        assert nums.get("200") == 8, nums
        assert nums.get("500") == 2, nums
        counts = [e["count"] for e in entries]
        assert counts == sorted(counts, reverse=True)
        assert all(e["first_seen"] for e in entries)

    def test_below_threshold_no_templates(self, tmp_path):
        src = tmp_path / "sample.log"
        _write_sample_log(src, hit_count=3, miss_count=2)
        out = tmp_path / "out.log"
        result = filter_text(
            src,
            pattern=pattern_from_terms(["login"]),
            output_path=out,
        )
        assert result.match_records == 3
        assert result.templates_path is None

    def test_threshold_disabled(self, tmp_path):
        src = tmp_path / "sample.log"
        _write_sample_log(src, hit_count=12)
        out = tmp_path / "out.log"
        result = filter_text(
            src,
            pattern=pattern_from_terms(["login", "timeout"]),
            output_path=out,
            template_threshold=0,
        )
        assert result.templates_path is None

    def test_default_no_fold(self, tmp_path):
        """按需折叠：默认不生成 .templates.jsonl。"""
        src = tmp_path / "sample.log"
        _write_sample_log(src, hit_count=12)
        out = tmp_path / "out.log"
        result = filter_text(
            src,
            pattern=pattern_from_terms(["login", "timeout"]),
            output_path=out,
        )
        assert result.match_records == 13
        assert result.templates_path is None
        assert result.template_stats is None
        assert result.term_usage == {"login": 12, "timeout": 1}
        assert "unmatched_summary" not in result.to_dict()

    def test_templates_header_pointer(self, tmp_path):
        src = tmp_path / "sample.log"
        _write_sample_log(src, hit_count=12)
        out = tmp_path / "out.log"
        result = filter_text(
            src,
            pattern=pattern_from_terms(["login"]),
            output_path=out,
            template_threshold=10,
        )
        header = out.read_text().split(HEADER_TERMINATOR, 1)[0]
        assert f"# templates: {result.templates_path}" in header


class TestMultiLineRecord:
    def test_multiline_block_hit_lines_absolute(self, tmp_path):
        lines = [
            "Aug  8 14:10:00.000 app[123] <Notice>: user 1 login success",
            "    continuation line A",
            "    continuation line B",
            "Aug  8 14:10:01.000 app[123] <Notice>: heartbeat",
            "Aug  8 14:10:02.000 app[123] <Notice>: user 2 login success",
        ]
        src = tmp_path / "multi.log"
        src.write_text("\n".join(lines) + "\n", encoding="utf-8")
        out = tmp_path / "out.log"
        result = filter_text(
            src,
            pattern=pattern_from_terms(["login"]),
            output_path=out,
            segmenter=build_segmenter(
                {
                    "start": r"^[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}",
                    "timestamp_formats": ["%b %d %H:%M:%S.%f"],
                    "multiline": True,
                }
            ),
        )
        rows = [json.loads(line) for line in result.hits_path.read_text().splitlines()]
        assert len(rows) == 2
        assert rows[0]["start_line"] == 1 and rows[0]["end_line"] == 3
        assert rows[0]["hit_lines"] == [1]
        assert rows[1]["start_line"] == 5 and rows[1]["end_line"] == 5
        assert rows[1]["hit_lines"] == [5]


class TestTimeRange:
    def test_minute_distribution(self, tmp_path):
        lines = []
        for minute in range(3):
            for i in range(5):
                lines.append(
                    f"2026-08-08 14:{10 + minute:02d}:{i:02d}.000 INFO line {i}"
                )
        src = tmp_path / "range.log"
        src.write_text("\n".join(lines) + "\n", encoding="utf-8")
        info = text_time_range(
            src,
            segmenter=FormatSegmenter(
                start=r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+)",
            ),
        )
        assert info["total_records"] == 15
        assert info["time_from"] == "2026-08-08T14:10:00"
        assert info["time_to"] == "2026-08-08T14:12:04"
        assert len(info["minute_distribution"]) == 3
        assert info["minute_distribution"][0]["records"] == 5

    def test_tail_backfill_lines_do_not_hide_real_range(self, tmp_path):
        lines = [
            "2026-08-08 14:10:00.000 INFO start",
            "2026-08-08 14:11:00.000 INFO mid",
            "2026-08-08 14:12:00.000 INFO end",
            "2026-08-08 14:10:00.000 INFO backfill(old line)",
        ]
        src = tmp_path / "backfill.log"
        src.write_text("\n".join(lines) + "\n", encoding="utf-8")
        info = text_time_range(
            src,
            segmenter=FormatSegmenter(
                start=r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+)",
            ),
        )
        assert info["time_from"] == "2026-08-08T14:10:00"
        assert info["time_to"] == "2026-08-08T14:12:00"
        assert len(info["minute_distribution"]) == 3


def test_filter_output_truncates_long_lines_but_records_stay_full(tmp_path):
    src = tmp_path / "big.log"
    giant = "X" * 5000
    src.write_text(f"2026-08-08 14:10:00 INFO hit {giant}\n", encoding="utf-8")
    out = tmp_path / "filtered.log"

    result = filter_text(src, pattern="hit", output_path=out, max_line_chars=512)

    body = out.read_text(encoding="utf-8")
    assert "...[trunc, expand:#L1]" in body
    assert len(body.splitlines()[-1]) <= 520
    records = (tmp_path / "filtered.log.records.jsonl").read_text(encoding="utf-8")
    assert giant in records
    assert result.lines_truncated == 1
    assert result.max_line_chars == 512
    header = body.split("# ---\n", 1)[0]
    assert "# lines_truncated: 1" in header
    assert "# max_line_chars: 512" in header
    assert result.history_path is not None
    history = result.history_path.read_text(encoding="utf-8").splitlines()
    entry = json.loads(history[-1])
    assert entry["lines_truncated"] == 1
    assert entry["max_line_chars"] == 512
