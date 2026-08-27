# -*- coding: utf-8 -*-
"""Bounded, deterministic raw-context sampling.

Sampling is an observation primitive, not a diagnosis.  The Core sampler
freezes a source by default, scans it through a :class:`Segmenter`, and then
returns a small number of addressable record snippets.  It deliberately
returns generic records and coverage rather than making any claim about a
root cause or outcome.

The implementation uses a bounded output budget while keeping the scan
streaming.  A first pass establishes the actual scope and record count; a
second pass materialises only the selected records.  This makes the uniform
strategy reproducible without retaining the input in memory.
"""

from __future__ import annotations

import hashlib
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Mapping, Optional, Tuple, Union

from .segmenter import Segmenter, build_segmenter, detect_segmenter_kind
from .text_filter import (
    FilterError,
    parse_last_duration,
    parse_time_arg,
    record_timestamp,
    reference_datetime,
)


# These are hard Core limits.  Callers may request a smaller budget but may not
# bypass the limits and accidentally place an unbounded source in an Agent
# result.
MAX_SAMPLE_RECORDS = 100
MAX_SAMPLE_COUNT = MAX_SAMPLE_RECORDS  # descriptive compatibility alias
MAX_SAMPLE_CHARS = 20_000
DEFAULT_SAMPLE_COUNT = 10
DEFAULT_SAMPLE_CHARS = 8_000
SAMPLE_STRATEGIES = ("head-tail", "uniform")


class SampleError(ValueError):
    """Invalid or incomplete input for a Core sample."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _count_lines(path: Path) -> int:
    count = 0
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for _line in handle:
            count += 1
    return count


def _snapshot(path: Path) -> Path:
    """Freeze ``path`` into a same-source hidden directory."""

    root = path.parent / ".snapshots"
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S%f")
    suffix = path.suffix or ".log"
    destination = root / f"{path.stem}_{stamp}-{uuid.uuid4().hex[:8]}{suffix}"
    shutil.copy2(path, destination)
    return destination


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat(timespec="milliseconds") if value is not None else None


def _segmenter_and_name(
    source: Path,
    segmenter: Union[str, Segmenter, Mapping[str, Any], None],
) -> Tuple[Segmenter, str]:
    if isinstance(segmenter, Segmenter):
        return segmenter, str(getattr(segmenter, "name", type(segmenter).__name__))
    if isinstance(segmenter, Mapping):
        return build_segmenter(dict(segmenter)), "format"
    kind = str(segmenter or "auto").strip().lower()
    if kind == "auto":
        kind = detect_segmenter_kind(source)
        if isinstance(kind, dict):
            return build_segmenter(kind), "format:inferred"
    return build_segmenter(kind), kind


def _iter_records(path: Path, segmenter: Segmenter) -> Iterator[Any]:
    # Keep the generator boundary explicit: segmenters own record boundaries;
    # sampling never materialises the source.
    yield from segmenter.segment_file(path)


def _time_window(
    path: Path,
    segmenter: Segmenter,
    *,
    last: Optional[str],
    since: Optional[str],
    until: Optional[str],
) -> Tuple[datetime, Optional[datetime], Optional[datetime], Optional[str]]:
    """Resolve time scope with the same semantics as search and survey."""

    reference = reference_datetime(path, segmenter=segmenter)
    time_from: Optional[datetime] = None
    time_to: Optional[datetime] = None
    if last is not None:
        duration = parse_last_duration(last)
        latest: Optional[datetime] = None
        for record in _iter_records(path, segmenter):
            timestamp = record_timestamp(record, ref=reference, segmenter=segmenter)
            if timestamp is not None:
                # ``--last`` follows the physically last parsed timestamp,
                # matching the existing filter/survey contract.
                latest = timestamp
        if latest is None:
            raise FilterError("无法从日志解析时间戳，不能使用 --last")
        time_from = latest - duration
        time_to = latest
    if since is not None:
        parsed = parse_time_arg(since, ref=reference, segmenter=segmenter)
        time_from = parsed if time_from is None else max(time_from, parsed)
    if until is not None:
        parsed = parse_time_arg(until, ref=reference, segmenter=segmenter)
        time_to = parsed if time_to is None else min(time_to, parsed)
    if time_from is not None and time_to is not None and time_from > time_to:
        raise FilterError(
            f"时间窗口无效: time_from={time_from.isoformat()} > time_to={time_to.isoformat()}"
        )
    return reference, time_from, time_to, last


def _in_window(
    timestamp: Optional[datetime],
    *,
    time_from: Optional[datetime],
    time_to: Optional[datetime],
) -> bool:
    if time_from is None and time_to is None:
        return True
    # A record without a parseable timestamp is retained conservatively.  The
    # resulting timestamp parse coverage and warning make that limitation
    # visible to callers instead of silently discarding context.
    if timestamp is None:
        return True
    if time_from is not None and timestamp < time_from:
        return False
    if time_to is not None and timestamp > time_to:
        return False
    return True


def _selected_positions(total: int, count: int, strategy: str) -> List[int]:
    """Return deterministic zero-based positions within the scoped stream."""

    if total <= 0 or count <= 0:
        return []
    target = min(total, count)
    if target >= total:
        return list(range(total))
    if strategy == "head-tail":
        head = (target + 1) // 2
        tail = target // 2
        positions = list(range(head))
        positions.extend(range(total - tail, total))
        return sorted(set(positions))
    if strategy == "uniform":
        if target == 1:
            return [0]
        # Include both endpoints and distribute the remaining positions by
        # integer interpolation.  Integer arithmetic makes this independent
        # of floating-point rounding and therefore stable across Python hosts.
        return sorted({(index * (total - 1)) // (target - 1) for index in range(target)})
    raise SampleError(
        f"未知 sample strategy {strategy!r}（可选: {', '.join(SAMPLE_STRATEGIES)}）"
    )


@dataclass
class SampleSummary:
    """Serializable Core sampling result, independent of Runtime schemas."""

    original_source: Path
    work_input: Path
    snapshot_path: Optional[Path]
    source_sha256: str
    segmenter: str
    strategy: str
    snapshot: bool
    requested_count: int
    requested_max_chars: int
    scan_lines: int
    scan_records: int
    scoped_lines: int
    scoped_records: int
    timestamped_records: int
    unparsed_timestamp_records: int
    observed_from: Optional[datetime]
    observed_to: Optional[datetime]
    scoped_from: Optional[datetime]
    scoped_to: Optional[datetime]
    time_from: Optional[datetime]
    time_to: Optional[datetime]
    scope_last: Optional[str]
    selected_records: int
    returned_records: int
    selection_omitted_records: int
    output_omitted_records: int
    returned_chars: int
    omitted_chars: int
    truncated_records: int
    samples: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def sampled_records(self) -> int:
        """Compatibility/readability alias for records returned inline."""

        return self.returned_records

    def _omissions(self) -> List[Dict[str, Any]]:
        omissions: List[Dict[str, Any]] = []
        outside_scope = max(0, self.scan_records - self.scoped_records)
        if outside_scope:
            omissions.append(
                {
                    "kind": "time_scope",
                    "count": outside_scope,
                    "detail": "records outside the requested time scope were not sampled",
                }
            )
        if self.unparsed_timestamp_records and (self.time_from is not None or self.time_to is not None):
            omissions.append(
                {
                    "kind": "unparsed_timestamp",
                    "count": self.unparsed_timestamp_records,
                    "detail": "records without timestamps were retained conservatively in the time scope",
                }
            )
        if self.selection_omitted_records:
            omissions.append(
                {
                    "kind": "sampling",
                    "count": self.selection_omitted_records,
                    "detail": f"strategy={self.strategy}; requested count is bounded",
                }
            )
        if self.output_omitted_records:
            omissions.append(
                {
                    "kind": "max_chars",
                    "count": self.output_omitted_records,
                    "detail": "selected records after the character budget were withheld",
                }
            )
        if self.truncated_records:
            omissions.append(
                {
                    "kind": "record_text_truncation",
                    "count": self.truncated_records,
                    "detail": "selected record text was clipped at max_chars",
                }
            )
        if self.omitted_chars:
            omissions.append(
                {
                    "kind": "characters",
                    "count": self.omitted_chars,
                    "detail": "characters not returned because of max_chars",
                }
            )
        return omissions

    def to_dict(self) -> Dict[str, Any]:
        timestamp_coverage = (
            self.timestamped_records / self.scan_records if self.scan_records else 0.0
        )
        selection_omitted = self.selection_omitted_records
        output_omitted = self.output_omitted_records
        coverage: Dict[str, Any] = {
            "scan_lines": self.scan_lines,
            "scanned_lines": self.scan_lines,
            "scan_records": self.scan_records,
            "scanned_records": self.scan_records,
            "scoped_lines": self.scoped_lines,
            "scoped_records": self.scoped_records,
            "records_scoped": self.scoped_records,
            "timestamped_records": self.timestamped_records,
            "unparsed_timestamp_records": self.unparsed_timestamp_records,
            "timestamp_parse_coverage": round(timestamp_coverage, 6),
            "selected_records": self.selected_records,
            "sampled_records": self.returned_records,
            "records_returned": self.returned_records,
            "records_omitted": selection_omitted + output_omitted,
            "scope_omitted_records": max(0, self.scan_records - self.scoped_records),
            "total_omitted_records": max(
                0,
                (self.scan_records - self.scoped_records)
                + selection_omitted
                + output_omitted,
            ),
            "selection_omitted_records": selection_omitted,
            "output_omitted_records": output_omitted,
            "returned_chars": self.returned_chars,
            "sample_chars": self.returned_chars,
            "omitted_chars": self.omitted_chars,
            "max_chars": self.requested_max_chars,
            "max_sample_chars": MAX_SAMPLE_CHARS,
            "requested_count": self.requested_count,
            "max_sample_records": MAX_SAMPLE_RECORDS,
            "truncated_records": self.truncated_records,
            "truncated": bool(self.truncated_records or output_omitted),
            "selection_truncated": bool(selection_omitted),
            "omissions": self._omissions(),
            "scope": {
                "last": self.scope_last,
                "since": _iso(self.time_from),
                "until": _iso(self.time_to),
                "time_from": _iso(self.time_from),
                "time_to": _iso(self.time_to),
            },
        }
        data = {
            "source": str(self.original_source),
            "work_input": str(self.work_input),
            "snapshot_path": str(self.snapshot_path) if self.snapshot_path else None,
            "source_sha256": self.source_sha256,
            "segmenter": self.segmenter,
            "strategy": self.strategy,
            "snapshot": self.snapshot,
            "samples": list(self.samples),
            "time_range": {
                "from": _iso(self.observed_from),
                "to": _iso(self.observed_to),
                "scoped_from": _iso(self.scoped_from),
                "scoped_to": _iso(self.scoped_to),
                "timestamped_records": self.timestamped_records,
                "unparsed_records": self.unparsed_timestamp_records,
            },
        }
        return {
            "source": str(self.original_source),
            "work_input": str(self.work_input),
            "snapshot_path": str(self.snapshot_path) if self.snapshot_path else None,
            "source_sha256": self.source_sha256,
            "segmenter": self.segmenter,
            "strategy": self.strategy,
            "snapshot": self.snapshot,
            "requested_count": self.requested_count,
            "requested_max_chars": self.requested_max_chars,
            "coverage": coverage,
            "data": data,
        }


def sample_file(
    input_path: Union[str, Path],
    *,
    strategy: str = "head-tail",
    count: int = DEFAULT_SAMPLE_COUNT,
    max_chars: int = DEFAULT_SAMPLE_CHARS,
    snapshot: bool = True,
    segmenter: Union[str, Segmenter, Mapping[str, Any], None] = "auto",
    last: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
) -> SampleSummary:
    """Return bounded raw record context from one source.

    ``count`` is the total number of records selected by the strategy, not a
    per-side budget.  ``max_chars`` is an aggregate character budget for the
    returned snippets.  Both budgets are hard limits and any omission or
    clipping is represented in ``coverage.omissions``.
    """

    source = Path(input_path).expanduser().resolve()
    if not source.is_file():
        raise SampleError(f"日志文件不存在或不是文件: {source}")
    try:
        requested_count = int(count)
        requested_max_chars = int(max_chars)
    except (TypeError, ValueError) as exc:
        raise SampleError("count 和 max_chars 必须是整数") from exc
    if requested_count <= 0:
        raise SampleError("count 必须大于 0")
    if requested_count > MAX_SAMPLE_RECORDS:
        raise SampleError(f"count 不能超过 Core 上限 {MAX_SAMPLE_RECORDS}")
    if requested_max_chars <= 0:
        raise SampleError("max_chars 必须大于 0")
    if requested_max_chars > MAX_SAMPLE_CHARS:
        raise SampleError(f"max_chars 不能超过 Core 上限 {MAX_SAMPLE_CHARS}")
    normalized_strategy = str(strategy or "").strip().lower().replace("_", "-")
    if normalized_strategy not in SAMPLE_STRATEGIES:
        raise SampleError(
            f"未知 sample strategy {strategy!r}（可选: {', '.join(SAMPLE_STRATEGIES)}）"
        )

    work_input = _snapshot(source) if snapshot else source
    snapshot_path = work_input if snapshot else None
    digest = _sha256(work_input)
    selected_segmenter, segmenter_name = _segmenter_and_name(work_input, segmenter)
    reference, time_from, time_to, scope_last = _time_window(
        work_input,
        selected_segmenter,
        last=last,
        since=since,
        until=until,
    )

    scan_lines = _count_lines(work_input)
    scan_records = 0
    scoped_lines = 0
    scoped_records = 0
    timestamped_records = 0
    unparsed_timestamp_records = 0
    observed_from: Optional[datetime] = None
    observed_to: Optional[datetime] = None
    scoped_from: Optional[datetime] = None
    scoped_to: Optional[datetime] = None

    # Pass one computes complete scan/scope coverage and the stable record
    # count needed by both sampling strategies.
    for record in _iter_records(work_input, selected_segmenter):
        scan_records += 1
        timestamp = record_timestamp(record, ref=reference, segmenter=selected_segmenter)
        if timestamp is None:
            unparsed_timestamp_records += 1
        else:
            timestamped_records += 1
            if observed_from is None or timestamp < observed_from:
                observed_from = timestamp
            if observed_to is None or timestamp > observed_to:
                observed_to = timestamp
        if not _in_window(timestamp, time_from=time_from, time_to=time_to):
            continue
        scoped_records += 1
        scoped_lines += int(getattr(record, "line_count", 0) or 0)
        if timestamp is not None:
            if scoped_from is None or timestamp < scoped_from:
                scoped_from = timestamp
            if scoped_to is None or timestamp > scoped_to:
                scoped_to = timestamp

    positions = _selected_positions(scoped_records, requested_count, normalized_strategy)
    selected_set = set(positions)
    selected_records = len(positions)
    selection_omitted_records = max(0, scoped_records - selected_records)
    samples: List[Dict[str, Any]] = []
    returned_chars = 0
    omitted_chars = 0
    truncated_records = 0
    output_omitted_records = 0
    scoped_index = 0

    # Pass two emits only selected records.  The character budget is applied
    # before appending each snippet and every withheld/clipped item is counted.
    for record in _iter_records(work_input, selected_segmenter):
        timestamp = record_timestamp(record, ref=reference, segmenter=selected_segmenter)
        if not _in_window(timestamp, time_from=time_from, time_to=time_to):
            continue
        if scoped_index not in selected_set:
            scoped_index += 1
            continue
        raw_text = str(getattr(record, "text", ""))
        remaining = requested_max_chars - returned_chars
        if remaining <= 0:
            output_omitted_records += 1
            omitted_chars += len(raw_text)
            scoped_index += 1
            continue
        text = raw_text
        if len(text) > remaining:
            text = text[:remaining]
            omitted_chars += len(raw_text) - len(text)
            truncated_records += 1
        returned_chars += len(text)
        samples.append(
            {
                "text": text,
                "start_line": int(getattr(record, "start_line", 0) or 0),
                "end_line": int(getattr(record, "end_line", 0) or 0),
                "timestamp": _iso(timestamp),
                "truncated": len(text) < len(raw_text),
            }
        )
        scoped_index += 1

    return SampleSummary(
        original_source=source,
        work_input=work_input,
        snapshot_path=snapshot_path,
        source_sha256=digest,
        segmenter=segmenter_name,
        strategy=normalized_strategy,
        snapshot=snapshot,
        requested_count=requested_count,
        requested_max_chars=requested_max_chars,
        scan_lines=scan_lines,
        scan_records=scan_records,
        scoped_lines=scoped_lines,
        scoped_records=scoped_records,
        timestamped_records=timestamped_records,
        unparsed_timestamp_records=unparsed_timestamp_records,
        observed_from=observed_from,
        observed_to=observed_to,
        scoped_from=scoped_from,
        scoped_to=scoped_to,
        time_from=time_from,
        time_to=time_to,
        scope_last=scope_last,
        selected_records=selected_records,
        returned_records=len(samples),
        selection_omitted_records=selection_omitted_records,
        output_omitted_records=output_omitted_records,
        returned_chars=returned_chars,
        omitted_chars=omitted_chars,
        truncated_records=truncated_records,
        samples=samples,
    )


def sample(*args: Any, **kwargs: Any) -> SampleSummary:
    """Short public alias for :func:`sample_file`."""

    return sample_file(*args, **kwargs)


# Keep Core and Runtime terminology aligned without maintaining a second
# implementation.  The top-level Runtime API also exposes this alias.
peek = sample


__all__ = [
    "DEFAULT_SAMPLE_CHARS",
    "DEFAULT_SAMPLE_COUNT",
    "MAX_SAMPLE_CHARS",
    "MAX_SAMPLE_COUNT",
    "MAX_SAMPLE_RECORDS",
    "SAMPLE_STRATEGIES",
    "SampleError",
    "SampleSummary",
    "peek",
    "sample",
    "sample_file",
]
