"""Shared JSONL semantic decoding used by Record and streaming physical plans.

This module owns the meaning of JsonLineSegmenter's normalized timestamp,
level, and message aliases. Callers that already decoded a JSON object can
reuse the exact same semantic extraction without re-running json.loads or
constructing a Record. That keeps physical-plan optimizations semantically
identical to canonical segmentation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Mapping


JSON_TIME_KEYS = ("ts", "time", "timestamp", "@timestamp", "datetime", "eventTime")
JSON_LEVEL_KEYS = ("level", "lvl", "severity")
JSON_MSG_KEYS = ("msg", "message", "content", "text")


@dataclass(frozen=True)
class JsonLineSemantics:
    timestamp: datetime | None
    fields: dict[str, Any]


def normalize_timestamp(value: datetime) -> datetime:
    """Return the Core comparison form for a parsed timestamp."""

    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=None)
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def strptime_timestamp(raw: str, fmt: str) -> datetime:
    """Parse a format timestamp without triggering yearless deprecations."""

    has_year = any(token in fmt for token in ("%Y", "%y", "%G"))
    if has_year:
        return datetime.strptime(raw, fmt)
    return datetime.strptime(f"{raw};1900", f"{fmt};%Y")


def _parse_timestamp(value: Any) -> tuple[datetime | None, str | None]:
    if value is None:
        return None, None

    raw_display = repr(value)
    if len(raw_display) > 160:
        raw_display = raw_display[:157] + "..."

    if isinstance(value, bool):
        return None, "布尔值不是有效的数值时间戳"

    if isinstance(value, (int, float)):
        try:
            numeric_ts = float(value)
            if not math.isfinite(numeric_ts):
                raise ValueError("时间戳必须是有限数值")
            seconds = numeric_ts / 1000 if abs(numeric_ts) > 1e11 else numeric_ts
            parsed = datetime.fromtimestamp(seconds, tz=timezone.utc)
            return normalize_timestamp(parsed), None
        except (OverflowError, OSError, ValueError) as exc:
            return None, f"无法解析数值时间戳 {raw_display}: {exc}"

    if isinstance(value, str):
        raw = value.strip()
        iso_raw = raw[:-1] + "+00:00" if raw[-1:].upper() == "Z" else raw
        try:
            return normalize_timestamp(datetime.fromisoformat(iso_raw)), None
        except ValueError:
            pass

        for fmt in (
            "%Y-%m-%dT%H:%M:%S.%fZ",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S.%f%z",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S.%f%z",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M:%S%z",
        ):
            try:
                return normalize_timestamp(strptime_timestamp(raw, fmt)), None
            except ValueError:
                continue
        return None, f"无法解析字符串时间戳 {raw_display}"

    return None, f"时间戳类型不受支持: {type(value).__name__}"


@lru_cache(maxsize=512, typed=True)
def _parse_scalar_timestamp(
    value: str | int | float | bool | None,
) -> tuple[datetime | None, str | None]:
    """Cache the pure parse result for repeated scalar timestamp values.

    JSONL telemetry commonly repeats a low-cardinality clock value (for
    example ``"16:04"``) across thousands of records.  Parsing that value is
    deterministic, including its failure result, so a bounded process-local
    cache preserves semantics while avoiding repeated ``strptime`` fallback
    work.  Non-scalar JSON values intentionally bypass this helper because
    they are not guaranteed to be hashable.
    """

    return _parse_timestamp(value)


def extract_jsonline_semantics(
    obj: Mapping[str, Any],
    *,
    time_field: str | None = None,
    level_field: str | None = None,
    msg_field: str | None = None,
) -> JsonLineSemantics:
    """Extract canonical JsonLineSegmenter aliases from an already-decoded object."""

    raw_timestamp: Any = None
    if time_field:
        raw_timestamp = obj.get(time_field)
    else:
        for key in JSON_TIME_KEYS:
            if key in obj:
                raw_timestamp = obj.get(key)
                break

    if raw_timestamp is None or type(raw_timestamp) in {str, int, float, bool}:
        timestamp, timestamp_parse_error = _parse_scalar_timestamp(raw_timestamp)
    else:
        timestamp, timestamp_parse_error = _parse_timestamp(raw_timestamp)
    fields: dict[str, Any] = {}
    if timestamp_parse_error is not None:
        fields["timestamp_parse_error"] = timestamp_parse_error

    level_keys = (level_field,) if level_field else JSON_LEVEL_KEYS
    for key in level_keys:
        if key in obj:
            fields["level"] = obj[key]
            break

    message_keys = (msg_field,) if msg_field else JSON_MSG_KEYS
    for key in message_keys:
        if key in obj:
            fields["msg"] = str(obj[key])[:200]
            break

    return JsonLineSemantics(timestamp=timestamp, fields=fields)


__all__ = [
    "JSON_LEVEL_KEYS",
    "JSON_MSG_KEYS",
    "JSON_TIME_KEYS",
    "JsonLineSemantics",
    "extract_jsonline_semantics",
    "normalize_timestamp",
    "strptime_timestamp",
]
