"""Canonical persisted retrieval/context state for Agent sessions.

``RetrievalSessionState`` is the single owner for mechanical retrieval memory:
seen Evidence identities, covered immutable-source ranges, and bounded transport
identities used by compatibility projections. It deliberately does not own
hypotheses, findings, causal conclusions, or audit decisions; those remain
InvestigationState responsibilities.

The canonical transport location remains ``_contexts/<id>.json`` for public CLI
compatibility. Legacy ``_evidence_contexts/<id>.json`` files are accepted on
read and migrated on the next save. Investigation-linked retrieval progress uses
the same state model in a separate ``_retrieval_sessions`` namespace.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping


RETRIEVAL_SESSION_SCHEMA_VERSION = 1
DEFAULT_MAX_SEEN_EVIDENCE = 4096
DEFAULT_MAX_SEEN_RESULTS = 512
DEFAULT_MAX_SEEN_GROUPS = 2048
DEFAULT_MAX_SEEN_RELATIONS = 8192
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def validate_retrieval_session_id(value: str) -> str:
    session_id = str(value).strip()
    if not _SESSION_ID_RE.fullmatch(session_id):
        raise ValueError(
            "context_id must be 1-128 characters using letters, digits, '.', '_' or '-'"
        )
    return session_id


def _string_list(payload: Mapping[str, Any], key: str) -> tuple[str, ...]:
    raw = payload.get(key) or []
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise ValueError(f"RetrievalSessionState {key} must be a string list")
    return tuple(raw)


def _append_unique(previous: tuple[str, ...], values: Iterable[str], limit: int) -> tuple[tuple[str, ...], bool]:
    if limit < 1:
        raise ValueError("retrieval session seen-state limits must be at least 1")
    additions = tuple(str(raw or "").strip() for raw in values if str(raw or "").strip())
    if not additions:
        return previous, False
    order = list(previous)
    seen = set(previous)
    for value in additions:
        if value not in seen:
            seen.add(value)
            order.append(value)
    if len(order) <= limit:
        return tuple(order), False
    return tuple(order[-limit:]), True


def _normalize_ranges(values: Iterable[tuple[int, int]]) -> tuple[tuple[int, int], ...]:
    ordered: list[tuple[int, int]] = []
    for start, end in values:
        if isinstance(start, bool) or isinstance(end, bool):
            raise ValueError("covered ranges require positive integers")
        if not isinstance(start, int) or not isinstance(end, int) or start < 1 or end < start:
            raise ValueError("covered ranges must satisfy 1 <= start <= end")
        ordered.append((start, end))
    ordered.sort()
    merged: list[tuple[int, int]] = []
    for start, end in ordered:
        if not merged or start > merged[-1][1] + 1:
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    return tuple(merged)


def _covered_ranges_from_dict(payload: Mapping[str, Any]) -> dict[str, tuple[tuple[int, int], ...]]:
    raw = payload.get("covered_ranges") or {}
    if not isinstance(raw, Mapping):
        raise ValueError("RetrievalSessionState covered_ranges must be an object")
    result: dict[str, tuple[tuple[int, int], ...]] = {}
    for source, ranges in raw.items():
        if not isinstance(source, str) or not isinstance(ranges, list):
            raise ValueError("RetrievalSessionState covered_ranges is malformed")
        pairs: list[tuple[int, int]] = []
        for item in ranges:
            if not isinstance(item, (list, tuple)) or len(item) != 2:
                raise ValueError("RetrievalSessionState covered range must be [start, end]")
            pairs.append((item[0], item[1]))
        result[source] = _normalize_ranges(pairs)
    return result


@dataclass(frozen=True)
class RetrievalSessionState:
    """Mechanical retrieval/context memory for one session."""

    context_id: str
    revision: int = 0
    seen_evidence: tuple[str, ...] = ()
    seen_results: tuple[str, ...] = ()
    seen_groups: tuple[str, ...] = ()
    seen_relations: tuple[str, ...] = ()
    covered_ranges: Mapping[str, tuple[tuple[int, int], ...]] = field(default_factory=dict)
    schema_version: int = RETRIEVAL_SESSION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "context_id", validate_retrieval_session_id(self.context_id))
        if self.schema_version != RETRIEVAL_SESSION_SCHEMA_VERSION:
            raise ValueError("unsupported RetrievalSessionState schema version")
        if isinstance(self.revision, bool) or self.revision < 0:
            raise ValueError("context revision cannot be negative")
        for name in ("seen_evidence", "seen_results", "seen_groups", "seen_relations"):
            values = tuple(getattr(self, name))
            if any(not isinstance(item, str) for item in values):
                raise ValueError(f"RetrievalSessionState {name} must contain strings")
            object.__setattr__(self, name, values)
        normalized_ranges: dict[str, tuple[tuple[int, int], ...]] = {}
        for source, ranges in dict(self.covered_ranges).items():
            source_key = str(source or "").strip()
            if not source_key:
                raise ValueError("covered range source cannot be empty")
            normalized_ranges[source_key] = _normalize_ranges(ranges)
        object.__setattr__(self, "covered_ranges", normalized_ranges)

    @property
    def session_id(self) -> str:
        """Preferred long-term name; ``context_id`` remains compatibility API."""

        return self.context_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "context_id": self.context_id,
            "revision": self.revision,
            "seen_evidence": list(self.seen_evidence),
            "seen_results": list(self.seen_results),
            "seen_groups": list(self.seen_groups),
            "seen_relations": list(self.seen_relations),
            "covered_ranges": {
                source: [[start, end] for start, end in ranges]
                for source, ranges in sorted(self.covered_ranges.items())
            },
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RetrievalSessionState":
        if not isinstance(payload, Mapping):
            raise ValueError("RetrievalSessionState file must contain a JSON object")
        schema_version = int(payload.get("schema_version") or 0)
        if schema_version != RETRIEVAL_SESSION_SCHEMA_VERSION:
            raise ValueError("unsupported RetrievalSessionState schema version")
        return cls(
            context_id=str(payload.get("context_id") or ""),
            revision=int(payload.get("revision") or 0),
            seen_evidence=_string_list(payload, "seen_evidence"),
            seen_results=_string_list(payload, "seen_results"),
            seen_groups=_string_list(payload, "seen_groups"),
            seen_relations=_string_list(payload, "seen_relations"),
            covered_ranges=_covered_ranges_from_dict(payload),
            schema_version=schema_version,
        )

    def advance(
        self,
        *,
        evidence: Iterable[str] = (),
        results: Iterable[str] = (),
        groups: Iterable[str] = (),
        relations: Iterable[str] = (),
        covered_ranges: Mapping[str, Iterable[tuple[int, int]]] | None = None,
        max_seen_evidence: int = DEFAULT_MAX_SEEN_EVIDENCE,
        max_seen_results: int = DEFAULT_MAX_SEEN_RESULTS,
        max_seen_groups: int = DEFAULT_MAX_SEEN_GROUPS,
        max_seen_relations: int = DEFAULT_MAX_SEEN_RELATIONS,
    ) -> tuple["RetrievalSessionState", bool]:
        """Advance state once while preserving unrelated dimensions."""

        seen_evidence, p1 = _append_unique(self.seen_evidence, evidence, max_seen_evidence)
        seen_results, p2 = _append_unique(self.seen_results, results, max_seen_results)
        seen_groups, p3 = _append_unique(self.seen_groups, groups, max_seen_groups)
        seen_relations, p4 = _append_unique(self.seen_relations, relations, max_seen_relations)
        merged_ranges = dict(self.covered_ranges)
        for source, ranges in dict(covered_ranges or {}).items():
            source_key = str(source or "").strip()
            if not source_key:
                raise ValueError("covered range source cannot be empty")
            merged_ranges[source_key] = _normalize_ranges(
                [*merged_ranges.get(source_key, ()), *tuple(ranges)]
            )
        return (
            RetrievalSessionState(
                context_id=self.context_id,
                revision=self.revision + 1,
                seen_evidence=seen_evidence,
                seen_results=seen_results,
                seen_groups=seen_groups,
                seen_relations=seen_relations,
                covered_ranges=merged_ranges,
            ),
            p1 or p2 or p3 or p4,
        )


class RetrievalSessionStore:
    """Atomic persistence for the single canonical retrieval state owner."""

    def __init__(
        self,
        root: str | Path,
        context_id: str,
        *,
        namespace: str = "_contexts",
        legacy_evidence_context: bool = True,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.context_id = validate_retrieval_session_id(context_id)
        namespace_name = str(namespace or "").strip()
        if not namespace_name or "/" in namespace_name or "\\" in namespace_name:
            raise ValueError("retrieval session namespace must be one path component")
        self.namespace = namespace_name
        self.path = self.root / namespace_name / f"{self.context_id}.json"
        self.legacy_evidence_context_path = (
            self.root / "_evidence_contexts" / f"{self.context_id}.json"
            if legacy_evidence_context and namespace_name == "_contexts"
            else None
        )

    @classmethod
    def for_investigation(cls, investigation_path: str | Path) -> "RetrievalSessionStore":
        path = Path(investigation_path).expanduser().resolve()
        digest = hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:24]
        return cls(
            path.parent,
            f"investigation-{digest}",
            namespace="_retrieval_sessions",
            legacy_evidence_context=False,
        )

    def load(self) -> RetrievalSessionState:
        source = self.path
        if not source.exists() and self.legacy_evidence_context_path is not None:
            source = self.legacy_evidence_context_path
        if not source.exists():
            return RetrievalSessionState(context_id=self.context_id)
        payload = json.loads(source.read_text(encoding="utf-8"))
        state = RetrievalSessionState.from_dict(payload)
        if state.context_id != self.context_id:
            raise ValueError("RetrievalSessionState context_id mismatch")
        return state

    def save(self, state: RetrievalSessionState) -> None:
        if not isinstance(state, RetrievalSessionState):
            raise TypeError("RetrievalSessionStore.save requires RetrievalSessionState")
        if state.context_id != self.context_id:
            raise ValueError("cannot save RetrievalSessionState under a different context_id")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(
            state.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self.context_id}.",
            suffix=".tmp",
            dir=self.path.parent,
            text=True,
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def reset(self) -> None:
        self.path.unlink(missing_ok=True)
        if self.legacy_evidence_context_path is not None:
            self.legacy_evidence_context_path.unlink(missing_ok=True)


__all__ = [
    "DEFAULT_MAX_SEEN_EVIDENCE",
    "DEFAULT_MAX_SEEN_GROUPS",
    "DEFAULT_MAX_SEEN_RELATIONS",
    "DEFAULT_MAX_SEEN_RESULTS",
    "RETRIEVAL_SESSION_SCHEMA_VERSION",
    "RetrievalSessionState",
    "RetrievalSessionStore",
    "validate_retrieval_session_id",
]
