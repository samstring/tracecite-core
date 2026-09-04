"""Artifact-free logical Record search.

This is the low-level mechanical search seam used by Evidence Shell. It yields
complete Segmenter records directly and never writes filtered logs,
matched-record JSONL, hit JSONL, unmatched summaries, or filter history.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional

from .matcher import Matcher
from .records import Record
from .segmenter import RawTextSegmenter, Segmenter
from .text_filter import (
    FilterError,
    parse_last_duration,
    parse_time_arg,
    record_timestamp,
    reference_datetime,
)


def _line_count(path: Path, *, encoding: str) -> int:
    count = 0
    with path.open("r", encoding=encoding, errors="replace") as handle:
        for _ in handle:
            count += 1
    return count


def _last_timestamp(
    path: Path,
    *,
    segmenter: Segmenter,
    reference: datetime,
    encoding: str,
) -> Optional[datetime]:
    last: Optional[datetime] = None
    for record in segmenter.segment_file(path, encoding=encoding):
        ts = record_timestamp(record, ref=reference, segmenter=segmenter)
        if ts is not None:
            last = ts
    return last


def _time_window(
    path: Path,
    *,
    segmenter: Segmenter,
    last: str | None,
    since: str | None,
    until: str | None,
    encoding: str,
) -> tuple[datetime, Optional[datetime], Optional[datetime]]:
    reference = reference_datetime(path, segmenter=segmenter, encoding=encoding)
    time_from: Optional[datetime] = None
    time_to: Optional[datetime] = None

    if last is not None:
        duration = parse_last_duration(last)
        final_ts = _last_timestamp(
            path,
            segmenter=segmenter,
            reference=reference,
            encoding=encoding,
        )
        if final_ts is None:
            raise FilterError("无法从日志解析时间戳，不能使用 --last")
        time_from = final_ts - duration
        time_to = final_ts

    if since is not None:
        parsed = parse_time_arg(since, ref=reference, segmenter=segmenter)
        time_from = parsed if time_from is None else max(time_from, parsed)
    if until is not None:
        parsed = parse_time_arg(until, ref=reference, segmenter=segmenter)
        time_to = parsed if time_to is None else min(time_to, parsed)

    if time_from is not None and time_to is not None and time_from > time_to:
        raise FilterError(f"时间窗口无效: time_from={time_from!s} > time_to={time_to!s}")
    return reference, time_from, time_to


def _in_time_window(
    record: Record,
    *,
    segmenter: Segmenter,
    reference: datetime,
    time_from: Optional[datetime],
    time_to: Optional[datetime],
) -> bool:
    if time_from is None and time_to is None:
        return True
    ts = record_timestamp(record, ref=reference, segmenter=segmenter)
    if ts is None:
        return True
    if time_from is not None and ts < time_from:
        return False
    if time_to is not None and ts > time_to:
        return False
    return True


def iter_matching_records(
    input_path: Path,
    *,
    query: str | None,
    regex: bool = False,
    segmenter: Optional[Segmenter] = None,
    last: str | None = None,
    since: str | None = None,
    until: str | None = None,
    tail_lines: int | None = None,
    line_from: int | None = None,
    line_to: int | None = None,
    pid: int | None = None,
    encoding: str = "utf-8",
) -> Iterator[Record]:
    """Yield complete logical records matching one source/scope.

    ``query=None`` means scan all records. Otherwise ``regex=False`` is a true
    literal contract and ``regex=True`` uses TraceCite's safe Matcher.
    """

    source = Path(input_path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if query is not None and not query:
        raise ValueError("query must be non-empty when supplied")

    for name, value in (
        ("tail_lines", tail_lines),
        ("line_from", line_from),
        ("line_to", line_to),
    ):
        if value is not None and value <= 0:
            raise ValueError(f"{name} must be positive")
    if line_from is not None and line_to is not None and line_from > line_to:
        raise ValueError("line_from must not exceed line_to")

    selected = segmenter or RawTextSegmenter(mode="line")
    matcher = Matcher(query) if query is not None and regex else None
    reference, time_from, time_to = _time_window(
        source,
        segmenter=selected,
        last=last,
        since=since,
        until=until,
        encoding=encoding,
    )

    start_line = line_from or 1
    if tail_lines is not None:
        start_line = max(
            start_line,
            max(1, _line_count(source, encoding=encoding) - tail_lines + 1),
        )
    end_line = line_to
    pid_token = f"[{int(pid)}]" if pid is not None else None

    for record in selected.segment_file(source, encoding=encoding):
        if record.end_line < start_line:
            continue
        if end_line is not None and record.start_line > end_line:
            continue
        if not _in_time_window(
            record,
            segmenter=selected,
            reference=reference,
            time_from=time_from,
            time_to=time_to,
        ):
            continue
        if pid_token is not None:
            header = record.text.split("\n", 1)[0]
            if (
                pid_token not in header
                and str(record.fields.get("pid") or "") != str(int(pid))
            ):
                continue

        if query is None:
            matched = True
        elif matcher is not None:
            matched = matcher.match(record.text)[0]
        else:
            matched = query in record.text
        if matched:
            yield record


__all__ = ["iter_matching_records"]
