from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

NEW_SESSION = r'''"""Canonical persisted retrieval memory for Agent sessions.

``RetrievalSessionState`` is the single owner for mechanical retrieval memory:
seen Evidence identities, covered source-version ranges, source observations,
bounded transport identities, and bounded retrieval-operation history.  It does
not own hypotheses, findings, causal conclusions, evidence sufficiency, or
stopping decisions.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable, Mapping


RETRIEVAL_SESSION_SCHEMA_VERSION = 1
DEFAULT_MAX_SEEN_EVIDENCE = 4096
DEFAULT_MAX_SEEN_RESULTS = 512
DEFAULT_MAX_SEEN_GROUPS = 2048
DEFAULT_MAX_SEEN_RELATIONS = 8192
DEFAULT_MAX_REQUEST_FINGERPRINTS = 512
DEFAULT_MAX_RECENT_OPERATIONS = 32
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")


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


def _append_unique(
    previous: tuple[str, ...], values: Iterable[str], limit: int
) -> tuple[tuple[str, ...], bool]:
    if limit < 1:
        raise ValueError("retrieval session seen-state limits must be at least 1")
    additions = tuple(
        str(raw or "").strip() for raw in values if str(raw or "").strip()
    )
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


def _covered_ranges_from_dict(
    payload: Mapping[str, Any],
) -> dict[str, tuple[tuple[int, int], ...]]:
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


def _source_observations_from_dict(payload: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    raw = payload.get("source_observations") or {}
    if not isinstance(raw, Mapping):
        raise ValueError("RetrievalSessionState source_observations must be an object")
    result: dict[str, dict[str, Any]] = {}
    for source, item in raw.items():
        if not isinstance(source, str) or not isinstance(item, Mapping):
            raise ValueError("RetrievalSessionState source_observations is malformed")
        generation = str(item.get("generation") or "").strip()
        if not generation:
            raise ValueError("source observation requires generation")
        values = {
            "generation": generation,
            "device": int(item.get("device") or 0),
            "inode": int(item.get("inode") or 0),
            "size": int(item.get("size") or 0),
            "mtime_ns": int(item.get("mtime_ns") or 0),
        }
        if values["size"] < 0:
            raise ValueError("source observation size cannot be negative")
        result[source] = values
    return result


def _operation_counts_from_dict(payload: Mapping[str, Any]) -> dict[str, int]:
    raw = payload.get("operation_counts") or {}
    if not isinstance(raw, Mapping):
        raise ValueError("RetrievalSessionState operation_counts must be an object")
    result: dict[str, int] = {}
    for operation, value in raw.items():
        name = str(operation or "").strip()
        if not name or isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("RetrievalSessionState operation_counts is malformed")
        result[name] = value
    return result


@dataclass(frozen=True)
class RetrievalOperation:
    """One bounded mechanical retrieval-operation observation."""

    operation: str
    status: str
    request_fingerprint: str = ""
    new_evidence: int = 0
    repeated_evidence: int = 0
    new_relations: int = 0
    new_lines: int = 0
    source_version: str = ""
    replayed: bool = False
    exact_duplicate_request: bool = False

    def __post_init__(self) -> None:
        operation = str(self.operation or "").strip()
        status = str(self.status or "").strip()
        if not operation or len(operation) > 64:
            raise ValueError("retrieval operation name must be 1-64 characters")
        if not status or len(status) > 64:
            raise ValueError("retrieval operation status must be 1-64 characters")
        fingerprint = str(self.request_fingerprint or "").strip().lower()
        if fingerprint and not _FINGERPRINT_RE.fullmatch(fingerprint):
            raise ValueError("request_fingerprint must be a sha256 hex digest")
        for name in ("new_evidence", "repeated_evidence", "new_relations", "new_lines"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        object.__setattr__(self, "operation", operation)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "request_fingerprint", fingerprint)
        object.__setattr__(self, "source_version", str(self.source_version or "").strip())
        object.__setattr__(self, "replayed", bool(self.replayed))
        object.__setattr__(self, "exact_duplicate_request", bool(self.exact_duplicate_request))

    @property
    def grew(self) -> bool:
        return any((self.new_evidence, self.new_relations, self.new_lines))

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "operation": self.operation,
            "status": self.status,
            "new_evidence": self.new_evidence,
            "repeated_evidence": self.repeated_evidence,
            "new_relations": self.new_relations,
            "new_lines": self.new_lines,
            "replayed": self.replayed,
            "exact_duplicate_request": self.exact_duplicate_request,
        }
        if self.request_fingerprint:
            payload["request_fingerprint"] = self.request_fingerprint
        if self.source_version:
            payload["source_version"] = self.source_version
        return payload

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "RetrievalOperation":
        if not isinstance(payload, Mapping):
            raise ValueError("recent operation must be an object")
        return cls(
            operation=str(payload.get("operation") or ""),
            status=str(payload.get("status") or ""),
            request_fingerprint=str(payload.get("request_fingerprint") or ""),
            new_evidence=int(payload.get("new_evidence") or 0),
            repeated_evidence=int(payload.get("repeated_evidence") or 0),
            new_relations=int(payload.get("new_relations") or 0),
            new_lines=int(payload.get("new_lines") or 0),
            source_version=str(payload.get("source_version") or ""),
            replayed=bool(payload.get("replayed")),
            exact_duplicate_request=bool(payload.get("exact_duplicate_request")),
        )


@dataclass(frozen=True)
class RetrievalSessionState:
    """Single canonical mechanical retrieval-memory owner."""

    context_id: str
    revision: int = 0
    seen_evidence: tuple[str, ...] = ()
    seen_results: tuple[str, ...] = ()
    seen_groups: tuple[str, ...] = ()
    seen_relations: tuple[str, ...] = ()
    covered_ranges: Mapping[str, tuple[tuple[int, int], ...]] = field(default_factory=dict)
    source_observations: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    operation_counts: Mapping[str, int] = field(default_factory=dict)
    recent_operations: tuple[RetrievalOperation, ...] = ()
    request_fingerprints: tuple[str, ...] = ()
    exact_duplicate_requests: int = 0
    schema_version: int = RETRIEVAL_SESSION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "context_id", validate_retrieval_session_id(self.context_id))
        if self.schema_version != RETRIEVAL_SESSION_SCHEMA_VERSION:
            raise ValueError("unsupported RetrievalSessionState schema version")
        if isinstance(self.revision, bool) or self.revision < 0:
            raise ValueError("context revision cannot be negative")
        if isinstance(self.exact_duplicate_requests, bool) or self.exact_duplicate_requests < 0:
            raise ValueError("exact_duplicate_requests cannot be negative")
        for name in ("seen_evidence", "seen_results", "seen_groups", "seen_relations"):
            values = tuple(getattr(self, name))
            if any(not isinstance(item, str) for item in values):
                raise ValueError(f"RetrievalSessionState {name} must contain strings")
            object.__setattr__(self, name, values)
        fingerprints = tuple(str(item).strip().lower() for item in self.request_fingerprints)
        if any(not _FINGERPRINT_RE.fullmatch(item) for item in fingerprints):
            raise ValueError("request_fingerprints must contain sha256 digests")
        object.__setattr__(self, "request_fingerprints", fingerprints)
        object.__setattr__(self, "operation_counts", _operation_counts_from_dict({"operation_counts": dict(self.operation_counts)}))
        operations = tuple(
            item if isinstance(item, RetrievalOperation) else RetrievalOperation.from_mapping(item)
            for item in self.recent_operations
        )
        object.__setattr__(self, "recent_operations", operations)
        normalized_ranges: dict[str, tuple[tuple[int, int], ...]] = {}
        for source, ranges in dict(self.covered_ranges).items():
            source_key = str(source or "").strip()
            if not source_key:
                raise ValueError("covered range source cannot be empty")
            normalized_ranges[source_key] = _normalize_ranges(ranges)
        object.__setattr__(self, "covered_ranges", normalized_ranges)
        object.__setattr__(
            self,
            "source_observations",
            _source_observations_from_dict({"source_observations": dict(self.source_observations)}),
        )

    @property
    def session_id(self) -> str:
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
            "source_observations": {
                source: dict(values)
                for source, values in sorted(self.source_observations.items())
            },
            "operation_counts": dict(sorted(self.operation_counts.items())),
            "recent_operations": [item.to_dict() for item in self.recent_operations],
            "request_fingerprints": list(self.request_fingerprints),
            "exact_duplicate_requests": self.exact_duplicate_requests,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RetrievalSessionState":
        if not isinstance(payload, Mapping):
            raise ValueError("RetrievalSessionState file must contain a JSON object")
        schema_version = int(payload.get("schema_version") or 0)
        if schema_version != RETRIEVAL_SESSION_SCHEMA_VERSION:
            raise ValueError("unsupported RetrievalSessionState schema version")
        recent_raw = payload.get("recent_operations") or []
        if not isinstance(recent_raw, list):
            raise ValueError("RetrievalSessionState recent_operations must be a list")
        return cls(
            context_id=str(payload.get("context_id") or ""),
            revision=int(payload.get("revision") or 0),
            seen_evidence=_string_list(payload, "seen_evidence"),
            seen_results=_string_list(payload, "seen_results"),
            seen_groups=_string_list(payload, "seen_groups"),
            seen_relations=_string_list(payload, "seen_relations"),
            covered_ranges=_covered_ranges_from_dict(payload),
            source_observations=_source_observations_from_dict(payload),
            operation_counts=_operation_counts_from_dict(payload),
            recent_operations=tuple(RetrievalOperation.from_mapping(item) for item in recent_raw),
            request_fingerprints=_string_list(payload, "request_fingerprints"),
            exact_duplicate_requests=int(payload.get("exact_duplicate_requests") or 0),
            schema_version=schema_version,
        )

    def retrieval_summary(self, *, recent_limit: int = 10) -> dict[str, Any]:
        if isinstance(recent_limit, bool) or not isinstance(recent_limit, int) or recent_limit < 1:
            raise ValueError("recent_limit must be a positive integer")
        recent = self.recent_operations[-recent_limit:]
        return {
            "operation_counts": dict(sorted(self.operation_counts.items())),
            "unique_evidence_seen": len(self.seen_evidence),
            "exact_duplicate_requests": self.exact_duplicate_requests,
            "recent_window": len(recent),
            "recent_with_new_evidence": sum(item.grew for item in recent),
            "recent_repeated_only": sum(
                (not item.grew) and item.repeated_evidence > 0 for item in recent
            ),
            "recent_no_match": sum(item.status == "no_match" for item in recent),
        }

    def advance(
        self,
        *,
        evidence: Iterable[str] = (),
        results: Iterable[str] = (),
        groups: Iterable[str] = (),
        relations: Iterable[str] = (),
        covered_ranges: Mapping[str, Iterable[tuple[int, int]]] | None = None,
        source_observations: Mapping[str, Mapping[str, Any]] | None = None,
        operation: RetrievalOperation | None = None,
        max_seen_evidence: int = DEFAULT_MAX_SEEN_EVIDENCE,
        max_seen_results: int = DEFAULT_MAX_SEEN_RESULTS,
        max_seen_groups: int = DEFAULT_MAX_SEEN_GROUPS,
        max_seen_relations: int = DEFAULT_MAX_SEEN_RELATIONS,
        max_request_fingerprints: int = DEFAULT_MAX_REQUEST_FINGERPRINTS,
        max_recent_operations: int = DEFAULT_MAX_RECENT_OPERATIONS,
    ) -> tuple["RetrievalSessionState", bool]:
        """Atomically advance all mechanical retrieval-memory dimensions once."""

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
        merged_observations = {
            source: dict(values) for source, values in self.source_observations.items()
        }
        for source, values in dict(source_observations or {}).items():
            source_key = str(source or "").strip()
            if not source_key:
                raise ValueError("source observation source cannot be empty")
            merged_observations[source_key] = dict(values)

        counts = dict(self.operation_counts)
        recent = list(self.recent_operations)
        fingerprints = self.request_fingerprints
        duplicates = self.exact_duplicate_requests
        p5 = False
        if operation is not None:
            if not isinstance(operation, RetrievalOperation):
                raise TypeError("operation must be RetrievalOperation")
            counts[operation.operation] = counts.get(operation.operation, 0) + 1
            duplicate = False
            if operation.request_fingerprint:
                duplicate = operation.request_fingerprint in set(fingerprints)
                fingerprints, p5 = _append_unique(
                    fingerprints,
                    (operation.request_fingerprint,),
                    max_request_fingerprints,
                )
            if duplicate:
                duplicates += 1
            recent.append(replace(operation, exact_duplicate_request=duplicate))
            if max_recent_operations < 1:
                raise ValueError("max_recent_operations must be at least 1")
            recent = recent[-max_recent_operations:]

        return (
            RetrievalSessionState(
                context_id=self.context_id,
                revision=self.revision + 1,
                seen_evidence=seen_evidence,
                seen_results=seen_results,
                seen_groups=seen_groups,
                seen_relations=seen_relations,
                covered_ranges=merged_ranges,
                source_observations=merged_observations,
                operation_counts=counts,
                recent_operations=tuple(recent),
                request_fingerprints=fingerprints,
                exact_duplicate_requests=duplicates,
            ),
            p1 or p2 or p3 or p4 or p5,
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
    "DEFAULT_MAX_RECENT_OPERATIONS",
    "DEFAULT_MAX_REQUEST_FINGERPRINTS",
    "DEFAULT_MAX_SEEN_EVIDENCE",
    "DEFAULT_MAX_SEEN_GROUPS",
    "DEFAULT_MAX_SEEN_RELATIONS",
    "DEFAULT_MAX_SEEN_RESULTS",
    "RETRIEVAL_SESSION_SCHEMA_VERSION",
    "RetrievalOperation",
    "RetrievalSessionState",
    "RetrievalSessionStore",
    "validate_retrieval_session_id",
]
'''

(ROOT / 'src/tracecite/runtime/retrieval_session.py').write_text(NEW_SESSION, encoding='utf-8')

# Patch session_retrieval to update Evidence memory and operation history in one locked advance.
path = ROOT / 'src/tracecite/runtime/session_retrieval.py'
text = path.read_text(encoding='utf-8')
text = text.replace('import hashlib\nimport re\n', 'import hashlib\nimport json\nimport re\n')
text = text.replace(
    'from .agent_api import EvidenceRequest, RangeTarget, RetrievalResult',
    'from .agent_api import EvidenceRequest, ProviderTarget, QueryTarget, RangeTarget, RetrievalResult, SourceTarget',
)
text = text.replace(
    '    RetrievalSessionState,\n    RetrievalSessionStore,\n)',
    '    RetrievalOperation,\n    RetrievalSessionState,\n    RetrievalSessionStore,\n)',
)
insert_after = '''_LINE_PREFIX_RE = re.compile(r"^\\s*(\\d+):(?:\\s|$)")\n\n\n'''
helpers = r'''def _request_operation(request: EvidenceRequest) -> tuple[str, str]:
    target = request.target
    if isinstance(target, QueryTarget):
        operation = "search"
        identity = {
            "source": str(Path(target.source).expanduser().resolve()),
            "query": target.query,
            "regex": target.regex,
            "last": target.last,
            "since": target.since,
            "until": target.until,
            "fold": target.fold,
        }
    elif isinstance(target, RangeTarget):
        operation = "expand"
        identity = {
            "source": str(Path(target.source).expanduser().resolve()),
            "start_line": target.start_line,
            "end_line": target.end_line,
            "before": target.before,
            "after": target.after,
            "expected_sha256": target.expected_sha256,
        }
    elif isinstance(target, SourceTarget):
        operation = "probe"
        identity = {
            "source": str(Path(target.source).expanduser().resolve()),
            "glob": target.glob,
            "recursive": target.recursive,
            "segmenter": target.segmenter,
        }
    elif isinstance(target, ProviderTarget):
        operation = "retrieve"
        identity = {"provider_request": target.request.to_dict()}
    else:
        operation = "retrieve"
        identity = {"target_type": type(target).__name__}
    encoded = json.dumps(
        {"operation": operation, "identity": identity},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return operation, hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _operation_record(
    request: EvidenceRequest,
    *,
    status: str,
    new_evidence: int,
    repeated_evidence: int,
    new_relations: int,
    new_lines: int,
    source_version: str | None,
) -> RetrievalOperation:
    operation, fingerprint = _request_operation(request)
    return RetrievalOperation(
        operation=operation,
        status=status,
        request_fingerprint=fingerprint,
        new_evidence=new_evidence,
        repeated_evidence=repeated_evidence,
        new_relations=new_relations,
        new_lines=new_lines,
        source_version=source_version or "",
    )


'''
if insert_after not in text:
    raise RuntimeError('session_retrieval helper insertion anchor missing')
text = text.replace(insert_after, insert_after + helpers, 1)

old_signature = '''def _commit_observation(\n    store: RetrievalSessionStore,\n    *,\n    evidence: tuple[Mapping[str, Any], ...],\n    relation_ids: tuple[str, ...],\n    source_key: str | None,\n    source_observation: tuple[str, Mapping[str, Any]] | None,\n    line_ranges: tuple[tuple[int, int], ...],\n) -> tuple[\n    EvidenceProgressTracker,\n    object,\n    tuple[Mapping[str, Any], ...],\n    int,\n    tuple[str, ...],\n    tuple[tuple[int, int], ...],\n]:\n'''
new_signature = '''def _commit_observation(\n    store: RetrievalSessionStore,\n    *,\n    request: EvidenceRequest,\n    canonical_status: str,\n    truncated: bool,\n    evidence: tuple[Mapping[str, Any], ...],\n    relation_ids: tuple[str, ...],\n    source_key: str | None,\n    source_observation: tuple[str, Mapping[str, Any]] | None,\n    line_ranges: tuple[tuple[int, int], ...],\n) -> tuple[\n    EvidenceProgressTracker,\n    object,\n    tuple[Mapping[str, Any], ...],\n    int,\n    tuple[str, ...],\n    tuple[tuple[int, int], ...],\n    str,\n    dict[str, Any],\n]:\n'''
if text.count(old_signature) != 1:
    raise RuntimeError('commit observation signature anchor mismatch')
text = text.replace(old_signature, new_signature, 1)

old_save = '''        if evidence_ids or relation_ids or line_ranges or source_observation:\n            evidence_limit = max(\n                DEFAULT_MAX_SEEN_EVIDENCE,\n                len(state.seen_evidence) + len(evidence_ids) + 1,\n            )\n            relation_limit = max(\n                DEFAULT_MAX_SEEN_RELATIONS,\n                len(state.seen_relations) + len(relation_ids) + 1,\n            )\n            observations = None\n            if source_observation is not None:\n                observations = {source_observation[0]: source_observation[1]}\n            next_state, _ = state.advance(\n                evidence=evidence_ids,\n                relations=relation_ids,\n                covered_ranges={source_key: line_ranges} if source_key and line_ranges else None,\n                source_observations=observations,\n                max_seen_evidence=evidence_limit,\n                max_seen_relations=relation_limit,\n            )\n            store.save(next_state)\n\n    return tracker, readiness, new_rows, repeated, new_relation_ids, unseen_ranges\n'''
new_save = '''        operation_status = str(canonical_status or "unknown")\n        if (\n            operation_status.lower() not in {"error", "no_match"}\n            and evidence\n            and not new_rows\n            and not new_relation_ids\n            and readiness.delta.new_lines == 0\n            and not truncated\n        ):\n            operation_status = "no_new_evidence"\n\n        evidence_limit = max(\n            DEFAULT_MAX_SEEN_EVIDENCE,\n            len(state.seen_evidence) + len(evidence_ids) + 1,\n        )\n        relation_limit = max(\n            DEFAULT_MAX_SEEN_RELATIONS,\n            len(state.seen_relations) + len(relation_ids) + 1,\n        )\n        observations = None\n        if source_observation is not None:\n            observations = {source_observation[0]: source_observation[1]}\n        next_state, _ = state.advance(\n            evidence=evidence_ids,\n            relations=relation_ids,\n            covered_ranges={source_key: line_ranges} if source_key and line_ranges else None,\n            source_observations=observations,\n            operation=_operation_record(\n                request,\n                status=operation_status,\n                new_evidence=len(new_rows),\n                repeated_evidence=repeated,\n                new_relations=len(new_relation_ids),\n                new_lines=readiness.delta.new_lines,\n                source_version=source_key,\n            ),\n            max_seen_evidence=evidence_limit,\n            max_seen_relations=relation_limit,\n        )\n        store.save(next_state)\n        session_progress = next_state.retrieval_summary()\n\n    return (\n        tracker,\n        readiness,\n        new_rows,\n        repeated,\n        new_relation_ids,\n        unseen_ranges,\n        operation_status,\n        session_progress,\n    )\n'''
if text.count(old_save) != 1:
    raise RuntimeError('commit observation save block mismatch')
text = text.replace(old_save, new_save, 1)

old_early = '''    if covered is not None:\n        source_key, _start, _end, observation = covered\n        readiness = tracker.observe(source=source_key)\n        if observation is not None:\n            with state_lock(session.path):\n                latest = session.load()\n                next_state, _ = latest.advance(\n                    source_observations={str(Path(request.target.source).expanduser().resolve()): observation}\n                )\n                session.save(next_state)\n        return RetrievalResult(\n            operation="expand",\n            status="no_new_evidence",\n            canonical_result={\n                "operation": "expand",\n                "status": "ok",\n                "outcome": "not_assessed",\n                "evidence": [],\n                "coverage": {},\n                "data": {\n                    "new_text": "",\n                    "unseen_ranges": [],\n                    "source_version": source_key,\n                    "novelty": {\n                        "state": "no_new_evidence",\n                        "basis": ["source_generation", "requested_context_already_covered"],\n                        "source_version": source_key,\n                    },\n                },\n            },\n            progress=readiness,\n        )\n'''
new_early = '''    if covered is not None:\n        source_key, _start, _end, observation = covered\n        with state_lock(session.path):\n            latest = session.load()\n            tracker = _restore_tracker(latest)\n            readiness = tracker.observe(source=source_key)\n            observations = None\n            if observation is not None:\n                observations = {\n                    str(Path(request.target.source).expanduser().resolve()): observation\n                }\n            next_state, _ = latest.advance(\n                source_observations=observations,\n                operation=_operation_record(\n                    request,\n                    status="no_new_evidence",\n                    new_evidence=0,\n                    repeated_evidence=0,\n                    new_relations=0,\n                    new_lines=0,\n                    source_version=source_key,\n                ),\n            )\n            session.save(next_state)\n            session_progress = next_state.retrieval_summary()\n        return RetrievalResult(\n            operation="expand",\n            status="no_new_evidence",\n            canonical_result={\n                "operation": "expand",\n                "status": "ok",\n                "outcome": "not_assessed",\n                "evidence": [],\n                "coverage": {},\n                "data": {\n                    "new_text": "",\n                    "unseen_ranges": [],\n                    "source_version": source_key,\n                    "session_progress": session_progress,\n                    "novelty": {\n                        "state": "no_new_evidence",\n                        "basis": ["source_generation", "requested_context_already_covered"],\n                        "source_version": source_key,\n                    },\n                },\n            },\n            progress=readiness,\n        )\n'''
if text.count(old_early) != 1:
    raise RuntimeError('covered-range early return block mismatch')
text = text.replace(old_early, new_early, 1)

old_call = '''    (\n        _tracker,\n        readiness,\n        new_rows,\n        repeated,\n        new_relation_ids,\n        unseen_ranges,\n    ) = _commit_observation(\n        session,\n        evidence=evidence,\n        relation_ids=relation_ids,\n        source_key=source_key,\n        source_observation=source_observation,\n        line_ranges=line_ranges,\n    )\n'''
new_call = '''    (\n        _tracker,\n        readiness,\n        new_rows,\n        repeated,\n        new_relation_ids,\n        unseen_ranges,\n        operation_status,\n        session_progress,\n    ) = _commit_observation(\n        session,\n        request=request,\n        canonical_status=str(canonical.get("status") or base.status or "unknown"),\n        truncated=truncated,\n        evidence=evidence,\n        relation_ids=relation_ids,\n        source_key=source_key,\n        source_observation=source_observation,\n        line_ranges=line_ranges,\n    )\n'''
if text.count(old_call) != 1:
    raise RuntimeError('commit observation call block mismatch')
text = text.replace(old_call, new_call, 1)

# Put the session summary in every session-backed canonical result.
anchor = '''    if repeated:\n        matched_existing = _matched_existing_evidence_refs(evidence, new_rows)\n'''
replacement = '''    data = dict(canonical.get("data") or {})\n    data["session_progress"] = session_progress\n    canonical["data"] = data\n\n    if repeated:\n        matched_existing = _matched_existing_evidence_refs(evidence, new_rows)\n'''
if text.count(anchor) != 1:
    raise RuntimeError('session_progress attachment anchor mismatch')
text = text.replace(anchor, replacement, 1)

old_status = '''    status = base.status\n    acquisition_end_reason = base.acquisition_end_reason\n    if (\n        str(canonical.get("status") or "").lower() not in {"error", "no_match"}\n        and evidence\n        and not new_rows\n        and not new_relation_ids\n        and readiness.delta.new_lines == 0\n        and not truncated\n    ):\n        status = "no_new_evidence"\n        data = dict(canonical.get("data") or {})\n        data["novelty"] = {\n            "state": "no_new_evidence",\n            "basis": ["all_returned_evidence_already_seen"],\n        }\n        canonical["data"] = data\n\n    return RetrievalResult(\n'''
new_status = '''    status = operation_status\n    acquisition_end_reason = base.acquisition_end_reason\n    if status == "no_new_evidence":\n        data = dict(canonical.get("data") or {})\n        data["novelty"] = {\n            "state": "no_new_evidence",\n            "basis": ["all_returned_evidence_already_seen"],\n        }\n        canonical["data"] = data\n\n    return RetrievalResult(\n'''
if text.count(old_status) != 1:
    raise RuntimeError('session status block mismatch')
text = text.replace(old_status, new_status, 1)
path.write_text(text, encoding='utf-8')

# Add regression for the unified state and absence of sidecar state.
test = ROOT / 'tests/test_session_novelty_regressions.py'
body = test.read_text(encoding='utf-8')
marker = '\n\ndef test_parallel_retrievals_merge_session_state_without_lost_updates'
new_test = r'''

def test_session_operation_history_is_atomic_and_has_no_sidecar(tmp_path: Path) -> None:
    source = tmp_path / "runtime.log"
    source.write_text("alpha beta same-line\nunrelated\n", encoding="utf-8")
    store = _store(tmp_path)

    retrieve_with_session(EvidenceRequest(QueryTarget(source, "alpha", max_evidence=3)), store)
    repeated = retrieve_with_session(
        EvidenceRequest(QueryTarget(source, "beta", max_evidence=3)), store
    ).to_dict()
    retrieve_with_session(EvidenceRequest(QueryTarget(source, "missing", max_evidence=3)), store)
    duplicate = retrieve_with_session(
        EvidenceRequest(QueryTarget(source, "missing", max_evidence=3)), store
    ).to_dict()

    state = store.load()
    assert state.revision == 4
    assert state.operation_counts == {"search": 4}
    assert state.exact_duplicate_requests == 1
    assert len(state.recent_operations) == 4
    assert state.recent_operations[1].status == "no_new_evidence"
    assert state.recent_operations[1].repeated_evidence == 1
    assert state.recent_operations[-1].status == "no_match"
    assert state.recent_operations[-1].exact_duplicate_request is True

    summary = state.retrieval_summary()
    assert summary["recent_window"] == 4
    assert summary["recent_with_new_evidence"] == 1
    assert summary["recent_repeated_only"] == 1
    assert summary["recent_no_match"] == 2
    assert repeated["data"]["session_progress"]["operation_counts"] == {"search": 2}
    assert duplicate["data"]["session_progress"]["exact_duplicate_requests"] == 1
    assert not list(tmp_path.rglob("*.telemetry.json"))
'''
if marker not in body:
    raise RuntimeError('session regression insertion marker missing')
if 'test_session_operation_history_is_atomic_and_has_no_sidecar' not in body:
    body = body.replace(marker, new_test + marker, 1)
test.write_text(body, encoding='utf-8')

# The failed experiment sidecar is not part of the new architecture.
telemetry = ROOT / 'src/tracecite/runtime/retrieval_telemetry.py'
if telemetry.exists():
    telemetry.unlink()

# No implementation/test/benchmark dependency may remain on the deleted sidecar.
for base in ('src', 'tests', 'benchmarks'):
    for candidate in (ROOT / base).rglob('*'):
        if not candidate.is_file() or candidate.suffix not in {'.py', '.ts', '.md'}:
            continue
        content = candidate.read_text(encoding='utf-8', errors='replace')
        if 'RetrievalSessionTelemetry' in content or '.telemetry.json' in content:
            raise RuntimeError(f'sidecar reference remains in {candidate.relative_to(ROOT)}')

print('B1 unified RetrievalSession history applied')
