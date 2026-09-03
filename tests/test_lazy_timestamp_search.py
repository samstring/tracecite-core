from __future__ import annotations

from pathlib import Path

from tracecite.runtime import tools
from tracecite_core import filter_text
from tracecite_core.segmenter import JsonLineSegmenter
import tracecite_core.segmenter as segmenter_module


def test_unscoped_agent_json_search_skips_timestamp_fallback_parsing(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "events.jsonl"
    source.write_text(
        '{"timestamp":"definitely-not-a-time","message":"needle"}\n' * 20,
        encoding="utf-8",
    )
    calls = 0
    original = segmenter_module._strptime_timestamp

    def counted(raw: str, fmt: str):
        nonlocal calls
        calls += 1
        return original(raw, fmt)

    monkeypatch.setattr(segmenter_module, "_strptime_timestamp", counted)
    result = tools.search(
        source, "needle", snapshot=False, segmenter="jsonline", cache=False
    )
    assert result["status"] == "ok"
    assert result["coverage"]["match_records"] == 20
    assert calls == 0
    assert all(item.get("timestamp") is None for item in result["evidence"])


def test_core_json_filter_default_keeps_timestamp_parsing_semantics(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "events.jsonl"
    source.write_text(
        '{"timestamp":"definitely-not-a-time","message":"needle"}\n',
        encoding="utf-8",
    )
    calls = 0
    original = segmenter_module._strptime_timestamp

    def counted(raw: str, fmt: str):
        nonlocal calls
        calls += 1
        return original(raw, fmt)

    monkeypatch.setattr(segmenter_module, "_strptime_timestamp", counted)
    result = filter_text(
        source, pattern="needle", snapshot=False, segmenter=JsonLineSegmenter()
    )
    assert result.match_records == 1
    assert calls > 0
