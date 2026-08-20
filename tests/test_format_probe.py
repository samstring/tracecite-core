"""Tests for L1 clue-probe auto-detection of regex FormatSegmenter configs."""

from __future__ import annotations

from pathlib import Path

import pytest

from tracecite_core.format_probe import probe_format_config, probe_format_report
from tracecite_core.segmenter import build_segmenter, detect_segmenter_kind
from tracecite_core.survey import survey_file


def _write(tmp_path: Path, name: str, lines: list[str]) -> Path:
    path = tmp_path / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "name,lines,expected_fmt",
    [
        ("iso_space", [
            "2024-01-02 03:04:05 INFO ok",
            "2024-01-02 03:04:06 WARN retry",
            "2024-01-02 03:04:07 ERROR boom",
        ], "%Y-%m-%d %H:%M:%S"),
        ("iso_tz", [
            "2024-01-02T03:04:05.123Z started",
            "2024-01-02T03:04:06.000Z done",
            "2024-01-02T03:04:07.500Z failed",
        ], "%Y-%m-%dT%H:%M:%S"),
        ("compact_date", [
            "081109 203615 148 INFO dfs.DataNode: x",
            "081109 203807 222 INFO dfs.FSNamesystem: y",
            "081110 000037 35 WARN dfs.DataNode: z",
        ], "%y%m%d %H%M%S"),
    ],
)
def test_probe_detects_line_start(tmp_path, name, lines, expected_fmt):
    path = _write(tmp_path, f"{name}.log", lines)
    report = probe_format_report(path)
    assert report["detected"] is True
    assert report["confidence"] >= 0.9
    assert report["config"] is not None
    assert any(expected_fmt in f for f in report["structure"]["formats"])
    # Config must drive survey without a hand-written rule.
    summary = survey_file(path, segmenter=build_segmenter(report["config"]), snapshot=False)
    assert summary.timestamped_records == summary.scan_records


def test_probe_detects_apache_bracketed(tmp_path):
    path = _write(tmp_path, "apache.log", [
        '127.0.0.1 - - [10/Oct/2000:13:55:36 -0700] "GET /a HTTP/1.0" 200 2326',
        '127.0.0.1 - - [10/Oct/2000:13:55:37 -0700] "GET /b HTTP/1.0" 200 1200',
        '127.0.0.1 - - [10/Oct/2000:13:55:38 -0700] "POST /c HTTP/1.0" 500 300',
    ])
    report = probe_format_report(path)
    assert report["detected"] is True
    assert report["confidence"] >= 0.9
    assert "%d/%b/%Y:%H:%M:%S" in " ".join(report["structure"]["formats"])
    seg = build_segmenter(report["config"])
    records = list(seg.segment_file(path))
    assert len(records) == 3
    # %z parses the -0700 offset; prefix flows into fields.
    assert records[0].timestamp.year == 2000
    assert records[0].timestamp.utcoffset() is not None
    assert records[0].fields.get("prefix") == "127.0.0.1 - - "


def test_probe_midline_medium_confidence(tmp_path):
    # Full coverage but position weight 0.8 -> medium, no auto config.
    path = _write(tmp_path, "midline.log", [
        "node-1 2026-08-19 10:11:12.345 INFO  boot ok",
        "node-1 2026-08-19 10:11:13.456 WARN  retry",
        "node-2 2026-08-19 10:11:14.567 ERROR boom",
    ])
    report = probe_format_report(path)
    # 行中时间戳：位置权重 0.8 -> 中置信，无 auto config，agent 决策。
    assert report["detected"] is False
    assert report["confidence"] < 0.9
    assert report["config"] is None
    assert "pick_candidate" in report["actions"]
    assert "fallback_rawtext" in report["actions"]


def test_probe_plain_text_falls_back(tmp_path):
    path = _write(tmp_path, "plain.log", [
        "just a line of text",
        "another line without timestamps",
    ])
    report = probe_format_report(path)
    assert report["detected"] is False
    assert report["config"] is None
    assert report["fallback"] == "rawtext"
    assert report["actions"] == ["increase_sample", "fallback_rawtext"]


def test_probe_jsonline_suggests_jsonline(tmp_path):
    path = _write(tmp_path, "x.jsonl", [
        '{"ts": "2026-08-19T10:00:00", "level": "ERROR", "msg": "boom"}',
        '{"ts": "2026-08-19T10:00:01", "level": "INFO", "msg": "ok"}',
    ])
    report = probe_format_report(path)
    assert report["detected"] is True
    assert report["position"] == "json"
    assert report["fallback"] == "jsonline"
    assert report["actions"] == ["use_jsonline"]


def test_probe_config_is_clean_formatsegmenter_dict(tmp_path):
    path = _write(tmp_path, "cfg.log", ["2024-01-02 03:04:05 hi"])
    config = probe_format_config(path)
    assert isinstance(config, dict)
    assert set(config) == {"start", "timestamp_formats", "multiline", "flags"}
    build_segmenter(config)  # safe to pass straight in


def test_probe_injects_level_at_idx0(tmp_path):
    path = _write(tmp_path, "lvl0.log", [
        "2024-01-02 03:04:05 INFO  login ok",
        "2024-01-02 03:04:06 WARN  cache miss",
        "2024-01-02 03:04:07 ERROR boom",
    ])
    report = probe_format_report(path)
    assert report["level"]["detected"] is True
    assert report["level"]["index"] == 0
    assert "(?P<level>" in report["config"]["start"]
    seg = build_segmenter(report["config"])
    levels = [r.fields.get("level") for r in seg.segment_file(path)]
    assert levels == ["INFO", "WARN", "ERROR"]


def test_probe_config_reports_issues_when_uncertain(tmp_path):
    # Only 2 distinct timestamps but coverage 1.0 -> should still detect.
    path = _write(tmp_path, "small.log", [
        "2024-01-02 03:04:05 INFO a",
        "2024-01-02 03:04:05 INFO b",
        "2024-01-02 03:04:05 INFO c",
    ])
    report = probe_format_report(path)
    assert report["detected"] is True
    assert report["coverage"] == 1.0


def test_auto_detects_unfamiliar_timestamp_log(tmp_path):
    kind = detect_segmenter_kind(_write(tmp_path, "u.log", [
        "2024-01-02 03:04:05 INFO  boot ok",
        "2024-01-02 03:04:06 WARN  retry 1",
        "2024-01-02 03:04:07 ERROR boom",
    ]))
    assert isinstance(kind, dict)
    assert "(?P<ts>" in kind["start"]
    assert "timestamp_formats" in kind


def test_auto_keeps_jsonline_unchanged(tmp_path):
    path = _write(tmp_path, "x.jsonl", [
        '{"ts": 1, "msg": "a"}',
        '{"ts": 2, "msg": "b"}',
        '{"ts": 3, "msg": "c"}',
    ])
    assert detect_segmenter_kind(path) == "jsonline"


def test_auto_keeps_rawtext_unchanged(tmp_path):
    path = _write(tmp_path, "plain.log", [
        "just a line",
        "another line",
    ])
    assert detect_segmenter_kind(path) == "rawtext"


def test_auto_survey_uses_inferred_segmenter(tmp_path):
    path = _write(tmp_path, "unknown.log", [
        "2024-01-02 03:04:05 INFO  boot ok",
        "2024-01-02 03:04:06 WARN  retry 1",
        "2024-01-02 03:04:07 ERROR boom",
    ])
    summary = survey_file(path, snapshot=False)
    assert summary.segmenter == "format:inferred"
    assert summary.timestamped_records == summary.scan_records
    assert summary.unparsed_timestamp_records == 0
    assert summary.observed_from is not None


def test_auto_survey_parses_apache_inline(tmp_path):
    # auto path must consume bracketed inline timestamps end to end.
    path = _write(tmp_path, "apache.log", [
        '127.0.0.1 - - [10/Oct/2000:13:55:36 -0700] "GET /a HTTP/1.0" 200 2326',
        '127.0.0.1 - - [10/Oct/2000:13:55:37 -0700] "GET /b HTTP/1.0" 200 1200',
        '127.0.0.1 - - [10/Oct/2000:13:55:38 -0700] "POST /c HTTP/1.0" 500 300',
    ])
    summary = survey_file(path, snapshot=False)
    assert summary.segmenter == "format:inferred"
    assert summary.timestamped_records == summary.scan_records
    assert summary.unparsed_timestamp_records == 0
    assert summary.observed_from is not None
    assert summary.observed_from.year == 2000


def test_detector_rawtext_fallback_does_not_short_circuit_probe(tmp_path):
    # A detector returning "rawtext" (its fallback signal) must NOT stop the
    # probe chain: L1 inference should still run and may produce a better dict.
    from tracecite_core.segmenter import (
        detect_segmenter_kind,
        register_segmenter_detector,
    )
    import tracecite_core.segmenter as seg_mod

    path = _write(tmp_path, "unknown.log", [
        "2024-01-02 03:04:05 INFO  boot ok",
        "2024-01-02 03:04:06 WARN  retry 1",
        "2024-01-02 03:04:07 ERROR boom",
    ])

    def rawtext_fallback(path, sample_lines=200):
        return "rawtext"  # always the fallback signal, never None

    register_segmenter_detector("t_rt", rawtext_fallback, priority=100, replace=True)
    try:
        kind = detect_segmenter_kind(path)
        assert isinstance(kind, dict)  # L1 probe ran despite rawtext signal
        assert "(?P<ts>" in kind["start"]
    finally:
        seg_mod._DETECTORS.pop("t_rt", None)


def test_detector_clear_hit_wins_over_probe(tmp_path):
    # A detector with a real format name still wins immediately (no probe).
    from tracecite_core.segmenter import (
        detect_segmenter_kind,
        register_segmenter_detector,
    )
    import tracecite_core.segmenter as seg_mod

    path = _write(tmp_path, "mine.log", [
        "2024-01-02 03:04:05 INFO  boot ok",
        "2024-01-02 03:04:06 WARN  retry 1",
        "2024-01-02 03:04:07 ERROR boom",
    ])

    def clear_hit(path, sample_lines=200):
        return "jsonline"  # definite hit, not a fallback

    register_segmenter_detector("t_hit", clear_hit, priority=100, replace=True)
    try:
        assert detect_segmenter_kind(path) == "jsonline"
    finally:
        seg_mod._DETECTORS.pop("t_hit", None)


def test_probe_detects_bracketed_line_start(tmp_path):
    # [2024-01-02 03:04:05] line-start bracket form (not apache midline).
    path = _write(tmp_path, "bracket.log", [
        "[2024-01-02 03:04:05] boot",
        "[2024-01-02 03:04:06] ready",
        "[2024-01-02 03:04:07] down",
    ])
    report = probe_format_report(path)
    assert report["detected"] is True
    assert report["confidence"] >= 0.9
    assert any("%Y-%m-%d %H:%M:%S" in f for f in report["structure"]["formats"])
    seg = build_segmenter(report["config"])
    records = list(seg.segment_file(path))
    assert len(records) == 3
    assert records[0].timestamp.year == 2024


def test_probe_time_only_reaches_high_confidence(tmp_path):
    # time_only is line-start; false-positive risk is handled by the 0.85
    # coverage bar, so position weight must not keep it below high confidence.
    path = _write(tmp_path, "time.log", [
        "03:04:05.123 INFO  a",
        "03:04:06.456 WARN  b",
        "03:04:07.789 ERROR c",
    ])
    report = probe_format_report(path)
    assert report["confidence"] >= 0.9
    assert report["detected"] is True
    assert any("%H:%M:%S" in f for f in report["structure"]["formats"])


def test_auto_survey_jsonline_with_z(tmp_path):
    # JsonLineSegmenter's built-in formats require a Z / space separator; the
    # probe must still route JSON to jsonline and survey must parse timestamps.
    path = _write(tmp_path, "x.jsonl", [
        '{"ts": "2026-08-19T10:00:00Z", "level": "ERROR", "msg": "boom"}',
        '{"ts": "2026-08-19T10:00:01Z", "level": "INFO", "msg": "ok"}',
        '{"ts": "2026-08-19T10:00:02Z", "level": "WARN", "msg": "retry"}',
    ])
    assert detect_segmenter_kind(path) == "jsonline"
    summary = survey_file(path, snapshot=False)
    assert summary.timestamped_records == summary.scan_records


# ---------------------------------------------------------------------------
# 通用结构归纳(无候选枚举):LogHub 真实格式
# ---------------------------------------------------------------------------

LOGHUB = "/tmp/loghub_samples"


def _loghub(name: str) -> Path:
    p = Path(LOGHUB) / f"{name}_2k.log"
    assert p.is_file(), f"LogHub 样本缺失: {p}"
    return p


@pytest.mark.parametrize(
    "name,fmt",
    [
        ("Hadoop", "%Y-%m-%d %H:%M:%S"),
        ("Zookeeper", "%Y-%m-%d %H:%M:%S"),
        ("Android", "%m-%d %H:%M:%S"),
        ("Spark", "%y/%m/%d %H:%M:%S"),
        ("HealthApp", "%Y%m%d-%H:%M:%S"),
        ("Windows", "%Y-%m-%d %H:%M:%S"),
        ("Linux", "%b %d %H:%M:%S"),
        ("Mac", "%b %d %H:%M:%S"),
        ("OpenSSH", "%b %d %H:%M:%S"),
        ("HDFS", "%y%m%d %H%M%S"),
    ],
)
def test_probe_loghub_structural_inference(tmp_path, name, fmt):
    # 通用结构归纳:不枚举候选,从行结构推断 strptime 格式。
    path = _loghub(name)
    report = probe_format_report(path)
    assert report["detected"] is True, f"{name}: {report['issues']}"
    assert report["confidence"] >= 0.9, f"{name}: conf={report['confidence']}"
    fmts = " ".join(report["structure"]["formats"])
    assert fmt in fmts, f"{name}: 缺 {fmt}，got {fmts}"
    # config 必须可被 survey 消费
    seg = build_segmenter(report["config"])
    summary = survey_file(path, snapshot=False)
    assert summary.timestamped_records > 0
