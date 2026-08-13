# -*- coding: utf-8 -*-
"""Bounded, streaming log survey primitives.

The survey engine is deliberately a Core primitive.  It only consumes a
``Segmenter`` stream and standard-library data structures; it does not know
about the Runtime AgentResult envelope or any application/device format.

Survey is descriptive rather than diagnostic.  It reports a bounded overview
of records in a source: timestamp coverage, generic severity levels, repeated
record shapes, and busy minute buckets.  It never turns those observations
into a root-cause conclusion.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Mapping, Optional, Tuple, Union

from .segmenter import Segmenter, build_segmenter, detect_segmenter_kind
from .text_filter import (
    FilterError,
    _normalize_for_template,
    parse_last_duration,
    parse_time_arg,
    record_timestamp,
    reference_datetime,
)


# The caps are part of the Core contract.  A caller may request a smaller
# budget, but an accidental unbounded request must not turn survey into a
# whole-file aggregation.
MAX_TEMPLATES = 500
MAX_SAMPLES_PER_TEMPLATE = 20
MAX_SPIKE_BUCKETS = 60
MAX_LEVELS = 32
MAX_SAMPLE_CHARS = 300
MAX_TEMPLATE_CHARS = 500

_LEVEL_RE = re.compile(
    r"\b(?P<level>TRACE|VERBOSE|DEBUG|INFO|NOTICE|WARN(?:ING)?|ERR(?:OR)?|"
    r"FATAL|CRIT(?:ICAL)?|PANIC)\b",
    re.IGNORECASE,
)


class SurveyError(ValueError):
    """Invalid or incomplete input for a Core survey."""


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
    """Freeze a source before scanning it.

    The destination follows the existing filter convention so EvidencePointers
    can share the same snapshot boundary.  A short UUID avoids collisions when
    two surveys start within the same microsecond.
    """

    root = path.parent / ".snapshots"
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S%f")
    suffix = path.suffix or ".log"
    destination = root / f"{path.stem}_{stamp}-{uuid.uuid4().hex[:8]}{suffix}"
    shutil.copy2(path, destination)
    return destination


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat(timespec="milliseconds") if value is not None else None


def _normalise_level(value: object) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    upper = text.upper()
    aliases = {
        "WARNING": "WARN",
        "ERR": "ERROR",
        "CRIT": "CRITICAL",
    }
    return aliases.get(upper, upper)[:32]


def _record_level(record: Any) -> Optional[str]:
    fields = getattr(record, "fields", {}) or {}
    for key in ("level", "lvl", "severity"):
        level = _normalise_level(fields.get(key))
        if level:
            return level
    match = _LEVEL_RE.search(str(getattr(record, "text", "")))
    return _normalise_level(match.group("level")) if match else None


@dataclass
class _Bucket:
    key: str
    count: int
    error: int = 0
    first_line: Optional[int] = None
    first_end_line: Optional[int] = None
    first_timestamp: Optional[str] = None
    samples: List[Dict[str, Any]] | None = None


class _SpaceSaving:
    """A deterministic bounded heavy-hitter counter.

    Keeping at most ``capacity`` buckets means memory is independent of input
    size.  On eviction the new bucket inherits the evicted minimum count; this
    is the standard space-saving approximation and is surfaced to callers via
    the ``approximate`` flag in the summary.
    """

    def __init__(self, capacity: int, *, sample_limit: int = 0) -> None:
        self.capacity = max(1, int(capacity))
        self.sample_limit = max(0, int(sample_limit))
        self._buckets: Dict[str, _Bucket] = {}
        self.evictions = 0
        self._sequence = 0
        self._order: Dict[str, int] = {}

    @property
    def retained(self) -> int:
        return len(self._buckets)

    def add(
        self,
        key: str,
        *,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
        timestamp: Optional[datetime] = None,
        text: Optional[str] = None,
    ) -> None:
        key = str(key)
        bucket = self._buckets.get(key)
        if bucket is None:
            if len(self._buckets) >= self.capacity:
                victim_key, victim = min(
                    self._buckets.items(),
                    key=lambda item: (item[1].count, self._order[item[0]]),
                )
                del self._buckets[victim_key]
                self._order.pop(victim_key, None)
                count = victim.count + 1
                error = victim.count
                self.evictions += 1
            else:
                count = 1
                error = 0
            bucket = _Bucket(
                key=key,
                count=count,
                error=error,
                samples=[] if self.sample_limit else None,
            )
            self._buckets[key] = bucket
            self._order[key] = self._sequence
            self._sequence += 1
        else:
            bucket.count += 1

        if bucket.first_line is None and start_line is not None:
            bucket.first_line = int(start_line)
            bucket.first_end_line = int(end_line) if end_line is not None else int(start_line)
            bucket.first_timestamp = _iso(timestamp)
        if self.sample_limit and text is not None and bucket.samples is not None:
            if len(bucket.samples) < self.sample_limit:
                bucket.samples.append(
                    {
                        "text": str(text).strip()[:MAX_SAMPLE_CHARS],
                        "start_line": int(start_line) if start_line is not None else None,
                        "end_line": int(end_line) if end_line is not None else None,
                        "timestamp": _iso(timestamp),
                    }
                )

    def ordered(self) -> List[_Bucket]:
        return sorted(
            self._buckets.values(),
            key=lambda bucket: (-bucket.count, bucket.key),
        )


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
    return build_segmenter(kind), kind


def _iter_records(path: Path, segmenter: Segmenter) -> Iterator[Any]:
    # Keep the generator boundary explicit: Segmenter owns parsing and records
    # are consumed one at a time; survey never materialises the source.
    yield from segmenter.segment_file(path)


def _time_window(
    path: Path,
    segmenter: Segmenter,
    *,
    last: Optional[str],
    since: Optional[str],
    until: Optional[str],
) -> Tuple[datetime, Optional[datetime], Optional[datetime], Optional[str]]:
    """Resolve the requested window using the same semantics as filtering."""

    reference = reference_datetime(path, segmenter=segmenter)
    time_from: Optional[datetime] = None
    time_to: Optional[datetime] = None
    if last is not None:
        duration = parse_last_duration(last)
        latest: Optional[datetime] = None
        for record in _iter_records(path, segmenter):
            timestamp = record_timestamp(record, ref=reference, segmenter=segmenter)
            # Keep the same ``--last`` meaning as the filter engine: the last
            # timestamp physically encountered in the stream, even if a log
            # contains an out-of-order record near its tail.
            if timestamp is not None:
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
    # Match filter semantics: a record with no parsed timestamp is retained
    # conservatively, and coverage warns the caller that the scope is partial.
    if timestamp is None:
        return True
    if time_from is not None and timestamp < time_from:
        return False
    if time_to is not None and timestamp > time_to:
        return False
    return True


@dataclass
class SurveySummary:
    """Serializable Core survey output, independent of Runtime schemas."""

    original_source: Path
    work_input: Path
    snapshot_path: Optional[Path]
    source_sha256: str
    segmenter: str
    snapshot: bool
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
    max_templates: int
    samples_per_template: int
    levels: List[Dict[str, Any]]
    templates: List[Dict[str, Any]]
    spikes: List[Dict[str, Any]]
    template_evictions: int
    spike_evictions: int
    level_evictions: int
    truncated_template_records: int

    def to_dict(self) -> Dict[str, Any]:
        timestamp_coverage = (
            self.timestamped_records / self.scan_records if self.scan_records else 0.0
        )
        scope = {
            "last": self.scope_last,
            "since": _iso(self.time_from),
            "until": _iso(self.time_to),
            "time_from": _iso(self.time_from),
            "time_to": _iso(self.time_to),
        }
        return {
            "source": str(self.original_source),
            "work_input": str(self.work_input),
            "snapshot_path": str(self.snapshot_path) if self.snapshot_path else None,
            "source_sha256": self.source_sha256,
            "segmenter": self.segmenter,
            "snapshot": self.snapshot,
            "coverage": {
                "scan_lines": self.scan_lines,
                "scanned_lines": self.scan_lines,
                "lines_scanned": self.scan_lines,
                "scan_records": self.scan_records,
                "scanned_records": self.scan_records,
                "records_scanned": self.scan_records,
                "scoped_lines": self.scoped_lines,
                "lines_scoped": self.scoped_lines,
                "scoped_records": self.scoped_records,
                "records_scoped": self.scoped_records,
                "timestamped_records": self.timestamped_records,
                "unparsed_timestamp_records": self.unparsed_timestamp_records,
                "timestamp_parse_coverage": round(timestamp_coverage, 6),
                "timestamp_parse": {
                    "parsed_records": self.timestamped_records,
                    "unparsed_records": self.unparsed_timestamp_records,
                    "coverage": round(timestamp_coverage, 6),
                },
                "scope": scope,
                "templates_retained": len(self.templates),
                "templates_memory_limit": self.max_templates,
                "max_templates": self.max_templates,
                "samples_per_template": self.samples_per_template,
                "sample_chars_limit": MAX_SAMPLE_CHARS,
                "template_chars_limit": MAX_TEMPLATE_CHARS,
                "truncated_template_records": self.truncated_template_records,
                "template_evictions": self.template_evictions,
                "spike_buckets_retained": len(self.spikes),
                "spike_memory_limit": MAX_SPIKE_BUCKETS,
                "spike_evictions": self.spike_evictions,
                "levels_retained": len(self.levels),
                "levels_memory_limit": MAX_LEVELS,
                "level_evictions": self.level_evictions,
            },
            "data": {
                "time_range": {
                    "from": _iso(self.observed_from),
                    "to": _iso(self.observed_to),
                    "scoped_from": _iso(self.scoped_from),
                    "scoped_to": _iso(self.scoped_to),
                    "timestamped_records": self.timestamped_records,
                    "unparsed_records": self.unparsed_timestamp_records,
                },
                "levels": self.levels,
                "top_templates": self.templates,
                "spikes": self.spikes,
            },
        }


def survey_file(
    input_path: Union[str, Path],
    *,
    snapshot: bool = True,
    segmenter: Union[str, Segmenter, Mapping[str, Any], None] = "auto",
    last: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    max_templates: int = 20,
    samples_per_template: int = 2,
) -> SurveySummary:
    """Stream a bounded overview of one text source.

    ``max_templates`` and ``samples_per_template`` are hard memory budgets,
    subject to Core-wide caps.  The source is snapshotted by default; callers
    opting out receive the same descriptive summary but must not treat samples
    as immutable evidence.
    """

    source = Path(input_path).expanduser().resolve()
    if not source.is_file():
        raise SurveyError(f"日志文件不存在或不是文件: {source}")
    try:
        requested_templates = int(max_templates)
        requested_samples = int(samples_per_template)
    except (TypeError, ValueError) as exc:
        raise SurveyError("max_templates 和 samples_per_template 必须是整数") from exc
    if requested_templates <= 0:
        raise SurveyError("max_templates 必须大于 0")
    if requested_samples < 0:
        raise SurveyError("samples_per_template 不能小于 0")
    if requested_templates > MAX_TEMPLATES:
        raise SurveyError(
            f"max_templates 不能超过 Core 上限 {MAX_TEMPLATES}"
        )
    if requested_samples > MAX_SAMPLES_PER_TEMPLATE:
        raise SurveyError(
            f"samples_per_template 不能超过 Core 上限 {MAX_SAMPLES_PER_TEMPLATE}"
        )

    work_input = _snapshot(source) if snapshot else source
    snapshot_path = work_input if snapshot else None
    digest = _sha256(work_input)
    selected, segmenter_name = _segmenter_and_name(work_input, segmenter)
    reference, time_from, time_to, scope_last = _time_window(
        work_input,
        selected,
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

    template_counter = _SpaceSaving(
        requested_templates,
        sample_limit=requested_samples,
    )
    spike_counter = _SpaceSaving(MAX_SPIKE_BUCKETS)
    level_counter = _SpaceSaving(MAX_LEVELS)
    truncated_template_records = 0

    for record in _iter_records(work_input, selected):
        scan_records += 1
        timestamp = record_timestamp(record, ref=reference, segmenter=selected)
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

        level = _record_level(record)
        if level:
            level_counter.add(level)
        template = _normalize_for_template(
            str(getattr(record, "text", "")),
            normalizers=selected.template_normalizers,
        )
        if len(template) > MAX_TEMPLATE_CHARS:
            template = template[:MAX_TEMPLATE_CHARS]
            truncated_template_records += 1
        template_counter.add(
            template,
            start_line=getattr(record, "start_line", None),
            end_line=getattr(record, "end_line", None),
            timestamp=timestamp,
            text=str(getattr(record, "text", "")),
        )
        if timestamp is not None:
            spike_counter.add(timestamp.strftime("%Y-%m-%d %H:%M"))

    templates: List[Dict[str, Any]] = []
    for bucket in template_counter.ordered():
        row: Dict[str, Any] = {
            "template": bucket.key,
            "count": bucket.count,
            "approximate": bucket.error > 0,
        }
        if bucket.error:
            row["count_lower_bound"] = bucket.count - bucket.error
            row["count_error"] = bucket.error
        if bucket.first_timestamp is not None:
            row["first_seen"] = bucket.first_timestamp
        if requested_samples:
            row["samples"] = list(bucket.samples or [])
        templates.append(row)

    levels = [
        {
            "level": bucket.key,
            "count": bucket.count,
            "approximate": bucket.error > 0,
            **(
                {
                    "count_lower_bound": bucket.count - bucket.error,
                    "count_error": bucket.error,
                }
                if bucket.error
                else {}
            ),
        }
        for bucket in level_counter.ordered()
    ]
    spikes = [
        {
            "minute": bucket.key,
            "count": bucket.count,
            "approximate": bucket.error > 0,
            **(
                {
                    "count_lower_bound": bucket.count - bucket.error,
                    "count_error": bucket.error,
                }
                if bucket.error
                else {}
            ),
        }
        for bucket in spike_counter.ordered()
    ]

    return SurveySummary(
        original_source=source,
        work_input=work_input,
        snapshot_path=snapshot_path,
        source_sha256=digest,
        segmenter=segmenter_name,
        snapshot=snapshot,
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
        max_templates=requested_templates,
        samples_per_template=requested_samples,
        levels=levels,
        templates=templates,
        spikes=spikes,
        template_evictions=template_counter.evictions,
        spike_evictions=spike_counter.evictions,
        level_evictions=level_counter.evictions,
        truncated_template_records=truncated_template_records,
    )


def survey(*args: Any, **kwargs: Any) -> SurveySummary:
    """Short public alias for :func:`survey_file`."""

    return survey_file(*args, **kwargs)


__all__ = [
    "MAX_LEVELS",
    "MAX_SAMPLES_PER_TEMPLATE",
    "MAX_SAMPLE_CHARS",
    "MAX_SPIKE_BUCKETS",
    "MAX_TEMPLATES",
    "MAX_TEMPLATE_CHARS",
    "SurveyError",
    "SurveySummary",
    "survey",
    "survey_file",
]
