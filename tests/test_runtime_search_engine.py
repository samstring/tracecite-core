from __future__ import annotations

import re
from pathlib import Path

from tracecite.runtime import search_engine, tools
from tracecite.runtime.candidate_filter import CandidateFilterUnsupported
from tracecite_core.segmenter import RawTextSegmenter


def test_literal_search_uses_candidate_first_fast_path(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "plain.log"
    source.write_text("alpha\nneedle one\nbeta\nneedle two\n", encoding="utf-8")
    original = search_engine.filter_literal_single_line
    calls = 0

    def wrapped(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(search_engine, "filter_literal_single_line", wrapped)
    result = search_engine.search_text(
        source,
        pattern=re.escape("needle"),
        regex=False,
        output_path=tmp_path / "fast" / "evidence.log",
        snapshot=False,
        segmenter=RawTextSegmenter(mode="line"),
    )

    assert calls == 1
    assert result.match_records == 2


def test_regex_search_bypasses_candidate_first(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "plain.log"
    source.write_text("alpha\nneedle one\nneedle two\n", encoding="utf-8")

    def unexpected(*args, **kwargs):
        raise AssertionError("regex search must not enter literal fast path")

    monkeypatch.setattr(search_engine, "filter_literal_single_line", unexpected)
    result = search_engine.search_text(
        source,
        pattern=r"needle\s+(?:one|two)",
        regex=True,
        output_path=tmp_path / "legacy" / "evidence.log",
        snapshot=False,
        segmenter=RawTextSegmenter(mode="line"),
    )

    assert result.match_records == 2


def test_unsupported_fast_path_falls_back_to_legacy(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "plain.log"
    source.write_text("alpha\nneedle\nbeta\n", encoding="utf-8")

    def unsupported(*args, **kwargs):
        raise CandidateFilterUnsupported("test fallback")

    monkeypatch.setattr(search_engine, "filter_literal_single_line", unsupported)
    result = search_engine.search_text(
        source,
        pattern=re.escape("needle"),
        regex=False,
        output_path=tmp_path / "fallback" / "evidence.log",
        snapshot=False,
        segmenter=RawTextSegmenter(mode="line"),
    )

    assert result.match_records == 1


def test_runtime_tools_search_routes_through_search_engine(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "plain.log"
    source.write_text("alpha\nneedle\n", encoding="utf-8")
    original = tools.search_text
    calls = 0

    def wrapped(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(tools, "search_text", wrapped)
    result = tools.search(source, "needle", snapshot=False, cache=False)

    assert calls == 1
    assert result["status"] == "ok"
    assert result["coverage"]["match_records"] == 1
