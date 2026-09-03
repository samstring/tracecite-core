from __future__ import annotations

from pathlib import Path

from tracecite_core import FormatSegmenter
from tracecite_core.text_filter import filter_text, filter_texts


class CountingFormatSegmenter(FormatSegmenter):
    def __init__(self) -> None:
        super().__init__(
            start=r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})",
            timestamp_formats=["%Y-%m-%d %H:%M:%S"],
            multiline=True,
        )
        self.built_records = 0

    def _build(self, pending, first):
        self.built_records += 1
        return super()._build(pending, first)


def _write_records(path: Path, count: int, *, hit_at: int | None = None) -> None:
    rows = []
    for index in range(count):
        message = "needle target" if index == hit_at else "ordinary heartbeat"
        rows.append(f"2026-08-08 14:10:{index % 60:02d} {message}\n")
    path.write_text("".join(rows), encoding="utf-8")


def test_literal_sparse_hit_segments_only_candidate_record(tmp_path: Path) -> None:
    source = tmp_path / "sparse.log"
    _write_records(source, 100, hit_at=73)
    segmenter = CountingFormatSegmenter()

    result = filter_text(
        source,
        pattern="needle",
        output_path=tmp_path / "out.log",
        segmenter=segmenter,
    )

    assert result.match_records == 1
    assert result.candidate_strategy == "candidate-first:literal"
    assert segmenter.built_records == 1


def test_zero_literal_hit_does_not_segment_file(tmp_path: Path) -> None:
    source = tmp_path / "zero.log"
    _write_records(source, 100)
    segmenter = CountingFormatSegmenter()

    result = filter_text(
        source,
        pattern="never-present",
        output_path=tmp_path / "out.log",
        segmenter=segmenter,
    )

    assert result.match_records == 0
    assert result.candidate_strategy == "candidate-first:literal"
    assert segmenter.built_records == 0


def test_dotall_regex_candidate_then_full_record_recheck(tmp_path: Path) -> None:
    source = tmp_path / "multiline.log"
    source.write_text(
        "2026-08-08 14:10:00 request failed\n"
        "    reason: timeout\n"
        "2026-08-08 14:10:01 request ok\n",
        encoding="utf-8",
    )
    segmenter = CountingFormatSegmenter()

    result = filter_text(
        source,
        pattern=r"(?s)failed.*timeout",
        output_path=tmp_path / "out.log",
        segmenter=segmenter,
    )

    assert result.match_records == 1
    assert result.candidate_strategy == "candidate-first:required-literal"
    assert segmenter.built_records == 1
    assert "request failed" in result.records_path.read_text(encoding="utf-8")
    assert "reason: timeout" in result.records_path.read_text(encoding="utf-8")


def test_cross_record_dotall_false_positive_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "cross-record.log"
    source.write_text(
        "2026-08-08 14:10:00 request failed\n"
        "2026-08-08 14:10:01 timeout while doing another request\n",
        encoding="utf-8",
    )
    segmenter = CountingFormatSegmenter()

    result = filter_text(
        source,
        pattern=r"(?s)failed.*timeout",
        output_path=tmp_path / "out.log",
        segmenter=segmenter,
    )

    assert result.match_records == 0
    assert result.candidate_strategy == "candidate-first:required-literal"
    # The raw candidate is the timeout record; full-record re-check drops it.
    assert segmenter.built_records == 1


def test_regex_without_safe_literal_falls_back(tmp_path: Path) -> None:
    source = tmp_path / "fallback.log"
    source.write_text(
        "2026-08-08 14:10:00 ABC\n"
        "2026-08-08 14:10:01 ordinary\n"
        "2026-08-08 14:10:02 ordinary\n",
        encoding="utf-8",
    )
    segmenter = CountingFormatSegmenter()

    result = filter_text(
        source,
        pattern=r"\b[A-Z]{3}\b",
        output_path=tmp_path / "out.log",
        segmenter=segmenter,
    )

    assert result.match_records == 1
    assert result.candidate_strategy == "segment-first"
    assert segmenter.built_records > 1


def test_scoped_ignorecase_falls_back_without_missing_match(tmp_path: Path) -> None:
    source = tmp_path / "scoped-ignorecase.log"
    source.write_text(
        "2026-08-08 14:10:00 NEEDLE target\n"
        "2026-08-08 14:10:01 ordinary\n",
        encoding="utf-8",
    )
    segmenter = CountingFormatSegmenter()

    result = filter_text(
        source,
        pattern=r"(?i:needle) target",
        output_path=tmp_path / "out.log",
        segmenter=segmenter,
    )

    assert result.match_records == 1
    assert result.candidate_strategy == "segment-first"
    assert segmenter.built_records == 2


def test_ascii_global_ignorecase_remains_candidate_first(tmp_path: Path) -> None:
    source = tmp_path / "ascii-ignorecase.log"
    source.write_text(
        "2026-08-08 14:10:00 NEEDLE target\n"
        "2026-08-08 14:10:01 ordinary\n",
        encoding="utf-8",
    )
    segmenter = CountingFormatSegmenter()

    result = filter_text(
        source,
        pattern=r"(?ai)needle target",
        output_path=tmp_path / "out.log",
        segmenter=segmenter,
    )

    assert result.match_records == 1
    assert result.candidate_strategy == "candidate-first:required-literal"
    assert segmenter.built_records == 1


def test_unmatched_summary_is_not_published(tmp_path: Path) -> None:
    source = tmp_path / "schema.log"
    _write_records(source, 3, hit_at=1)

    result = filter_text(
        source,
        pattern="needle",
        output_path=tmp_path / "out.log",
        segmenter=CountingFormatSegmenter(),
    )

    assert "unmatched_summary" not in result.to_dict()


def test_filter_texts_uses_same_candidate_first_engine(tmp_path: Path) -> None:
    first = tmp_path / "first.log"
    second = tmp_path / "second.log"
    _write_records(first, 20, hit_at=3)
    _write_records(second, 20, hit_at=12)
    segmenters = [CountingFormatSegmenter(), CountingFormatSegmenter()]

    result = filter_texts(
        [first, second],
        pattern="needle",
        segmenter=segmenters,
        output_dir=tmp_path / "filtered",
    )

    assert result.match_records == 2
    assert all(
        row["candidate_strategy"] == "candidate-first:literal"
        for row in result.sources
    )
    assert [item.built_records for item in segmenters] == [1, 1]
