"""Unbounded candidate-first Record stream for Evidence Shell.

The scanner finds raw physical-line hits first and invokes the Segmenter only
for hit locations. There is no hidden candidate-count limit; the caller owns
Evidence byte/token admission and may stop once the user budget is exceeded.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

from tracecite_core.matcher import Matcher
from tracecite_core.records import Record
from tracecite_core.segmenter import FormatSegmenter, JsonLineSegmenter, RawTextSegmenter, Segmenter

from .candidate_search import CandidateHit, LocalRecoveryUnsupported, recover_record, supports_local_recovery


class CandidateStreamUnsupported(RuntimeError):
    """The query/segmenter cannot preserve semantics with raw-hit recovery."""


def _single_line(segmenter: Segmenter) -> bool:
    return isinstance(segmenter, JsonLineSegmenter) or (
        isinstance(segmenter, RawTextSegmenter) and segmenter.mode == "line"
    ) or (isinstance(segmenter, FormatSegmenter) and not segmenter.multiline)


def iter_candidate_records(
    path: Path,
    *,
    query: str,
    regex: bool,
    segmenter: Segmenter,
    encoding: str = "utf-8",
) -> Iterator[Record]:
    """Yield complete unique records after raw physical-line candidate search."""

    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if not query:
        raise ValueError("candidate query must be non-empty")
    if "\n" in query or "\r" in query:
        raise CandidateStreamUnsupported("cross-line query requires full Record scanning")
    if not supports_local_recovery(segmenter):
        raise CandidateStreamUnsupported(type(segmenter).__name__)
    if regex and not _single_line(segmenter):
        # A regex may intentionally depend on multiline Record text. Raw-line
        # preselection cannot prove parity for that case.
        raise CandidateStreamUnsupported("multiline regex requires full Record scanning")

    needle = query.encode(encoding) if not regex else b""
    matcher = Matcher(query) if regex else None
    seen_ranges: set[tuple[int, int]] = set()
    offset = 0

    with source.open("rb") as handle:
        for line_number, raw in enumerate(handle, start=1):
            end = offset + len(raw)
            if regex:
                text = raw.decode(encoding, errors="replace")
                matched = matcher.match(text)[0] if matcher is not None else False
            else:
                matched = needle in raw
            if matched:
                hit = CandidateHit(line_number, offset, end)
                try:
                    record = recover_record(
                        source,
                        hit,
                        segmenter,
                        encoding=encoding,
                    )
                except LocalRecoveryUnsupported as exc:
                    raise CandidateStreamUnsupported(str(exc)) from exc
                key = (record.start_line, record.end_line)
                if key not in seen_ranges:
                    seen_ranges.add(key)
                    yield record
            offset = end


__all__ = ["CandidateStreamUnsupported", "iter_candidate_records"]
