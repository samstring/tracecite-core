from __future__ import annotations

import re
from pathlib import Path

import pytest

from tracecite.runtime.assertions import pattern_hits
from tracecite_core.preprocess import run_preprocess_pipeline
from tracecite_core.segmenter import FormatSegmenter


def test_format_segmenter_rejects_unsafe_start_regex() -> None:
    with pytest.raises(re.error, match="nested variable repetitions"):
        FormatSegmenter(start=r"(a+)+$")


def test_preprocess_grep_rejects_unsafe_regex(tmp_path: Path) -> None:
    source = tmp_path / "source.log"
    source.write_text("safe input\n", encoding="utf-8")

    with pytest.raises(re.error, match="nested variable repetitions"):
        run_preprocess_pipeline(
            source,
            [{"action": "grep", "pattern": r"(a+)+$"}],
            temp_dir=tmp_path / "processed",
        )


def test_assertion_regex_gate_preserves_literal_fallback() -> None:
    assert pattern_hits("prefix (a+)+$ suffix", r"(a+)+$", ignore_case=False) == 1
