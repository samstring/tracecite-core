from __future__ import annotations

"""Candidate-first literal search primitives for large text evidence sources.

The scanner answers only "where did the literal occur?" using raw bytes.  A
segmenter is invoked only for candidate locations that need to be materialized
as logical records.  This keeps record semantics while avoiding full-file
parsing on every query.

This module is intentionally internal for now.  The public ``runtime.search``
path can opt into it after parity/fallback coverage is proven.
"""

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from tracecite_core.records import Record
from tracecite_core.segmenter import (
    FormatSegmenter,
    JsonLineSegmenter,
    RawTextSegmenter,
    Segmenter,
)


_DEFAULT_INITIAL_RECOVERY_BYTES = 64 * 1024
_DEFAULT_MAX_RECOVERY_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True)
class CandidateHit:
    """One physical line containing the literal query."""

    line_number: int
    byte_start: int
    byte_end: int


@dataclass
class CandidateSearchResult:
    """Mechanical candidate-search result before Agent-result adaptation."""

    records: list[Record]
    match_records: int
    match_lines: int
    physical_hit_lines: int
    total_lines: int
    scan_seconds: float = 0.0
    recover_seconds: float = 0.0

    @property
    def status(self) -> str:
        return "ok" if self.match_records else "no_match"


class LocalRecoveryUnsupported(RuntimeError):
    """The selected segmenter cannot safely recover a record from local bytes."""


def _literal_bytes(query: str, *, encoding: str) -> bytes:
    if not query:
        raise ValueError("query must not be empty")
    needle = query.encode(encoding)
    if not needle:
        raise ValueError("query must not encode to empty bytes")
    return needle


def scan_literal(
    path: Path,
    query: str,
    *,
    encoding: str = "utf-8",
    keep_hits: Optional[int] = None,
) -> tuple[list[CandidateHit], int, int]:
    """Scan raw physical lines once.

    Returns ``(kept_hits, physical_hit_lines, total_lines)``.  ``keep_hits``
    bounds retained offsets without changing the exact hit-line count.
    """

    source = Path(path).expanduser().resolve()
    needle = _literal_bytes(query, encoding=encoding)
    hits: list[CandidateHit] = []
    hit_count = 0
    total_lines = 0
    offset = 0
    with source.open("rb") as handle:
        for line_number, raw in enumerate(handle, start=1):
            total_lines = line_number
            end = offset + len(raw)
            if needle in raw:
                hit_count += 1
                if keep_hits is None or len(hits) < keep_hits:
                    hits.append(CandidateHit(line_number, offset, end))
            offset = end
    return hits, hit_count, total_lines


def _read_hit_line(path: Path, hit: CandidateHit, *, encoding: str) -> str:
    with Path(path).open("rb") as handle:
        handle.seek(hit.byte_start)
        raw = handle.read(hit.byte_end - hit.byte_start)
    return raw.decode(encoding, errors="replace")


def _single_line_record(
    path: Path,
    hit: CandidateHit,
    segmenter: Segmenter,
    *,
    encoding: str,
) -> Record:
    text = _read_hit_line(path, hit, encoding=encoding)
    records = list(segmenter.segment_lines(iter([(hit.line_number, text)])))
    if len(records) != 1:
        raise LocalRecoveryUnsupported(
            f"single-line recovery produced {len(records)} records for "
            f"{type(segmenter).__name__}"
        )
    return records[0]


def _find_previous_format_start(
    path: Path,
    hit: CandidateHit,
    segmenter: FormatSegmenter,
    *,
    encoding: str,
    initial_bytes: int,
    max_bytes: int,
) -> int:
    window = min(max(1, initial_bytes), max(hit.byte_end, 1))
    while True:
        start = max(0, hit.byte_start - window)
        with Path(path).open("rb") as handle:
            handle.seek(start)
            data = handle.read(hit.byte_end - start)

        base = start
        # A backward byte window can begin in the middle of a physical line.
        # Drop that partial line before applying a line-start regex.
        if start > 0:
            first_nl = data.find(b"\n")
            if first_nl < 0:
                if window >= max_bytes:
                    raise LocalRecoveryUnsupported(
                        "no complete line in backward recovery window"
                    )
                window = min(max_bytes, window * 2)
                continue
            base += first_nl + 1
            data = data[first_nl + 1 :]

        cursor = base
        starts: list[int] = []
        for raw in data.splitlines(keepends=True):
            line_start = cursor
            cursor += len(raw)
            if line_start > hit.byte_start:
                break
            text = raw.decode(encoding, errors="replace")
            if segmenter.pattern.match(text):
                starts.append(line_start)
        if starts:
            return starts[-1]
        if start == 0:
            return 0
        if window >= max_bytes:
            raise LocalRecoveryUnsupported(
                "segment start not found within local recovery bound"
            )
        window = min(max_bytes, window * 2)


def _find_next_format_start(
    path: Path,
    hit: CandidateHit,
    segmenter: FormatSegmenter,
    *,
    encoding: str,
    max_bytes: int,
) -> int:
    source = Path(path)
    size = source.stat().st_size
    scanned = 0
    with source.open("rb") as handle:
        handle.seek(hit.byte_end)
        while handle.tell() < size:
            line_start = handle.tell()
            raw = handle.readline()
            if not raw:
                break
            scanned += len(raw)
            text = raw.decode(encoding, errors="replace")
            if segmenter.pattern.match(text):
                return line_start
            if scanned >= max_bytes:
                raise LocalRecoveryUnsupported(
                    "next segment start not found within local recovery bound"
                )
    return size


def _recover_format_record(
    path: Path,
    hit: CandidateHit,
    segmenter: FormatSegmenter,
    *,
    encoding: str,
    initial_bytes: int,
    max_bytes: int,
) -> Record:
    # Continuation rules can make a syntactic start line belong to the previous
    # record.  Until that state machine has a local proof, use the legacy path.
    continuation_kind = str((segmenter.continuation or {}).get("kind") or "")
    if continuation_kind:
        raise LocalRecoveryUnsupported(
            f"continuation kind {continuation_kind!r} requires legacy segmentation"
        )

    if not segmenter.multiline:
        return _single_line_record(path, hit, segmenter, encoding=encoding)

    start = _find_previous_format_start(
        path,
        hit,
        segmenter,
        encoding=encoding,
        initial_bytes=initial_bytes,
        max_bytes=max_bytes,
    )
    end = _find_next_format_start(
        path,
        hit,
        segmenter,
        encoding=encoding,
        max_bytes=max_bytes,
    )
    with Path(path).open("rb") as handle:
        handle.seek(start)
        raw = handle.read(end - start)

    prefix_len = max(0, hit.byte_start - start)
    start_line = hit.line_number - raw[:prefix_len].count(b"\n")
    text = raw.decode(encoding, errors="replace")
    pairs = [
        (start_line + index, line)
        for index, line in enumerate(text.splitlines(keepends=True))
    ]
    records = list(segmenter.segment_lines(iter(pairs)))
    if len(records) != 1:
        raise LocalRecoveryUnsupported(
            f"local format recovery produced {len(records)} records for "
            f"byte range {start}-{end}"
        )
    return records[0]


def supports_local_recovery(segmenter: Segmenter) -> bool:
    if isinstance(segmenter, JsonLineSegmenter):
        return True
    if isinstance(segmenter, RawTextSegmenter):
        return segmenter.mode == "line"
    if isinstance(segmenter, FormatSegmenter):
        return not bool(segmenter.continuation)
    return False


def recover_record(
    path: Path,
    hit: CandidateHit,
    segmenter: Segmenter,
    *,
    encoding: str = "utf-8",
    initial_bytes: int = _DEFAULT_INITIAL_RECOVERY_BYTES,
    max_bytes: int = _DEFAULT_MAX_RECOVERY_BYTES,
) -> Record:
    """Recover the logical record containing ``hit`` without scanning from L1."""

    if isinstance(segmenter, JsonLineSegmenter):
        return _single_line_record(path, hit, segmenter, encoding=encoding)
    if isinstance(segmenter, RawTextSegmenter) and segmenter.mode == "line":
        return _single_line_record(path, hit, segmenter, encoding=encoding)
    if isinstance(segmenter, FormatSegmenter):
        return _recover_format_record(
            path,
            hit,
            segmenter,
            encoding=encoding,
            initial_bytes=initial_bytes,
            max_bytes=max_bytes,
        )
    raise LocalRecoveryUnsupported(type(segmenter).__name__)


def candidate_first_literal_search(
    path: Path,
    query: str,
    *,
    segmenter: Segmenter,
    max_evidence: int = 20,
    encoding: str = "utf-8",
    initial_bytes: int = _DEFAULT_INITIAL_RECOVERY_BYTES,
    max_recovery_bytes: int = _DEFAULT_MAX_RECOVERY_BYTES,
) -> CandidateSearchResult:
    """Literal candidate scan + bounded local record materialization.

    This function deliberately does not implement snapshotting, time windows,
    PID scopes, template folding, provenance hashing, or Agent-result shaping.
    Callers must fall back when those semantics are required.
    """

    if not supports_local_recovery(segmenter):
        raise LocalRecoveryUnsupported(type(segmenter).__name__)
    limit = max(1, int(max_evidence))
    single_line = isinstance(segmenter, JsonLineSegmenter) or (
        isinstance(segmenter, RawTextSegmenter) and segmenter.mode == "line"
    ) or (isinstance(segmenter, FormatSegmenter) and not segmenter.multiline)

    scan_start = time.perf_counter()
    hits, physical_hit_lines, total_lines = scan_literal(
        Path(path),
        query,
        encoding=encoding,
        keep_hits=limit if single_line else None,
    )
    scan_seconds = time.perf_counter() - scan_start

    recover_start = time.perf_counter()
    records: list[Record] = []
    if single_line:
        for hit in hits:
            records.append(
                recover_record(
                    path,
                    hit,
                    segmenter,
                    encoding=encoding,
                    initial_bytes=initial_bytes,
                    max_bytes=max_recovery_bytes,
                )
            )
        match_records = physical_hit_lines
        match_lines = physical_hit_lines
    else:
        unique_ranges: set[tuple[int, int]] = set()
        for hit in hits:
            record = recover_record(
                path,
                hit,
                segmenter,
                encoding=encoding,
                initial_bytes=initial_bytes,
                max_bytes=max_recovery_bytes,
            )
            key = (record.start_line, record.end_line)
            if key in unique_ranges:
                continue
            unique_ranges.add(key)
            if len(records) < limit:
                records.append(record)
        match_records = len(unique_ranges)
        match_lines = sum(end - start + 1 for start, end in unique_ranges)
    recover_seconds = time.perf_counter() - recover_start

    return CandidateSearchResult(
        records=records,
        match_records=match_records,
        match_lines=match_lines,
        physical_hit_lines=physical_hit_lines,
        total_lines=total_lines,
        scan_seconds=scan_seconds,
        recover_seconds=recover_seconds,
    )
