"""Format-neutral local Record recovery from raw physical-line hits."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .records import Record
from .segmenter import FormatSegmenter, JsonLineSegmenter, RawTextSegmenter, Segmenter


_DEFAULT_INITIAL_RECOVERY_BYTES = 64 * 1024
_DEFAULT_MAX_RECOVERY_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True)
class CandidateHit:
    line_number: int
    byte_start: int
    byte_end: int


class LocalRecoveryUnsupported(RuntimeError):
    pass


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
    rows = list(segmenter.segment_lines(iter([(hit.line_number, text)])))
    if len(rows) != 1:
        raise LocalRecoveryUnsupported(
            f"single-line recovery produced {len(rows)} records for {type(segmenter).__name__}"
        )
    return rows[0]


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
        if start > 0:
            first_nl = data.find(b"\n")
            if first_nl < 0:
                if window >= max_bytes:
                    raise LocalRecoveryUnsupported("no complete line in recovery window")
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
            if segmenter.pattern.match(raw.decode(encoding, errors="replace")):
                starts.append(line_start)
        if starts:
            return starts[-1]
        if start == 0:
            return 0
        if window >= max_bytes:
            raise LocalRecoveryUnsupported("segment start not found within recovery bound")
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
            if segmenter.pattern.match(raw.decode(encoding, errors="replace")):
                return line_start
            if scanned >= max_bytes:
                raise LocalRecoveryUnsupported("next segment start not found within recovery bound")
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
    if segmenter.continuation:
        raise LocalRecoveryUnsupported("continuation state requires full Record scanning")
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
            f"local recovery produced {len(records)} records for byte range {start}-{end}"
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


__all__ = [
    "CandidateHit",
    "LocalRecoveryUnsupported",
    "recover_record",
    "supports_local_recovery",
]
