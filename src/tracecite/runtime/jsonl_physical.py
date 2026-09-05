"""Shared JSONL physical-plan primitives.

This module contains mechanics that are safe to reuse from both Evidence Compute
and Evidence Shell.  It does not choose investigations or hypotheses.  It only
resolves fields from an already-decoded JSON line and keeps bounded Top-K state
without constructing canonical Record objects.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from tracecite_core.jsonline_semantics import JsonLineSemantics

from .evidence_shell_fast_jsonl import _SPECIAL_FIELDS, _matches, _value
from .source_versions import SourceSegment


SEMANTIC_JSON_FIELDS = frozenset({"timestamp", "level", "msg"})
RAW_FALLBACK_FIELDS = frozenset({"parse_error", "raw_fallback"})


def predicate_field(stage: Any) -> str | None:
    if stage.command in {"where", "exists", "missing"} and stage.args:
        return str(stage.args[0])
    return None


def referenced_fields(stages: Sequence[Any]) -> set[str]:
    result: set[str] = set()
    for stage in stages:
        field = predicate_field(stage)
        if field is not None:
            result.add(field)
    return result


def split_predicates(stages: Sequence[Any]) -> tuple[list[Any], list[Any]]:
    raw = [
        stage
        for stage in stages
        if stage.command in {"search", "regex", "exclude", "exclude-regex", "all"}
    ]
    fields = [stage for stage in stages if stage not in raw]
    return raw, fields


def special_field_value(
    raw: str,
    field: str,
    *,
    semantics: JsonLineSemantics | None,
    segment: SourceSegment,
    local_start_line: int,
    local_end_line: int,
) -> Any:
    key = str(field).strip()
    global_start = segment.line_base + max(0, local_start_line - 1)
    global_end = segment.line_base + max(0, local_end_line - 1)
    if key == "text":
        return raw.rstrip("\n")
    if key in {"line", "start_line", "global_line"}:
        return global_start
    if key == "end_line":
        return global_end
    if key == "local_start_line":
        return local_start_line
    if key == "local_end_line":
        return local_end_line
    if key == "timestamp":
        if semantics is None or semantics.timestamp is None:
            return None
        return semantics.timestamp.isoformat(timespec="milliseconds")
    if key == "source":
        return segment.path
    if key in {"level", "msg"}:
        return semantics.fields.get(key) if semantics is not None else None
    return None


def field_value(
    obj: Mapping[str, Any],
    raw: str,
    field: str,
    *,
    semantics: JsonLineSemantics | None,
    segment: SourceSegment,
    local_start_line: int,
    local_end_line: int,
) -> Any:
    if field in _SPECIAL_FIELDS:
        return special_field_value(
            raw,
            field,
            semantics=semantics,
            segment=segment,
            local_start_line=local_start_line,
            local_end_line=local_end_line,
        )
    return _value(obj, field)


def field_predicate_matches(
    obj: Mapping[str, Any],
    raw: str,
    stage: Any,
    *,
    semantics: JsonLineSemantics | None,
    segment: SourceSegment,
    local_start_line: int,
    local_end_line: int,
) -> bool:
    field = predicate_field(stage)
    if field in _SPECIAL_FIELDS:
        value = field_value(
            obj,
            raw,
            str(field),
            semantics=semantics,
            segment=segment,
            local_start_line=local_start_line,
            local_end_line=local_end_line,
        )
        return _matches({str(field): value}, raw, stage)
    return _matches(obj, raw, stage)


def topk_sort_key(value: Any, *, numeric: bool) -> tuple[int, float | str]:
    if value is None:
        return (1, 0.0 if numeric else "")
    if numeric:
        try:
            return (0, float(str(value).strip()))
        except ValueError:
            return (1, 0.0)
    return (0, str(value))


def _better(
    key: tuple[int, float | str],
    ordinal: int,
    other_key: tuple[int, float | str],
    other_ordinal: int,
    *,
    descending: bool,
) -> bool:
    if key != other_key:
        return key > other_key if descending else key < other_key
    return ordinal < other_ordinal


@dataclass
class _WorstFirstEntry:
    key: tuple[int, float | str]
    ordinal: int
    value: Any
    descending: bool

    def __lt__(self, other: "_WorstFirstEntry") -> bool:
        # heapq keeps the smallest item at index 0.  We intentionally define
        # "smaller" as "worse" so the root is always the candidate to evict.
        return _better(
            other.key,
            other.ordinal,
            self.key,
            self.ordinal,
            descending=self.descending,
        )


class FixedCapacityTopK:
    """Stable O(N log K) Top-K accumulator with at most K retained values."""

    def __init__(self, limit: int, *, descending: bool) -> None:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("Top-K limit must be a positive integer")
        self.limit = limit
        self.descending = bool(descending)
        self._heap: list[_WorstFirstEntry] = []
        self._ordinal = 0

    @property
    def retained(self) -> int:
        return len(self._heap)

    def add(self, key: tuple[int, float | str], value: Any) -> None:
        self._ordinal += 1
        candidate = _WorstFirstEntry(
            key=key,
            ordinal=self._ordinal,
            value=value,
            descending=self.descending,
        )
        if len(self._heap) < self.limit:
            heapq.heappush(self._heap, candidate)
            return
        worst = self._heap[0]
        if _better(
            candidate.key,
            candidate.ordinal,
            worst.key,
            worst.ordinal,
            descending=self.descending,
        ):
            heapq.heapreplace(self._heap, candidate)

    def values(self) -> list[Any]:
        # Stable sort in two passes: source order first, requested key second.
        selected = list(self._heap)
        selected.sort(key=lambda item: item.ordinal)
        selected.sort(key=lambda item: item.key, reverse=self.descending)
        return [item.value for item in selected]


__all__ = [
    "FixedCapacityTopK",
    "RAW_FALLBACK_FIELDS",
    "SEMANTIC_JSON_FIELDS",
    "field_predicate_matches",
    "field_value",
    "predicate_field",
    "referenced_fields",
    "special_field_value",
    "split_predicates",
    "topk_sort_key",
]
