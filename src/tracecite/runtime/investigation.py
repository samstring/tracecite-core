"""Versioned, domain-neutral investigation state for Agent runtimes.

The evidence tools are intentionally useful without an investigation file.  A
caller that supplies ``investigation_path`` can additionally relate a bounded
execution record to a Hypothesis and Test.  The state file stores decisions,
links, and evidence pointers; it never stores an AgentResult ``data`` payload
or raw log text.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Mapping, Optional, Sequence, Union

from tracecite_core.state_file import atomic_write_json, read_json, state_lock

if TYPE_CHECKING:  # pragma: no cover - imports are intentionally lazy at runtime
    from tracecite.knowledge import KnowledgeCandidate, KnowledgeGovernanceStore


INVESTIGATION_SCHEMA_VERSION = 1
BUDGET_POLICY_SCHEMA_VERSION = 2
INVESTIGATION_STATUSES = frozenset({"active", "completed"})
HYPOTHESIS_STATUSES = frozenset({"open", "supported", "contradicted", "unknown"})
FINDING_OUTCOMES = frozenset({"supported", "contradicted", "unknown"})
SOURCE_SESSION_STATUSES = frozenset({"unknown", "known", "changed", "needs_revalidation"})
MAX_SOURCE_SESSIONS = 100
STOP_KINDS = frozenset(
    {
        "completed",
        "resolved",
        "evidence_exhausted",
        "budget_exhausted",
        "budget_reached",
        "authorization_required",
        "new_authorization_needed",
        "input_missing",
        "blocked",
        "aborted",
    }
)

BUDGET_LIMIT_FIELDS = (
    "max_executions",
    "max_searches",
    "max_queries",
    "max_recorded_evidence_pointers",
    "max_expand_requested_chars",
    "max_expand_returned_chars",
    "max_elapsed_seconds",
)
BUDGET_USAGE_FIELDS = (
    "executions",
    "searches",
    "queries",
    "recorded_evidence_pointers",
    "expand_requested_chars",
    "expand_returned_chars",
    "elapsed_seconds",
)
BUDGET_RESERVATION_FIELDS = BUDGET_USAGE_FIELDS
DEFAULT_MAX_ROUNDS = 64
DEFAULT_MAX_INPUT_PER_ROUND = 128_000
LEGACY_BUDGET_LIMIT_FIELDS = BUDGET_LIMIT_FIELDS
MAX_BUDGET_RESERVATIONS = 100
MAX_CACHE_ENTRIES = 100
MAX_CACHE_SOURCES = 100
MAX_CACHE_EVIDENCE = 100
MAX_CACHE_ARTIFACTS = 100
MAX_CACHE_ENTRY_BYTES = 512 * 1024
MAX_CACHE_STORE_BYTES = 4 * 1024 * 1024
CACHE_SCHEMA_VERSION = 1
CACHE_TOOL_VERSION = "tracecite-cache-v2"
SAFE_CACHE_OPERATIONS = frozenset({"probe", "search"})

# These limits apply only to the state document.  Artifacts and tool results
# remain at their existing boundaries and are never copied into this file.
MAX_ID_LENGTH = 128
MAX_STATE_TEXT = 4_096
MAX_EXECUTION_ITEMS = 100
MAX_EXECUTION_REFS = 100
MAX_EXECUTION_ARTIFACTS = 100
MAX_EXECUTION_WARNINGS = 100
_ID_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{0,127}\Z")
_EVIDENCE_URI_RE = re.compile(
    r"^evidence://sha256/(?P<digest>[0-9a-fA-F]{64})"
    r"#L(?P<start>[1-9][0-9]*)(?:-L(?P<end>[1-9][0-9]*))?$"
)

# Investigation state keeps only this small link record.  The candidate's
# payload remains in the independently persisted KnowledgeGovernanceStore.
KNOWLEDGE_CANDIDATE_LINK_KEYS = frozenset(
    {"candidate_id", "finding_id", "status", "store_path", "link", "created_at"}
)
KNOWLEDGE_CANDIDATE_STATUSES = frozenset(
    {"candidate", "verified", "contradicted", "promoted"}
)


class InvestigationError(RuntimeError):
    """An investigation document or state transition is invalid."""


class BudgetExhausted(InvestigationError):
    """A linked operation was refused before execution due to budget."""

    def __init__(self, message: str, *, details: Optional[Mapping[str, Any]] = None) -> None:
        super().__init__(message)
        self.details = dict(details or {})


def _positive_limit(value: Any, *, field_name: str, elapsed: bool = False) -> Optional[Union[int, float]]:
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvestigationError(f"{field_name} 必须是正数")
    if not math.isfinite(float(value)) or float(value) <= 0:
        raise InvestigationError(f"{field_name} 必须是正数")
    if elapsed:
        return float(value)
    if not isinstance(value, int):
        raise InvestigationError(f"{field_name} 必须是正整数")
    return int(value)


@dataclass(frozen=True, init=False)
class BudgetPolicy:
    """Two-dimensional user budget for an Agent investigation.

    ``max_rounds`` bounds how many Runtime calls may be attempted.  A round is
    one linked Runtime operation. ``max_input_per_round`` bounds the serialized
    Agent-visible result for any one round. Defaults are intentionally generous
    but finite.

    Legacy v1 budget keys are accepted only to read existing callers/state.
    ``max_executions`` maps to ``max_rounds``; all other old per-dimension limits
    are ignored because they are no longer user budget concepts.
    """

    schema_version: int
    max_rounds: int
    max_input_per_round: int

    def __init__(
        self,
        schema_version: int = BUDGET_POLICY_SCHEMA_VERSION,
        max_rounds: Optional[int] = None,
        max_input_per_round: Optional[int] = None,
        **legacy: Any,
    ) -> None:
        if isinstance(schema_version, bool) or not isinstance(schema_version, int):
            raise InvestigationError("budget_policy.schema_version 必须是整数")
        if schema_version not in {1, BUDGET_POLICY_SCHEMA_VERSION}:
            raise InvestigationError(f"不支持 budget policy schema {schema_version!r}")
        unsupported = set(legacy) - set(LEGACY_BUDGET_LIMIT_FIELDS)
        if unsupported:
            raise InvestigationError(
                "budget_policy 含有不支持的字段: "
                + ", ".join(sorted(str(item) for item in unsupported))
            )
        if max_rounds is None and legacy.get("max_executions") not in {None, ""}:
            max_rounds = legacy.get("max_executions")
        rounds = DEFAULT_MAX_ROUNDS if max_rounds is None else max_rounds
        input_cap = (
            DEFAULT_MAX_INPUT_PER_ROUND
            if max_input_per_round is None
            else max_input_per_round
        )
        _positive_limit(rounds, field_name="budget_policy.max_rounds")
        _positive_limit(input_cap, field_name="budget_policy.max_input_per_round")
        object.__setattr__(self, "schema_version", BUDGET_POLICY_SCHEMA_VERSION)
        object.__setattr__(self, "max_rounds", int(rounds))
        object.__setattr__(self, "max_input_per_round", int(input_cap))

    @classmethod
    def from_mapping(cls, raw: Optional[Mapping[str, Any]]) -> "BudgetPolicy":
        if raw is None:
            return cls()
        if not isinstance(raw, Mapping):
            raise InvestigationError("budget_policy 必须是对象或 null")
        allowed = {
            "schema_version",
            "max_rounds",
            "max_input_per_round",
            *LEGACY_BUDGET_LIMIT_FIELDS,
        }
        unsupported = set(raw) - allowed
        if unsupported:
            raise InvestigationError(
                "budget_policy 含有不支持的字段: "
                + ", ".join(sorted(str(item) for item in unsupported))
            )
        kwargs = dict(raw)
        return cls(**kwargs)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": BUDGET_POLICY_SCHEMA_VERSION,
            "max_rounds": self.max_rounds,
            "max_input_per_round": self.max_input_per_round,
        }

    def remaining(self, usage: Mapping[str, Any]) -> Dict[str, int]:
        rounds_used = int(usage.get("executions") or 0)
        return {
            "rounds": max(0, self.max_rounds - rounds_used),
            "input_per_round": self.max_input_per_round,
        }


def _empty_budget_usage() -> Dict[str, Union[int, float]]:
    return {
        "executions": 0,
        "searches": 0,
        "queries": 0,
        "recorded_evidence_pointers": 0,
        "expand_requested_chars": 0,
        "expand_returned_chars": 0,
        "elapsed_seconds": 0.0,
    }


def _normalize_budget_usage(raw: Any) -> Dict[str, Union[int, float]]:
    if raw is None:
        return _empty_budget_usage()
    if not isinstance(raw, Mapping):
        raise InvestigationError("budget_usage 必须是对象")
    unsupported = set(raw) - set(BUDGET_USAGE_FIELDS)
    if unsupported:
        raise InvestigationError(
            "budget_usage 含有不支持的字段: "
            + ", ".join(sorted(str(item) for item in unsupported))
        )
    result = _empty_budget_usage()
    for field_name in BUDGET_USAGE_FIELDS:
        value = raw.get(field_name, result[field_name])
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise InvestigationError(f"budget_usage.{field_name} 必须是非负数")
        if not math.isfinite(float(value)) or float(value) < 0:
            raise InvestigationError(f"budget_usage.{field_name} 必须是非负数")
        if field_name == "elapsed_seconds":
            result[field_name] = float(value)
        else:
            if not isinstance(value, int):
                raise InvestigationError(f"budget_usage.{field_name} 必须是非负整数")
            result[field_name] = int(value)
    return result


def _normalize_budget_reservations(raw: Any) -> Dict[str, Dict[str, Any]]:
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise InvestigationError("budget_reservations 必须是对象")
    if len(raw) > MAX_BUDGET_RESERVATIONS:
        raise InvestigationError("budget_reservations 数量超过限制")
    result: Dict[str, Dict[str, Any]] = {}
    allowed = {"operation", "created_at", *BUDGET_RESERVATION_FIELDS}
    for reservation_id, item in raw.items():
        identifier = _validate_id(reservation_id, field_name="budget_reservations.id")
        if not isinstance(item, Mapping):
            raise InvestigationError("budget_reservations 条目必须是对象")
        unsupported = set(item) - allowed
        if unsupported:
            raise InvestigationError("budget_reservations 条目含有不支持字段")
        operation = _required_text(
            item.get("operation"),
            field_name="budget_reservations.operation",
            limit=256,
        )
        created_at = _required_text(
            item.get("created_at"),
            field_name="budget_reservations.created_at",
            limit=128,
        )
        row: Dict[str, Any] = {"operation": operation, "created_at": created_at}
        for field_name in BUDGET_RESERVATION_FIELDS:
            value = item.get(field_name, 0.0 if field_name == "elapsed_seconds" else 0)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise InvestigationError(
                    f"budget_reservations.{field_name} 必须是非负数"
                )
            if not math.isfinite(float(value)) or float(value) < 0:
                raise InvestigationError(
                    f"budget_reservations.{field_name} 必须是非负数"
                )
            row[field_name] = float(value) if field_name == "elapsed_seconds" else int(value)
        result[identifier] = row
    return result


class BudgetReservation:
    """A concurrency-safe reservation finalized after one linked operation."""

    def __init__(
        self,
        store: "InvestigationStore",
        reservation_id: str,
        reserved: Mapping[str, Any],
        *,
        started_monotonic: Optional[float] = None,
    ) -> None:
        self.store = store
        self.reservation_id = reservation_id
        self.reserved = dict(reserved)
        self.started_monotonic = (
            time.monotonic() if started_monotonic is None else started_monotonic
        )
        self._finished = False

    def finalize(
        self,
        actual: Optional[Mapping[str, Any]] = None,
        *,
        elapsed_seconds: Optional[float] = None,
    ) -> Dict[str, Any]:
        if self._finished:
            return self.store.budget_status()
        values = dict(actual or {})
        if elapsed_seconds is None:
            elapsed_seconds = max(0.0, time.monotonic() - self.started_monotonic)
        values.setdefault("elapsed_seconds", elapsed_seconds)
        status = self.store.finalize_budget(self.reservation_id, values)
        self._finished = True
        return status

    def release(self) -> Dict[str, Any]:
        if self._finished:
            return self.store.budget_status()
        status = self.store.release_budget(self.reservation_id)
        self._finished = True
        return status


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _path_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _cache_safe_result(result: Mapping[str, Any]) -> Dict[str, Any]:
    """Detach a cacheable result without copying raw source bodies."""

    payload = copy.deepcopy(dict(result))
    evidence = payload.get("evidence")
    if isinstance(evidence, list):
        for item in evidence:
            if not isinstance(item, dict):
                continue
            item.pop("label", None)
            metadata = item.get("metadata")
            if isinstance(metadata, dict):
                metadata.pop("text", None)
                metadata.pop("raw", None)
    data = payload.get("data")
    if isinstance(data, dict):
        for key in ("text", "raw", "samples", "top_templates", "spikes"):
            data.pop(key, None)
    return payload


class InvestigationCacheStore:
    """Bounded, atomic cache sidecar for deterministic linked tool results."""

    def __init__(self, path: Union[str, Path]) -> None:
        self.path = Path(path).expanduser().resolve()

    @staticmethod
    def default_path(investigation_path: Union[str, Path]) -> Path:
        path = Path(investigation_path).expanduser().resolve()
        return path.with_name(path.name + ".cache.json")

    def _empty(self) -> Dict[str, Any]:
        return {
            "schema_version": CACHE_SCHEMA_VERSION,
            "revision": 0,
            "tool_version": CACHE_TOOL_VERSION,
            "entries": [],
        }

    def _load(self) -> Dict[str, Any]:
        if not self.path.is_file():
            return self._empty()
        try:
            if self.path.stat().st_size > MAX_CACHE_STORE_BYTES:
                raise InvestigationError("缓存文件超过大小限制")
        except OSError as exc:
            raise InvestigationError(f"缓存文件不可读: {self.path}") from exc
        try:
            raw = read_json(self.path)
        except ValueError as exc:
            raise InvestigationError(f"缓存文件损坏或不可读: {self.path}") from exc
        if int(raw.get("schema_version") or 0) != CACHE_SCHEMA_VERSION:
            raise InvestigationError(
                f"不支持 cache schema {raw.get('schema_version')!r}"
            )
        entries = raw.get("entries") or []
        if not isinstance(entries, list) or len(entries) > MAX_CACHE_ENTRIES:
            raise InvestigationError("缓存条目数量超过限制")
        for entry in entries:
            if not isinstance(entry, Mapping):
                raise InvestigationError("缓存条目必须是对象")
            if len(_canonical_json(entry).encode("utf-8")) > MAX_CACHE_ENTRY_BYTES:
                raise InvestigationError("缓存条目超过大小限制")
        raw["revision"] = int(raw.get("revision") or 0)
        raw["tool_version"] = str(raw.get("tool_version") or CACHE_TOOL_VERSION)
        raw["entries"] = entries
        return raw

    def _save(self, raw: Dict[str, Any]) -> None:
        raw["revision"] = int(raw.get("revision") or 0) + 1
        encoded = json.dumps(raw, ensure_ascii=False, indent=2).encode("utf-8")
        if len(encoded) > MAX_CACHE_STORE_BYTES:
            raise InvestigationError("缓存文件超过大小限制")
        atomic_write_json(self.path, raw)

    @staticmethod
    def make_key(
        operation: str,
        parameters: Mapping[str, Any],
        *,
        source_refs: Sequence[Mapping[str, Any]],
        segmenter: str,
        snapshot: Optional[bool],
    ) -> str:
        payload = {
            "tool_version": CACHE_TOOL_VERSION,
            "result_schema_version": 1,
            "operation": operation,
            "parameters": dict(parameters),
            "sources": [dict(item) for item in source_refs],
            "segmenter": segmenter,
            "snapshot": snapshot,
        }
        return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()

    @staticmethod
    def _source_refs_valid(
        source_refs: Sequence[Mapping[str, Any]],
        *,
        digest_cache: Optional[Dict[str, str]] = None,
    ) -> tuple[bool, str]:
        verified = digest_cache if digest_cache is not None else {}
        for item in source_refs:
            path = Path(str(item.get("path") or "")).expanduser()
            expected = str(item.get("sha256") or "")
            if not path.is_file():
                return False, "source_missing"
            if not re.fullmatch(r"[0-9a-fA-F]{64}", expected):
                return False, "source_sha256_missing"
            key = str(path.resolve())
            try:
                actual = verified.get(key)
                if actual is None:
                    actual = _path_sha256(path)
                    verified[key] = actual
            except OSError:
                return False, "source_unreadable"
            if actual != expected:
                return False, "source_sha256_changed"
        return True, ""

    @classmethod
    def _entry_valid(cls, entry: Mapping[str, Any]) -> tuple[bool, str]:
        sources = entry.get("sources") or []
        if not isinstance(sources, list) or len(sources) > MAX_CACHE_SOURCES:
            return False, "invalid_sources"
        digest_cache: Dict[str, str] = {}
        valid, reason = cls._source_refs_valid(
            sources, digest_cache=digest_cache
        )
        if not valid:
            return False, reason
        evidence_sources = entry.get("evidence_sources") or []
        if not isinstance(evidence_sources, list) or len(evidence_sources) > MAX_CACHE_EVIDENCE:
            return False, "invalid_evidence"
        for item in evidence_sources:
            if not isinstance(item, Mapping):
                return False, "invalid_evidence"
            valid, reason = cls._source_refs_valid(
                [item], digest_cache=digest_cache
            )
            if not valid:
                return False, "evidence_" + reason
        artifacts = entry.get("artifacts") or []
        if not isinstance(artifacts, list) or len(artifacts) > MAX_CACHE_ARTIFACTS:
            return False, "invalid_artifact"
        for item in artifacts:
            if not isinstance(item, Mapping):
                return False, "invalid_artifact"
            path = Path(str(item.get("path") or "")).expanduser()
            expected = str(item.get("sha256") or "")
            if not path.is_file():
                return False, "artifact_missing"
            if expected:
                try:
                    actual = _path_sha256(path)
                except OSError:
                    return False, "artifact_unreadable"
                if actual != expected:
                    return False, "artifact_sha256_changed"
        return True, ""

    def lookup(
        self,
        key: str,
        *,
        source_refs: Sequence[Mapping[str, Any]],
        operation: str = "",
        parameters: Optional[Mapping[str, Any]] = None,
        segmenter: str = "",
        snapshot: Optional[bool] = None,
    ) -> tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
        with state_lock(self.path):
            raw = self._load()
            entries = list(raw.get("entries") or [])
            for index, item in enumerate(entries):
                if not isinstance(item, Mapping) or str(item.get("key")) != key:
                    continue
                if [dict(ref) for ref in item.get("sources") or []] != [
                    dict(ref) for ref in source_refs
                ]:
                    return None, {"status": "miss", "reason": "source_identity_changed", "key": key}
                valid, reason = self._entry_valid(item)
                if not valid:
                    entries.pop(index)
                    raw["entries"] = entries
                    self._save(raw)
                    return None, {"status": "miss", "reason": reason}
                result = item.get("result")
                if not isinstance(result, Mapping):
                    return None, {"status": "miss", "reason": "invalid_result"}
                return copy.deepcopy(dict(result)), {
                    "status": "hit",
                    "key": key,
                    "created_at": item.get("created_at"),
                }
            # The source digest is deliberately part of the primary key.  If
            # parameters match an older entry but its source now fails hash
            # validation, expose a useful stale miss instead of hiding it as a
            # generic new-key miss.
            for item in entries:
                if not isinstance(item, Mapping):
                    continue
                if (
                    str(item.get("operation") or "") == operation
                    and dict(item.get("parameters") or {}) == dict(parameters or {})
                    and str(item.get("segmenter") or "") == segmenter
                    and item.get("snapshot") == snapshot
                ):
                    return None, {"status": "miss", "reason": "source_sha256_changed", "key": key}
            return None, {"status": "miss", "reason": "not_found", "key": key}

    def put(
        self,
        key: str,
        *,
        operation: str,
        result: Mapping[str, Any],
        source_refs: Sequence[Mapping[str, Any]],
        parameters: Optional[Mapping[str, Any]] = None,
        segmenter: str = "",
        snapshot: Optional[bool] = None,
    ) -> None:
        if len(source_refs) > MAX_CACHE_SOURCES:
            raise InvestigationError("缓存来源数量超过限制")
        safe_result = _cache_safe_result(result)
        if len(safe_result.get("evidence") or []) > MAX_CACHE_EVIDENCE:
            raise InvestigationError("缓存 Evidence 数量超过限制")
        if len(safe_result.get("artifacts") or []) > MAX_CACHE_ARTIFACTS:
            raise InvestigationError("缓存 artifact 数量超过限制")
        evidence_sources: List[Dict[str, Any]] = []
        evidence_source_keys: set[tuple[str, str]] = set()
        verified_evidence_paths: Dict[str, str] = {}
        for item in safe_result.get("evidence") or []:
            if not isinstance(item, Mapping):
                continue
            path_text = str(item.get("source_path") or "").strip()
            digest = str(item.get("sha256") or "").strip()
            if not path_text or not digest:
                raise InvestigationError("缓存 Evidence 缺少可验证 source_path/sha256")
            path = Path(path_text).expanduser()
            if not path.is_file():
                raise InvestigationError(f"缓存 Evidence 来源不存在: {path}")
            resolved_path = str(path.resolve())
            try:
                actual = verified_evidence_paths.get(resolved_path)
                if actual is None:
                    actual = _path_sha256(path)
                    verified_evidence_paths[resolved_path] = actual
            except OSError as exc:
                raise InvestigationError(f"缓存 Evidence 来源不可读: {path}") from exc
            if actual != digest:
                raise InvestigationError(f"缓存 Evidence 来源摘要不匹配: {path}")
            identity = (resolved_path, digest)
            if identity not in evidence_source_keys:
                evidence_source_keys.add(identity)
                evidence_sources.append({"path": resolved_path, "sha256": digest})
        artifacts: List[Dict[str, Any]] = []
        for item in safe_result.get("artifacts") or []:
            if not isinstance(item, Mapping):
                continue
            path_text = str(item.get("path") or "").strip()
            if not path_text:
                raise InvestigationError("缓存 artifact 缺少 path")
            path = Path(path_text).expanduser()
            if not path.is_file():
                raise InvestigationError(f"缓存 artifact 不存在: {path}")
            try:
                digest = _path_sha256(path)
            except OSError as exc:
                raise InvestigationError(f"缓存 artifact 不可读: {path}") from exc
            artifacts.append({"path": str(path), "sha256": digest})
        entry = {
            "key": key,
            "operation": operation,
            "parameters": dict(parameters or {}),
            "segmenter": segmenter,
            "snapshot": snapshot,
            "created_at": _now_iso(),
            "sources": [dict(item) for item in source_refs],
            "evidence_sources": evidence_sources,
            "artifacts": artifacts,
            "result": safe_result,
        }
        if len(json.dumps(entry, ensure_ascii=False, indent=2).encode("utf-8")) > MAX_CACHE_ENTRY_BYTES:
            raise InvestigationError("缓存条目超过大小限制")
        with state_lock(self.path):
            raw = self._load()
            entries = [
                item for item in raw.get("entries") or []
                if isinstance(item, Mapping) and str(item.get("key")) != key
            ]
            if len(entries) >= MAX_CACHE_ENTRIES:
                raise InvestigationError("缓存条目数量已达上限")
            entries.append(entry)
            raw["entries"] = entries
            self._save(raw)

def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _required_text(value: object, *, field_name: str, limit: int = MAX_STATE_TEXT) -> str:
    resolved = "" if value is None else str(value).strip()
    if not resolved:
        raise InvestigationError(f"{field_name} 不能为空")
    if len(resolved) > limit:
        raise InvestigationError(f"{field_name} 不能超过 {limit} 个字符")
    return resolved


def _optional_text(
    value: object,
    *,
    field_name: str,
    limit: int = MAX_STATE_TEXT,
) -> str:
    resolved = "" if value is None else str(value).strip()
    if len(resolved) > limit:
        raise InvestigationError(f"{field_name} 不能超过 {limit} 个字符")
    return resolved


def _validate_id(value: object, *, field_name: str) -> str:
    resolved = _required_text(value, field_name=field_name, limit=MAX_ID_LENGTH)
    if not _ID_RE.fullmatch(resolved):
        raise InvestigationError(
            f"{field_name} 格式无效；只能使用字母开头的字母、数字、点、下划线、冒号或连字符"
        )
    return resolved


def _json_value(value: Any, *, field_name: str) -> Any:
    """Validate JSON compatibility and return a detached plain value."""

    try:
        return json.loads(
            json.dumps(value, ensure_ascii=False, allow_nan=False)
        )
    except (TypeError, ValueError, OverflowError) as exc:
        raise InvestigationError(f"{field_name} 必须可以序列化为 JSON") from exc


def _bounded_value(value: Any, *, depth: int = 0) -> Any:
    """Detach arbitrary JSON while keeping state metadata bounded."""

    if depth > 6:
        return "<truncated>"
    if isinstance(value, str):
        return value[:MAX_STATE_TEXT]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, Mapping):
        result: Dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= MAX_EXECUTION_ITEMS:
                break
            result[str(key)[:256]] = _bounded_value(item, depth=depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        return [_bounded_value(item, depth=depth + 1) for item in value[:MAX_EXECUTION_ITEMS]]
    return str(value)[:MAX_STATE_TEXT]


def _bounded_value_with_flag(value: Any, *, depth: int = 0) -> tuple[Any, bool]:
    """Bound an external summary value and report whether anything was omitted."""

    if depth > 6:
        return "<truncated>", True
    if isinstance(value, str):
        return value[:MAX_STATE_TEXT], len(value) > MAX_STATE_TEXT
    if value is None or isinstance(value, (bool, int, float)):
        return value, False
    if isinstance(value, Mapping):
        result: Dict[str, Any] = {}
        truncated = len(value) > MAX_EXECUTION_ITEMS
        for index, (key, item) in enumerate(value.items()):
            if index >= MAX_EXECUTION_ITEMS:
                break
            bounded, omitted = _bounded_value_with_flag(item, depth=depth + 1)
            result[str(key)[:256]] = bounded
            truncated = truncated or omitted or len(str(key)) > 256
        return result, truncated
    if isinstance(value, (list, tuple)):
        truncated = len(value) > MAX_EXECUTION_ITEMS
        result: List[Any] = []
        for item in value[:MAX_EXECUTION_ITEMS]:
            bounded, omitted = _bounded_value_with_flag(item, depth=depth + 1)
            result.append(bounded)
            truncated = truncated or omitted
        return result, truncated
    text = str(value)
    return text[:MAX_STATE_TEXT], len(text) > MAX_STATE_TEXT


def _strict_json_value(value: Any, *, field_name: str, depth: int = 0) -> Any:
    """Validate user-authored state JSON without silently changing it."""

    if depth > 6:
        raise InvestigationError(f"{field_name} 嵌套层级超过限制")
    checked = _json_value(value, field_name=field_name)
    if isinstance(checked, str):
        if len(checked) > MAX_STATE_TEXT:
            raise InvestigationError(f"{field_name} 中的文本过长")
        return checked
    if isinstance(checked, Mapping):
        if len(checked) > MAX_EXECUTION_ITEMS:
            raise InvestigationError(f"{field_name} 对象字段过多")
        result: Dict[str, Any] = {}
        for key, item in checked.items():
            key_text = str(key)
            if len(key_text) > 256:
                raise InvestigationError(f"{field_name} 的字段名过长")
            result[key_text] = _strict_json_value(
                item, field_name=f"{field_name}.{key_text}", depth=depth + 1
            )
        return result
    if isinstance(checked, list):
        if len(checked) > MAX_EXECUTION_ITEMS:
            raise InvestigationError(f"{field_name} 数组元素过多")
        return [
            _strict_json_value(item, field_name=f"{field_name}[{index}]", depth=depth + 1)
            for index, item in enumerate(checked)
        ]
    return checked


def _bounded_external_object(
    value: Any,
    *,
    field_name: str,
) -> tuple[Dict[str, Any], bool]:
    """Validate and bound tool-returned JSON while reporting omissions."""

    if value is None:
        return {}, False
    if not isinstance(value, Mapping):
        raise InvestigationError(f"{field_name} 必须是对象")
    checked = _json_value(dict(value), field_name=field_name)
    bounded, truncated = _bounded_value_with_flag(checked)
    if not isinstance(bounded, Mapping):
        raise InvestigationError(f"{field_name} 必须是对象")
    return dict(bounded), truncated


def _bounded_error(
    error: Any,
    *,
    strict: bool = False,
) -> Optional[Dict[str, str]]:
    """Keep structured tool failure metadata without copying arbitrary payloads."""

    if error is None:
        return None
    if not isinstance(error, Mapping):
        raise InvestigationError("execution.error 必须是对象或 null")
    allowed = {"type", "message", "code"}
    if strict and set(error) - allowed:
        raise InvestigationError("execution.error 含有不支持的字段")
    result: Dict[str, str] = {}
    for key in ("type", "message", "code"):
        value = error.get(key)
        if value is not None:
            text = str(value)
            if strict and len(text) > MAX_STATE_TEXT:
                raise InvestigationError(f"execution.error.{key} 不能超过预算")
            result[key] = text[:MAX_STATE_TEXT]
    return result or None


def _bounded_error_with_flag(
    error: Any,
) -> tuple[Optional[Dict[str, str]], bool]:
    if error is None:
        return None, False
    if not isinstance(error, Mapping):
        raise InvestigationError("execution.error 必须是对象或 null")
    truncated = False
    for key in ("type", "message", "code"):
        value = error.get(key)
        if value is not None and len(str(value)) > MAX_STATE_TEXT:
            truncated = True
    return _bounded_error(error), truncated


def _json_object(value: Any, *, field_name: str) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        raise InvestigationError(f"{field_name} 必须是对象")
    checked = _strict_json_value(dict(value), field_name=field_name)
    return dict(checked)


def _text_list(value: Any, *, field_name: str, max_items: int = MAX_EXECUTION_ITEMS) -> List[str]:
    if value is None:
        return []
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise InvestigationError(f"{field_name} 必须是字符串数组")
    if len(value) > max_items:
        raise InvestigationError(f"{field_name} 元素过多")
    result: List[str] = []
    seen = set()
    for item in value:
        resolved = str(item or "").strip()
        if not resolved or resolved in seen:
            continue
        if len(resolved) > MAX_STATE_TEXT:
            raise InvestigationError(f"{field_name} 中的文本过长")
        seen.add(resolved)
        result.append(resolved)
    return result


def _unique_texts(values: Sequence[object]) -> List[str]:
    """Return non-empty, de-duplicated text references."""

    if isinstance(values, (str, bytes)):
        values = [values]  # type: ignore[assignment]
    result: List[str] = []
    seen = set()
    for value in values or ():
        item = str(value or "").strip()
        if item and item not in seen:
            seen.add(item)
            if len(item) > MAX_STATE_TEXT:
                raise InvestigationError("文本引用过长")
            result.append(item)
    if len(result) > MAX_EXECUTION_REFS:
        raise InvestigationError("文本引用过多")
    return result


def _evidence_refs(evidence: Sequence[Any]) -> List[str]:
    refs: List[str] = []
    for item in evidence or ():
        if isinstance(item, Mapping):
            uri = str(item.get("uri") or "").strip()
            if uri:
                refs.append(uri)
        elif str(item or "").strip():
            refs.append(str(item).strip())
    return _unique_texts(refs)


def _citable_evidence_refs(values: Sequence[object], *, field_name: str) -> List[str]:
    """Validate immutable EvidencePointer URI references for governance.

    Candidate proposals intentionally accept only the canonical immutable
    pointer form currently emitted by Runtime:
    ``evidence://sha256/<64-hex-digest>#L<start>[-L<end>]``.  Manifest refs
    are not accepted until a versioned manifest URI contract is defined.
    """

    refs = _unique_texts(values)
    for ref in refs:
        match = _EVIDENCE_URI_RE.fullmatch(ref)
        if match is None:
            raise InvestigationError(
                f"{field_name} 必须是带 SHA-256 摘要和行范围的 Evidence URI: {ref!r}"
            )
        start = int(match.group("start"))
        end = int(match.group("end") or match.group("start"))
        if end < start:
            raise InvestigationError(
                f"{field_name} 必须是带 SHA-256 摘要和行范围的 Evidence URI；"
                f"行范围无效（结束行小于起始行）: {ref!r}"
            )
    return refs


def _bounded_evidence_refs(evidence: Sequence[Any]) -> tuple[List[str], bool]:
    refs: List[str] = []
    seen = set()
    truncated = False
    for item in evidence or ():
        if isinstance(item, Mapping):
            uri = str(item.get("uri") or "").strip()
        else:
            uri = str(item or "").strip()
        if not uri or uri in seen:
            continue
        seen.add(uri)
        if len(uri) > MAX_STATE_TEXT:
            truncated = True
            uri = uri[:MAX_STATE_TEXT]
        if len(refs) >= MAX_EXECUTION_REFS:
            truncated = True
            continue
        refs.append(uri)
    return refs, truncated


def _bounded_evidence_item(item: Any) -> Optional[Dict[str, Any]]:
    """Keep only pointer metadata; deliberately discard arbitrary metadata."""

    if isinstance(item, Mapping):
        allowed = (
            "uri",
            "source_path",
            "sha256",
            "start_line",
            "end_line",
            "timestamp",
            "label",
        )
        result: Dict[str, Any] = {}
        for key in allowed:
            value = item.get(key)
            if value is None:
                continue
            if key in {"uri", "source_path", "sha256", "timestamp"}:
                result[key] = str(value)[:MAX_STATE_TEXT]
            elif key in {"start_line", "end_line"}:
                try:
                    result[key] = int(value)
                except (TypeError, ValueError):
                    continue
            else:
                result[key] = str(value)[:240]
        return result or None
    text = str(item or "").strip()
    return {"uri": text[:MAX_STATE_TEXT]} if text else None


def _bounded_evidence(evidence: Any) -> List[Dict[str, Any]]:
    if evidence is None:
        return []
    if isinstance(evidence, (str, bytes)) or not isinstance(evidence, Sequence):
        raise InvestigationError("evidence 必须是数组")
    result: List[Dict[str, Any]] = []
    for item in evidence[:MAX_EXECUTION_ITEMS]:
        bounded = _bounded_evidence_item(item)
        if bounded is not None:
            result.append(bounded)
    return result


def _strict_evidence(evidence: Any) -> List[Dict[str, Any]]:
    """Load canonical persisted pointers without silently dropping fields."""

    if evidence is None:
        return []
    if isinstance(evidence, (str, bytes)) or not isinstance(evidence, Sequence):
        raise InvestigationError("execution.evidence 必须是数组")
    if len(evidence) > MAX_EXECUTION_ITEMS:
        raise InvestigationError("execution.evidence 元素过多")
    allowed = {
        "uri", "source_path", "sha256", "start_line", "end_line", "timestamp", "label"
    }
    result: List[Dict[str, Any]] = []
    for index, item in enumerate(evidence):
        if isinstance(item, Mapping):
            if set(item) - allowed:
                raise InvestigationError(
                    f"execution.evidence[{index}] 含有不支持的字段"
                )
            for key in ("uri", "source_path", "sha256", "timestamp"):
                value = item.get(key)
                if value is not None and len(str(value)) > MAX_STATE_TEXT:
                    raise InvestigationError(
                        f"execution.evidence[{index}].{key} 不能超过预算"
                    )
            label = item.get("label")
            if label is not None and len(str(label)) > 240:
                raise InvestigationError(
                    f"execution.evidence[{index}].label 不能超过预算"
                )
            for key in ("start_line", "end_line"):
                value = item.get(key)
                if value is not None and (
                    isinstance(value, bool) or not isinstance(value, int)
                ):
                    raise InvestigationError(
                        f"execution.evidence[{index}].{key} 必须是整数"
                    )
            bounded = _bounded_evidence_item(item)
        else:
            text = str(item or "").strip()
            if not text:
                raise InvestigationError(f"execution.evidence[{index}] 不能为空")
            if len(text) > MAX_STATE_TEXT:
                raise InvestigationError(
                    f"execution.evidence[{index}] 不能超过预算"
                )
            bounded = {"uri": text}
        if bounded is not None:
            result.append(bounded)
    return result


def _bounded_evidence_with_flags(
    evidence: Any,
) -> tuple[List[Dict[str, Any]], bool, bool, bool]:
    """Return bounded pointers, array truncation, and metadata omission flags."""

    if evidence is None:
        return [], False, False, False
    if isinstance(evidence, (str, bytes)) or not isinstance(evidence, Sequence):
        raise InvestigationError("evidence 必须是数组")
    array_truncated = len(evidence) > MAX_EXECUTION_ITEMS
    allowed_pointer_keys = {
        "uri", "source_path", "sha256", "start_line", "end_line", "timestamp", "label"
    }
    metadata_omitted = any(
        isinstance(item, Mapping)
        and (item.get("metadata") or set(item) - allowed_pointer_keys)
        for item in evidence
    )
    fields_truncated = False
    result: List[Dict[str, Any]] = []
    for item in evidence[:MAX_EXECUTION_ITEMS]:
        if isinstance(item, Mapping) and (
            item.get("metadata") or set(item) - allowed_pointer_keys
        ):
            metadata_omitted = True
        if isinstance(item, Mapping):
            for key in ("uri", "source_path", "sha256", "timestamp"):
                value = item.get(key)
                if value is not None and len(str(value)) > MAX_STATE_TEXT:
                    fields_truncated = True
            value = item.get("label")
            if value is not None and len(str(value)) > 240:
                fields_truncated = True
        bounded = _bounded_evidence_item(item)
        if bounded is not None:
            result.append(bounded)
    return result, array_truncated, metadata_omitted, fields_truncated


def _bounded_artifacts(artifacts: Any) -> List[Dict[str, Any]]:
    if artifacts is None:
        return []
    if isinstance(artifacts, (str, bytes)) or not isinstance(artifacts, Sequence):
        raise InvestigationError("artifacts 必须是数组")
    result: List[Dict[str, Any]] = []
    for item in artifacts[:MAX_EXECUTION_ARTIFACTS]:
        if not isinstance(item, Mapping):
            continue
        row: Dict[str, Any] = {}
        for key in ("role", "path", "uri", "sha256", "kind", "name"):
            value = item.get(key)
            if value is not None:
                row[key] = str(value)[:MAX_STATE_TEXT]
        if row:
            result.append(row)
    return result


def _strict_artifacts(artifacts: Any) -> List[Dict[str, Any]]:
    """Load canonical persisted artifact pointers without silent omission."""

    if artifacts is None:
        return []
    if isinstance(artifacts, (str, bytes)) or not isinstance(artifacts, Sequence):
        raise InvestigationError("execution.artifacts 必须是数组")
    if len(artifacts) > MAX_EXECUTION_ARTIFACTS:
        raise InvestigationError("execution.artifacts 元素过多")
    allowed = {"role", "path", "uri", "sha256", "kind", "name"}
    result: List[Dict[str, Any]] = []
    for index, item in enumerate(artifacts):
        if not isinstance(item, Mapping):
            raise InvestigationError(f"execution.artifacts[{index}] 必须是对象")
        if set(item) - allowed:
            raise InvestigationError(
                f"execution.artifacts[{index}] 含有不支持的字段"
            )
        for key, value in item.items():
            if value is not None and len(str(value)) > MAX_STATE_TEXT:
                raise InvestigationError(
                    f"execution.artifacts[{index}].{key} 不能超过预算"
                )
        row = {str(key): str(value) for key, value in item.items() if value is not None}
        if row:
            result.append(row)
    return result


def _bounded_artifacts_with_flag(
    artifacts: Any,
) -> tuple[List[Dict[str, Any]], bool, bool, bool]:
    if artifacts is None:
        return [], False, False, False
    if isinstance(artifacts, (str, bytes)) or not isinstance(artifacts, Sequence):
        raise InvestigationError("artifacts 必须是数组")
    allowed = {"role", "path", "uri", "sha256", "kind", "name"}
    fields_truncated = False
    metadata_omitted = False
    for item in artifacts:
        if not isinstance(item, Mapping):
            continue
        if set(item) - allowed:
            metadata_omitted = True
        for key in allowed:
            value = item.get(key)
            if value is not None and len(str(value)) > MAX_STATE_TEXT:
                fields_truncated = True
    return (
        _bounded_artifacts(artifacts),
        len(artifacts) > MAX_EXECUTION_ARTIFACTS,
        fields_truncated,
        metadata_omitted,
    )


def _bounded_text_list(value: Any, *, field_name: str, max_items: int) -> tuple[List[str], bool]:
    if value is None:
        return [], False
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise InvestigationError(f"{field_name} 必须是字符串数组")
    truncated = len(value) > max_items
    result: List[str] = []
    seen = set()
    for item in value[:max_items]:
        resolved = str(item or "").strip()
        if not resolved or resolved in seen:
            continue
        seen.add(resolved)
        result.append(resolved[:MAX_STATE_TEXT])
        truncated = truncated or len(resolved) > MAX_STATE_TEXT
    return result, truncated


def _validate_list(raw: Any, *, field_name: str) -> List[Mapping[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, list) or any(not isinstance(item, Mapping) for item in raw):
        raise InvestigationError(f"{field_name} 必须是对象数组")
    return list(raw)


def _source_session_confidence(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvestigationError("source_session.confidence 必须是 0 到 1 之间的数字")
    resolved = float(value)
    if not math.isfinite(resolved) or resolved < 0.0 or resolved > 1.0:
        raise InvestigationError("source_session.confidence 必须是 0 到 1 之间的数字")
    return resolved


def _normalize_source_session(item: Mapping[str, Any], *, index: int = 0) -> Dict[str, Any]:
    if not isinstance(item, Mapping):
        raise InvestigationError(f"source_sessions[{index}] 必须是对象")
    allowed = {
        "id", "source_id", "identity", "fingerprint", "source_type",
        "format", "segmenter", "extension", "recognition_status",
        "confidence", "coverage", "invalidation_reason", "created_at", "updated_at",
    }
    unsupported = set(item) - allowed
    if unsupported:
        raise InvestigationError(
            f"source_sessions[{index}] 含有不支持的字段: "
            + ", ".join(sorted(str(value) for value in unsupported))
        )
    status = str(item.get("recognition_status") or "unknown").strip().lower()
    if status not in SOURCE_SESSION_STATUSES:
        raise InvestigationError(f"未知 source session status: {status!r}")
    return {
        "id": _validate_id(item.get("id"), field_name="source_session.id"),
        "source_id": _required_text(item.get("source_id"), field_name="source_session.source_id", limit=512),
        "identity": _json_object(item.get("identity") or {}, field_name="source_session.identity"),
        "fingerprint": _optional_text(item.get("fingerprint"), field_name="source_session.fingerprint", limit=512),
        "source_type": _optional_text(item.get("source_type"), field_name="source_session.source_type", limit=256),
        "format": _optional_text(item.get("format"), field_name="source_session.format", limit=256),
        "segmenter": _optional_text(item.get("segmenter"), field_name="source_session.segmenter", limit=256),
        "extension": _optional_text(item.get("extension"), field_name="source_session.extension", limit=256),
        "recognition_status": status,
        "confidence": _source_session_confidence(item.get("confidence")),
        "coverage": _json_object(item.get("coverage") or {}, field_name="source_session.coverage"),
        "invalidation_reason": _optional_text(
            item.get("invalidation_reason"), field_name="source_session.invalidation_reason"
        ),
        "created_at": _required_text(item.get("created_at"), field_name="source_session.created_at", limit=128),
        "updated_at": _required_text(item.get("updated_at"), field_name="source_session.updated_at", limit=128),
    }


def _normalize_source_sessions(raw: Any) -> List[Dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise InvestigationError("source_sessions 必须是数组")
    if len(raw) > MAX_SOURCE_SESSIONS:
        raise InvestigationError("source_sessions 数量超过限制")
    result: List[Dict[str, Any]] = []
    ids: set[str] = set()
    source_ids: set[str] = set()
    for index, item in enumerate(raw):
        normalized = _normalize_source_session(item, index=index)
        if normalized["id"] in ids:
            raise InvestigationError(f"source session id 重复: {normalized['id']}")
        if normalized["source_id"] in source_ids:
            raise InvestigationError(f"source session source_id 重复: {normalized['source_id']}")
        ids.add(normalized["id"])
        source_ids.add(normalized["source_id"])
        result.append(normalized)
    return result


def _source_sessions(state: "InvestigationState") -> List[Dict[str, Any]]:
    return state.source_sessions


def _find_source_session(state: "InvestigationState", session_id: str) -> Dict[str, Any]:
    for item in state.source_sessions:
        if item["id"] == session_id:
            return item
    raise InvestigationError(f"未知 source session: {session_id}")


def _candidate_link_metadata(
    item: Mapping[str, Any],
    *,
    field_name: str,
    require_candidate_id: bool = True,
) -> Dict[str, Any]:
    """Validate the investigation-side knowledge candidate link.

    Candidate payloads, evidence, and review records must never be copied into
    an InvestigationState document.  The state stores only enough metadata to
    navigate to the independently persisted candidate and display its latest
    known lifecycle status.  ``id``/``path`` are accepted as read-compatibility
    aliases for early extension-point documents, but are normalized to the
    canonical names on load.
    """

    if not isinstance(item, Mapping):
        raise InvestigationError(f"{field_name} 必须是对象")
    unsupported = set(item) - KNOWLEDGE_CANDIDATE_LINK_KEYS - {"id", "path"}
    if unsupported:
        raise InvestigationError(
            f"{field_name} 只能包含候选 ID、链接和状态元数据；不支持字段: "
            + ", ".join(sorted(str(value) for value in unsupported))
        )
    candidate_id = item.get("candidate_id") or item.get("id")
    if require_candidate_id or candidate_id:
        candidate_id = _validate_id(
            candidate_id,
            field_name=f"{field_name}.candidate_id",
        )
    finding_id = item.get("finding_id")
    if finding_id:
        finding_id = _validate_id(finding_id, field_name=f"{field_name}.finding_id")
    status = _optional_text(
        item.get("status") or "candidate",
        field_name=f"{field_name}.status",
        limit=128,
    )
    if status not in KNOWLEDGE_CANDIDATE_STATUSES:
        raise InvestigationError(
            f"{field_name}.status 必须是: "
            + ", ".join(sorted(KNOWLEDGE_CANDIDATE_STATUSES))
        )
    store_path = _optional_text(
        item.get("store_path") or item.get("path"),
        field_name=f"{field_name}.store_path",
        limit=MAX_STATE_TEXT,
    )
    link = _optional_text(
        item.get("link") or store_path,
        field_name=f"{field_name}.link",
        limit=MAX_STATE_TEXT,
    )
    created_at = _optional_text(
        item.get("created_at"),
        field_name=f"{field_name}.created_at",
        limit=128,
    )
    normalized: Dict[str, Any] = {
        "candidate_id": candidate_id,
        "finding_id": finding_id or "",
        "status": status,
        "store_path": store_path,
        "link": link,
        "created_at": created_at,
    }
    return normalized


def _candidate_proposal_conflicts(
    candidate: Any,
    *,
    payload: Mapping[str, Any],
    kind: str,
    domain: str,
    scope: str,
    created_by: str,
    case_id: str,
) -> List[str]:
    """Return stable proposal-identity fields that differ from a candidate."""

    conflicts: List[str] = []
    if str(candidate.kind) != kind:
        conflicts.append("kind")
    if str(candidate.domain) != domain:
        conflicts.append("domain")
    if str(candidate.scope) != scope:
        conflicts.append("scope")
    if str(candidate.created_by) != created_by:
        conflicts.append("created_by")
    verifications = list(getattr(candidate, "verifications", ()) or ())
    proposal_case = str(verifications[0].case_id) if verifications else ""
    if proposal_case != case_id:
        conflicts.append("case_id")
    existing_payload = dict(candidate.payload or {})
    # ``source_revision`` records the revision at which the candidate was
    # first proposed.  Linking the candidate increments InvestigationState's
    # revision, so normalize the fresh payload to that frozen revision before
    # comparing.  All caller-controlled payload fields remain exact.
    frozen_revision = existing_payload.get("source_revision")
    normalized_existing = copy.deepcopy(existing_payload)
    normalized_payload = copy.deepcopy(dict(payload))
    if isinstance(frozen_revision, int) and not isinstance(frozen_revision, bool):
        normalized_existing["source_revision"] = frozen_revision
        normalized_payload["source_revision"] = frozen_revision
        existing_source = normalized_existing.get("source")
        payload_source = normalized_payload.get("source")
        if isinstance(existing_source, Mapping):
            normalized_existing["source"] = dict(existing_source)
            normalized_existing["source"]["revision"] = frozen_revision
        if isinstance(payload_source, Mapping):
            normalized_payload["source"] = dict(payload_source)
            normalized_payload["source"]["revision"] = frozen_revision
    if normalized_existing != normalized_payload:
        conflicts.append("payload")
    return conflicts


def _validate_and_normalize(raw: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate the complete graph and return canonical v1 JSON fields."""

    if not isinstance(raw, Mapping):
        raise InvestigationError("investigation 顶层必须是对象")
    version = raw.get("schema_version")
    if not isinstance(version, int) or isinstance(version, bool) or version != INVESTIGATION_SCHEMA_VERSION:
        raise InvestigationError(f"不支持 investigation schema {raw.get('schema_version')!r}")

    investigation_id = _validate_id(raw.get("investigation_id"), field_name="investigation_id")
    status = str(raw.get("status") or "")
    if status not in INVESTIGATION_STATUSES:
        raise InvestigationError(f"未知 investigation status: {status!r}")
    revision = raw.get("revision", 0)
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
        raise InvestigationError("revision 必须是非负整数")
    problem = _json_object(raw.get("problem"), field_name="problem")
    problem["question"] = _required_text(problem.get("question"), field_name="problem.question")
    scope = _json_object(raw.get("scope"), field_name="scope")
    budget_policy = BudgetPolicy.from_mapping(raw.get("budget_policy"))
    budget_usage = _normalize_budget_usage(raw.get("budget_usage"))
    budget_reservations = _normalize_budget_reservations(
        raw.get("budget_reservations")
    )
    created_at = _required_text(raw.get("created_at"), field_name="created_at")
    updated_at = _required_text(raw.get("updated_at"), field_name="updated_at")
    created_by = _optional_text(raw.get("created_by"), field_name="created_by")

    observations: List[Dict[str, Any]] = []
    hypotheses: List[Dict[str, Any]] = []
    tests: List[Dict[str, Any]] = []
    executions: List[Dict[str, Any]] = []
    findings: List[Dict[str, Any]] = []
    knowledge_candidates: List[Dict[str, Any]] = []
    source_sessions = _normalize_source_sessions(raw.get("source_sessions"))
    all_ids: Dict[str, str] = {}

    def remember(identifier: str, kind: str) -> None:
        previous = all_ids.get(identifier)
        if previous is not None:
            raise InvestigationError(f"{kind} id 与 {previous} id 重复: {identifier}")
        all_ids[identifier] = kind

    for index, item in enumerate(_validate_list(raw.get("observations"), field_name="observations")):
        identifier = _validate_id(item.get("id"), field_name=f"observations[{index}].id")
        remember(identifier, "observation")
        observations.append(
            {
                "id": identifier,
                "text": _required_text(item.get("text"), field_name="observation.text"),
                "evidence_refs": _text_list(item.get("evidence_refs", []), field_name="observation.evidence_refs"),
                "metadata": _json_object(item.get("metadata") or {}, field_name="observation.metadata"),
                "created_at": _required_text(item.get("created_at"), field_name="observation.created_at"),
            }
        )

    for index, item in enumerate(_validate_list(raw.get("hypotheses"), field_name="hypotheses")):
        identifier = _validate_id(item.get("id"), field_name=f"hypotheses[{index}].id")
        remember(identifier, "hypothesis")
        hypothesis_status = str(item.get("status") or "open")
        if hypothesis_status not in HYPOTHESIS_STATUSES:
            raise InvestigationError(f"未知 hypothesis status: {hypothesis_status!r}")
        test_ids_raw = item.get("test_ids")
        if test_ids_raw is None:
            test_ids_raw = item.get("tests", [])
        if not isinstance(test_ids_raw, list):
            raise InvestigationError("hypothesis.test_ids 必须是 ID 数组")
        test_ids = [_validate_id(value, field_name="hypothesis.test_ids") for value in test_ids_raw]
        if len(test_ids) != len(set(test_ids)):
            raise InvestigationError(f"hypothesis {identifier} 的 test id 重复")
        hypotheses.append(
            {
                "id": identifier,
                "claim": _required_text(item.get("claim"), field_name="hypothesis.claim"),
                "rationale": _optional_text(item.get("rationale"), field_name="hypothesis.rationale"),
                "status": hypothesis_status,
                "test_ids": test_ids,
                "supporting_evidence": _text_list(item.get("supporting_evidence", []), field_name="hypothesis.supporting_evidence"),
                "contradicting_evidence": _text_list(item.get("contradicting_evidence", []), field_name="hypothesis.contradicting_evidence"),
                "created_at": _required_text(item.get("created_at"), field_name="hypothesis.created_at"),
            }
        )

    for index, item in enumerate(_validate_list(raw.get("tests"), field_name="tests")):
        identifier = _validate_id(item.get("id"), field_name=f"tests[{index}].id")
        remember(identifier, "test")
        execution_ids_raw = item.get("execution_ids", [])
        if not isinstance(execution_ids_raw, list):
            raise InvestigationError("test.execution_ids 必须是 ID 数组")
        execution_ids = [_validate_id(value, field_name="test.execution_ids") for value in execution_ids_raw]
        if len(execution_ids) != len(set(execution_ids)):
            raise InvestigationError(f"test {identifier} 的 execution id 重复")
        tests.append(
            {
                "id": identifier,
                "hypothesis_id": _validate_id(item.get("hypothesis_id"), field_name="test.hypothesis_id"),
                "intent": _required_text(item.get("intent"), field_name="test.intent"),
                "expected_observation": _required_text(item.get("expected_observation"), field_name="test.expected_observation"),
                "contradicting_observation": _required_text(item.get("contradicting_observation"), field_name="test.contradicting_observation"),
                "strategy": _json_object(item.get("strategy") or {}, field_name="test.strategy"),
                "execution_ids": execution_ids,
                "latest_execution_id": (
                    _validate_id(
                        item.get("latest_execution_id"),
                        field_name="test.latest_execution_id",
                    )
                    if item.get("latest_execution_id")
                    else ""
                ),
                "coverage": _json_object(item.get("coverage") or {}, field_name="test.coverage"),
                "created_at": _required_text(item.get("created_at"), field_name="test.created_at"),
            }
        )

    for index, item in enumerate(_validate_list(raw.get("executions"), field_name="executions")):
        identifier = _validate_id(item.get("id"), field_name=f"executions[{index}].id")
        remember(identifier, "execution")
        hypothesis_id = str(item.get("hypothesis_id") or "").strip()
        test_id = str(item.get("test_id") or "").strip()
        if hypothesis_id:
            hypothesis_id = _validate_id(hypothesis_id, field_name="execution.hypothesis_id")
        if test_id:
            test_id = _validate_id(test_id, field_name="execution.test_id")
        executions.append(
            {
                "id": identifier,
                "operation": _required_text(item.get("operation"), field_name="execution.operation", limit=256),
                "hypothesis_id": hypothesis_id or None,
                "test_id": test_id or None,
                "status": _optional_text(
                    item.get("status") or "unknown",
                    field_name="execution.status",
                    limit=128,
                ),
                "outcome": _optional_text(
                    item.get("outcome") or "unknown",
                    field_name="execution.outcome",
                    limit=128,
                ),
                "parameters": _json_object(item.get("parameters") or {}, field_name="execution.parameters"),
                "evidence": _strict_evidence(item.get("evidence") or []),
                "evidence_refs": _text_list(item.get("evidence_refs", []), field_name="execution.evidence_refs", max_items=MAX_EXECUTION_REFS),
                "artifacts": _strict_artifacts(item.get("artifacts") or []),
                "coverage": _json_object(item.get("coverage") or {}, field_name="execution.coverage"),
                "missing_evidence": _strict_json_value(item.get("missing_evidence") or [], field_name="execution.missing_evidence"),
                "warnings": _text_list(item.get("warnings", []), field_name="execution.warnings", max_items=MAX_EXECUTION_WARNINGS),
                "error": _bounded_error(item.get("error"), strict=True),
                "verification": _json_object(item.get("verification") or {}, field_name="execution.verification"),
                "run_id": _optional_text(item.get("run_id"), field_name="execution.run_id", limit=256),
                "verdict": _optional_text(item.get("verdict"), field_name="execution.verdict", limit=256),
                "recording": _json_object(item.get("recording") or {}, field_name="execution.recording"),
                "recorded_at": _required_text(item.get("recorded_at"), field_name="execution.recorded_at"),
            }
        )

    for index, item in enumerate(_validate_list(raw.get("findings"), field_name="findings")):
        identifier = _validate_id(item.get("id"), field_name=f"findings[{index}].id")
        remember(identifier, "finding")
        outcome = str(item.get("outcome") or "").strip().lower()
        if outcome not in FINDING_OUTCOMES:
            raise InvestigationError("finding outcome 必须是 supported / contradicted / unknown")
        supporting_evidence = _text_list(
            item.get("supporting_evidence", []),
            field_name="finding.supporting_evidence",
        )
        contradicting_evidence = _text_list(
            item.get("contradicting_evidence", []),
            field_name="finding.contradicting_evidence",
        )
        if outcome == "supported" and not supporting_evidence:
            raise InvestigationError("supported Finding 必须包含 supporting_evidence")
        if outcome == "contradicted" and not contradicting_evidence:
            raise InvestigationError(
                "contradicted Finding 必须包含 contradicting_evidence"
            )
        findings.append(
            {
                "id": identifier,
                "hypothesis_id": _validate_id(item.get("hypothesis_id"), field_name="finding.hypothesis_id"),
                "outcome": outcome,
                "summary": _required_text(item.get("summary"), field_name="finding.summary"),
                "supporting_evidence": supporting_evidence,
                "contradicting_evidence": contradicting_evidence,
                "coverage": _json_object(item.get("coverage") or {}, field_name="finding.coverage"),
                "limitations": _text_list(item.get("limitations", []), field_name="finding.limitations"),
                "created_at": _required_text(item.get("created_at"), field_name="finding.created_at"),
            }
        )

    for index, item in enumerate(
        _validate_list(raw.get("knowledge_candidates"), field_name="knowledge_candidates")
    ):
        # Keep this list deliberately small: a candidate payload belongs to
        # KnowledgeGovernanceStore, never to the investigation document.
        knowledge_candidates.append(
            _candidate_link_metadata(
                item,
                field_name=f"knowledge_candidates[{index}]",
            )
        )

    hypotheses_by_id = {item["id"]: item for item in hypotheses}
    tests_by_id = {item["id"]: item for item in tests}
    executions_by_id = {item["id"]: item for item in executions}
    findings_by_id = {item["id"]: item for item in findings}
    del findings_by_id  # duplicate IDs were already checked by remember().

    for hypothesis in hypotheses:
        for test_id in hypothesis["test_ids"]:
            test = tests_by_id.get(test_id)
            if test is None:
                raise InvestigationError(f"hypothesis {hypothesis['id']} 引用了未知 test {test_id!r}")
            if test["hypothesis_id"] != hypothesis["id"]:
                raise InvestigationError(f"test {test_id!r} 与 hypothesis 不一致")
    for test in tests:
        hypothesis = hypotheses_by_id.get(test["hypothesis_id"])
        if hypothesis is None:
            raise InvestigationError(f"test {test['id']!r} 引用了未知 hypothesis {test['hypothesis_id']!r}")
        # Accept older/minimal documents that only contain the Test's forward
        # link, but expose the canonical reverse link in the loaded state.
        if test["id"] not in hypothesis["test_ids"]:
            hypothesis["test_ids"].append(test["id"])
        for execution_id in test["execution_ids"]:
            execution = executions_by_id.get(execution_id)
            if execution is None:
                raise InvestigationError(f"test {test['id']!r} 引用了未知 execution {execution_id!r}")
            if execution.get("test_id") != test["id"]:
                raise InvestigationError(f"execution {execution_id!r} 与 test 不一致")
        if test["latest_execution_id"] and test["latest_execution_id"] not in test["execution_ids"]:
            raise InvestigationError(
                f"test {test['id']!r} 的 latest_execution_id 未被 execution_ids 引用"
            )
    for execution in executions:
        hypothesis_id = execution.get("hypothesis_id")
        test_id = execution.get("test_id")
        if hypothesis_id and hypothesis_id not in hypotheses_by_id:
            raise InvestigationError(f"execution 引用了未知 hypothesis {hypothesis_id!r}")
        if test_id:
            test = tests_by_id.get(test_id)
            if test is None:
                raise InvestigationError(f"execution 引用了未知 test {test_id!r}")
            if hypothesis_id and test["hypothesis_id"] != hypothesis_id:
                raise InvestigationError(f"execution 的 hypothesis {hypothesis_id!r} 与 test 不一致")
            if execution["id"] not in test["execution_ids"]:
                test["execution_ids"].append(execution["id"])
    for finding in findings:
        if finding["hypothesis_id"] not in hypotheses_by_id:
            raise InvestigationError(f"finding 引用了未知 hypothesis {finding['hypothesis_id']!r}")

    stop_reason_raw = raw.get("stop_reason")
    stop_reason: Optional[Dict[str, Any]] = None
    if stop_reason_raw is not None:
        if not isinstance(stop_reason_raw, Mapping):
            raise InvestigationError("stop_reason 必须是对象或 null")
        kind = _required_text(stop_reason_raw.get("kind"), field_name="stop_reason.kind", limit=128)
        if kind not in STOP_KINDS:
            raise InvestigationError(f"未知 stop_reason.kind: {kind!r}")
        stop_reason = {
            "kind": kind,
            "detail": _required_text(stop_reason_raw.get("detail"), field_name="stop_reason.detail"),
            "stopped_at": _required_text(stop_reason_raw.get("stopped_at"), field_name="stop_reason.stopped_at"),
        }
    if status == "active" and stop_reason is not None:
        raise InvestigationError("active investigation 不能包含 stop_reason")
    if status == "completed" and stop_reason is None:
        raise InvestigationError("completed investigation 必须包含 stop_reason")

    return {
        "schema_version": INVESTIGATION_SCHEMA_VERSION,
        "investigation_id": investigation_id,
        "revision": revision,
        "status": status,
        "created_at": created_at,
        "updated_at": updated_at,
        "created_by": created_by,
        "problem": problem,
        "scope": scope,
        "budget_policy": budget_policy.to_dict(),
        "budget_usage": budget_usage,
        "budget_reservations": budget_reservations,
        "observations": observations,
        "hypotheses": hypotheses,
        "tests": tests,
        "executions": executions,
        "findings": findings,
        "stop_reason": stop_reason,
        "knowledge_candidates": knowledge_candidates,
        "source_sessions": source_sessions,
    }


@dataclass
class InvestigationState:
    """Serializable cross-tool investigation document."""

    investigation_id: str
    problem: Dict[str, Any]
    scope: Dict[str, Any]
    created_at: str
    updated_at: str
    created_by: str = ""
    status: str = "active"
    revision: int = 0
    budget_policy: Dict[str, Any] = field(default_factory=dict)
    budget_usage: Dict[str, Any] = field(default_factory=_empty_budget_usage)
    budget_reservations: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    observations: List[Dict[str, Any]] = field(default_factory=list)
    hypotheses: List[Dict[str, Any]] = field(default_factory=list)
    tests: List[Dict[str, Any]] = field(default_factory=list)
    executions: List[Dict[str, Any]] = field(default_factory=list)
    findings: List[Dict[str, Any]] = field(default_factory=list)
    stop_reason: Optional[Dict[str, Any]] = None
    knowledge_candidates: List[Dict[str, Any]] = field(default_factory=list)
    source_sessions: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def schema_version(self) -> int:
        """Return the on-disk schema version for callers inspecting a state."""

        return INVESTIGATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        # Public construction is validated just like loading from disk.
        checked = _validate_and_normalize(self.to_dict())
        checked.pop("schema_version", None)
        self.investigation_id = checked["investigation_id"]
        self.problem = checked["problem"]
        self.scope = checked["scope"]
        self.created_at = checked["created_at"]
        self.updated_at = checked["updated_at"]
        self.created_by = checked["created_by"]
        self.status = checked["status"]
        self.revision = checked["revision"]
        self.budget_policy = checked["budget_policy"]
        self.budget_usage = checked["budget_usage"]
        self.budget_reservations = checked["budget_reservations"]
        self.observations = checked["observations"]
        self.hypotheses = checked["hypotheses"]
        self.tests = checked["tests"]
        self.executions = checked["executions"]
        self.findings = checked["findings"]
        self.stop_reason = checked["stop_reason"]
        self.knowledge_candidates = checked["knowledge_candidates"]
        self.source_sessions = checked["source_sessions"]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": INVESTIGATION_SCHEMA_VERSION,
            "investigation_id": self.investigation_id,
            "revision": self.revision,
            "status": self.status,
            "budget_policy": copy.deepcopy(self.budget_policy),
            "budget_usage": copy.deepcopy(self.budget_usage),
            "budget_reservations": copy.deepcopy(self.budget_reservations),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "created_by": self.created_by,
            "problem": copy.deepcopy(self.problem),
            "scope": copy.deepcopy(self.scope),
            "observations": copy.deepcopy(self.observations),
            "hypotheses": copy.deepcopy(self.hypotheses),
            "tests": copy.deepcopy(self.tests),
            "executions": copy.deepcopy(self.executions),
            "findings": copy.deepcopy(self.findings),
            "stop_reason": copy.deepcopy(self.stop_reason),
            "knowledge_candidates": copy.deepcopy(self.knowledge_candidates),
            "source_sessions": copy.deepcopy(self.source_sessions),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "InvestigationState":
        checked = _validate_and_normalize(raw)
        checked.pop("schema_version", None)
        return cls(**checked)


class InvestigationStore:
    """Atomic, locked persistence for one InvestigationState document."""

    def __init__(self, path: Union[str, Path]) -> None:
        self.path = Path(path).expanduser().resolve()

    def create(
        self,
        question: str,
        *,
        scope: Optional[Mapping[str, Any]] = None,
        created_by: str = "",
        investigation_id: Optional[str] = None,
        budget_policy: Optional[Union[BudgetPolicy, Mapping[str, Any]]] = None,
    ) -> InvestigationState:
        resolved_question = _required_text(question, field_name="question")
        if scope is not None and not isinstance(scope, Mapping):
            raise InvestigationError("scope 必须是对象")
        resolved_scope = _json_object(scope or {}, field_name="scope")
        if isinstance(budget_policy, BudgetPolicy):
            resolved_budget_policy = budget_policy.to_dict()
        else:
            resolved_budget_policy = BudgetPolicy.from_mapping(budget_policy).to_dict()
        resolved_id = (
            _validate_id(investigation_id, field_name="investigation_id")
            if investigation_id is not None
            else f"inv-{uuid.uuid4().hex[:16]}"
        )
        now = _now_iso()
        state = InvestigationState(
            investigation_id=resolved_id,
            problem={"question": resolved_question},
            scope=resolved_scope,
            created_at=now,
            updated_at=now,
            created_by=_optional_text(created_by, field_name="created_by"),
            budget_policy=resolved_budget_policy,
        )
        with state_lock(self.path):
            if self.path.exists():
                raise InvestigationError(f"调查状态已存在: {self.path}")
            atomic_write_json(self.path, state.to_dict())
        return state

    def load(self) -> InvestigationState:
        if not self.path.is_file():
            raise InvestigationError(f"调查状态不存在: {self.path}")
        try:
            raw = read_json(self.path)
            return InvestigationState.from_dict(raw)
        except (ValueError, TypeError, KeyError) as exc:
            raise InvestigationError(str(exc)) from exc

    # ``show`` is a small ergonomic alias used by hosts that treat the store as
    # a command-style API; it performs the same validation as ``load``.
    def show(self) -> InvestigationState:
        return self.load()

    def budget_status(self) -> Dict[str, Any]:
        """Return policy, committed usage, and remaining budget counters."""

        state = self.load()
        policy = BudgetPolicy.from_mapping(state.budget_policy)
        usage = _normalize_budget_usage(state.budget_usage)
        return {
            "schema_version": BUDGET_POLICY_SCHEMA_VERSION,
            "policy": policy.to_dict(),
            "usage": usage,
            "remaining": policy.remaining(usage),
            "reservations": copy.deepcopy(state.budget_reservations),
        }

    def set_budget_policy(
        self,
        policy: Optional[Union[BudgetPolicy, Mapping[str, Any]]],
        *,
        reset_usage: bool = False,
    ) -> Dict[str, Any]:
        """Set the optional policy using a locked, versioned state update."""

        resolved = (
            policy
            if isinstance(policy, BudgetPolicy)
            else BudgetPolicy.from_mapping(policy)
        )

        def mutate(state: InvestigationState) -> None:
            self._require_active(state)
            state.budget_policy = resolved.to_dict()
            if reset_usage:
                state.budget_usage = _empty_budget_usage()
                state.budget_reservations = {}

        self._update(mutate)
        return self.budget_status()

    @staticmethod
    def _budget_request(
        *,
        executions: int = 1,
        searches: int = 0,
        queries: int = 0,
        recorded_evidence_pointers: int = 0,
        expand_requested_chars: int = 0,
        expand_returned_chars: int = 0,
        elapsed_seconds: float = 0.0,
    ) -> Dict[str, Union[int, float]]:
        values: Dict[str, Union[int, float]] = {
            "executions": executions,
            "searches": searches,
            "queries": queries,
            "recorded_evidence_pointers": recorded_evidence_pointers,
            "expand_requested_chars": expand_requested_chars,
            "expand_returned_chars": expand_returned_chars,
            "elapsed_seconds": elapsed_seconds,
        }
        for field_name, value in values.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise InvestigationError(f"budget request {field_name} 必须是非负数")
            if not math.isfinite(float(value)) or float(value) < 0:
                raise InvestigationError(f"budget request {field_name} 必须是非负数")
            if field_name != "elapsed_seconds" and not isinstance(value, int):
                raise InvestigationError(f"budget request {field_name} 必须是非负整数")
        return values

    @staticmethod
    def _bounded_end_reason(detail: str) -> Dict[str, Any]:
        return {
            "kind": "budget_exhausted",
            "detail": _required_text(detail, field_name="stop_reason.detail"),
            "stopped_at": _now_iso(),
        }

    def reserve_budget(
        self,
        operation: str,
        *,
        executions: int = 1,
        searches: int = 0,
        queries: int = 0,
        recorded_evidence_pointers: int = 0,
        expand_requested_chars: int = 0,
        expand_returned_chars: int = 0,
        elapsed_seconds: float = 0.0,
    ) -> BudgetReservation:
        """Atomically reserve counters before a linked operation executes.

        A refusal transitions the active InvestigationState to completed with a
        ``budget_exhausted`` stop reason and raises ``BudgetExhausted``.  No
        execution record is written for that refused operation.
        """

        resolved_operation = _required_text(operation, field_name="operation", limit=256)
        requested = self._budget_request(
            executions=executions,
            searches=searches,
            queries=queries,
            recorded_evidence_pointers=recorded_evidence_pointers,
            expand_requested_chars=expand_requested_chars,
            expand_returned_chars=expand_returned_chars,
            elapsed_seconds=elapsed_seconds,
        )
        with state_lock(self.path):
            state = self.load()
            self._require_active(state)
            policy = BudgetPolicy.from_mapping(state.budget_policy)
            usage = _normalize_budget_usage(state.budget_usage)
            projected = {
                key: float(usage[key]) + float(requested[key])
                for key in BUDGET_USAGE_FIELDS
            }
            violations: List[Dict[str, Any]] = []
            if projected["executions"] > float(policy.max_rounds):
                violations.append(
                    {
                        "limit": "max_rounds",
                        "usage": int(usage["executions"]),
                        "requested": int(requested["executions"]),
                        "maximum": policy.max_rounds,
                        "remaining": policy.remaining(usage)["rounds"],
                    }
                )
            if violations:
                detail = (
                    f"{resolved_operation} 被调查预算拒绝: "
                    + ", ".join(item["limit"] for item in violations)
                )
                # An in-flight reservation may still need to finalize and
                # append its execution.  Keep the state active until those
                # reservations drain; a later refusal with no in-flight work
                # records the terminal budget_exhausted stop reason.
                if not state.budget_reservations:
                    state.status = "completed"
                    state.stop_reason = self._bounded_end_reason(detail)
                state.revision += 1
                state.updated_at = _now_iso()
                atomic_write_json(self.path, InvestigationState.from_dict(state.to_dict()).to_dict())
                raise BudgetExhausted(
                    detail,
                    details={
                        "operation": resolved_operation,
                        "violations": violations,
                        "policy": policy.to_dict(),
                        "usage": usage,
                        "remaining": policy.remaining(usage),
                        "pending_reservations": bool(state.budget_reservations),
                    },
                )
            reservation_id = _validate_id(
                f"B{uuid.uuid4().hex[:12]}", field_name="budget_reservation.id"
            )
            state.budget_reservations[reservation_id] = {
                "operation": resolved_operation,
                "created_at": _now_iso(),
                **requested,
            }
            for field_name in BUDGET_USAGE_FIELDS:
                if field_name == "elapsed_seconds":
                    usage[field_name] = float(usage[field_name]) + float(requested[field_name])
                else:
                    usage[field_name] = int(usage[field_name]) + int(requested[field_name])
            state.budget_usage = usage
            state.revision += 1
            state.updated_at = _now_iso()
            checked = InvestigationState.from_dict(state.to_dict())
            atomic_write_json(self.path, checked.to_dict())
        return BudgetReservation(self, reservation_id, requested)

    def finalize_budget(
        self,
        reservation_id: str,
        actual: Mapping[str, Any],
    ) -> Dict[str, Any]:
        """Replace a reservation with measured counters under the state lock."""

        resolved_id = _validate_id(reservation_id, field_name="budget_reservation.id")
        input_returned_chars = int(actual.get("input_returned_chars", 0))
        if input_returned_chars < 0:
            raise InvestigationError("input_returned_chars 必须是非负整数")
        actual_values = self._budget_request(
            executions=int(actual.get("executions", 1)),
            searches=int(actual.get("searches", 0)),
            queries=int(actual.get("queries", 0)),
            recorded_evidence_pointers=int(actual.get("recorded_evidence_pointers", 0)),
            expand_requested_chars=int(actual.get("expand_requested_chars", 0)),
            expand_returned_chars=int(actual.get("expand_returned_chars", 0)),
            elapsed_seconds=float(actual.get("elapsed_seconds", 0.0)),
        )
        with state_lock(self.path):
            state = self.load()
            reservation = state.budget_reservations.get(resolved_id)
            if reservation is None:
                raise InvestigationError(f"未知 budget reservation: {resolved_id}")
            usage = _normalize_budget_usage(state.budget_usage)
            for field_name in BUDGET_USAGE_FIELDS:
                reserved = reservation.get(field_name, 0.0 if field_name == "elapsed_seconds" else 0)
                delta = float(actual_values[field_name]) - float(reserved)
                if field_name == "elapsed_seconds":
                    usage[field_name] = max(0.0, float(usage[field_name]) + delta)
                else:
                    usage[field_name] = max(0, int(round(float(usage[field_name]) + delta)))
            del state.budget_reservations[resolved_id]
            policy = BudgetPolicy.from_mapping(state.budget_policy)
            violations: List[str] = []
            if int(usage["executions"]) > policy.max_rounds:
                violations.append("max_rounds")
            if input_returned_chars > policy.max_input_per_round:
                violations.append("max_input_per_round")
            if violations and state.status == "active":
                state.status = "completed"
                state.stop_reason = self._bounded_end_reason(
                    "执行后测量值超过调查预算: " + ", ".join(violations)
                )
            state.budget_usage = usage
            state.revision += 1
            state.updated_at = _now_iso()
            checked = InvestigationState.from_dict(state.to_dict())
            atomic_write_json(self.path, checked.to_dict())
            return {
                "schema_version": BUDGET_POLICY_SCHEMA_VERSION,
                "policy": policy.to_dict(),
                "usage": usage,
                "remaining": policy.remaining(usage),
                "violations": violations,
                "stop_reason": copy.deepcopy(checked.stop_reason),
            }

    def release_budget(self, reservation_id: str) -> Dict[str, Any]:
        """Release a reservation if a caller aborts before execution."""

        resolved_id = _validate_id(reservation_id, field_name="budget_reservation.id")
        with state_lock(self.path):
            state = self.load()
            reservation = state.budget_reservations.get(resolved_id)
            if reservation is None:
                raise InvestigationError(f"未知 budget reservation: {resolved_id}")
            usage = _normalize_budget_usage(state.budget_usage)
            for field_name in BUDGET_USAGE_FIELDS:
                amount = reservation.get(field_name, 0.0 if field_name == "elapsed_seconds" else 0)
                usage[field_name] = (
                    max(0.0, float(usage[field_name]) - float(amount))
                    if field_name == "elapsed_seconds"
                    else max(0, int(usage[field_name]) - int(amount))
                )
            del state.budget_reservations[resolved_id]
            state.budget_usage = usage
            state.revision += 1
            state.updated_at = _now_iso()
            checked = InvestigationState.from_dict(state.to_dict())
            atomic_write_json(self.path, checked.to_dict())
            policy = BudgetPolicy.from_mapping(checked.budget_policy)
            return {
                "schema_version": BUDGET_POLICY_SCHEMA_VERSION,
                "policy": policy.to_dict(),
                "usage": usage,
                "remaining": policy.remaining(usage),
                "stop_reason": copy.deepcopy(checked.stop_reason),
            }

    def _update(self, mutate: Callable[[InvestigationState], Any]) -> tuple[InvestigationState, Any]:
        with state_lock(self.path):
            state = self.load()
            result = mutate(state)
            state.revision += 1
            state.updated_at = _now_iso()
            checked = InvestigationState.from_dict(state.to_dict())
            atomic_write_json(self.path, checked.to_dict())
            return checked, result

    @staticmethod
    def _require_active(state: InvestigationState) -> None:
        if state.status != "active":
            raise InvestigationError(f"调查状态为 {state.status!r}，不能继续修改")

    @staticmethod
    def _find_hypothesis(state: InvestigationState, hypothesis_id: str) -> Dict[str, Any]:
        for item in state.hypotheses:
            if item["id"] == hypothesis_id:
                return item
        raise InvestigationError(f"未知 hypothesis: {hypothesis_id}")

    @staticmethod
    def _find_test(state: InvestigationState, test_id: str) -> Dict[str, Any]:
        for item in state.tests:
            if item["id"] == test_id:
                return item
        raise InvestigationError(f"未知 test: {test_id}")

    @staticmethod
    def _find_finding(state: InvestigationState, finding_id: str) -> Dict[str, Any]:
        for item in state.findings:
            if item["id"] == finding_id:
                return item
        raise InvestigationError(f"未知 finding: {finding_id}")


    def register_source_session(
        self,
        source_id: str,
        *,
        identity: Optional[Mapping[str, Any]] = None,
        fingerprint: str = "",
        source_type: str = "",
        format: str = "",
        segmenter: str = "",
        extension: str = "",
        recognition_status: str = "known",
        confidence: Optional[float] = None,
        coverage: Optional[Mapping[str, Any]] = None,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Register reusable recognition for one logical source."""

        now = _now_iso()
        session = _normalize_source_session(
            {
                "id": session_id or f"S{uuid.uuid4().hex[:12]}",
                "source_id": source_id,
                "identity": dict(identity or {}),
                "fingerprint": fingerprint,
                "source_type": source_type,
                "format": format,
                "segmenter": segmenter,
                "extension": extension,
                "recognition_status": recognition_status,
                "confidence": confidence,
                "coverage": dict(coverage or {}),
                "invalidation_reason": "",
                "created_at": now,
                "updated_at": now,
            }
        )

        def mutate(state: InvestigationState) -> None:
            self._require_active(state)
            existing = _source_sessions(state)
            if len(existing) >= MAX_SOURCE_SESSIONS:
                raise InvestigationError("source_sessions 数量超过限制")
            if any(item["id"] == session["id"] for item in existing):
                raise InvestigationError(f"source session id 已存在: {session['id']}")
            if any(item["source_id"] == session["source_id"] for item in existing):
                raise InvestigationError(f"source session source_id 已存在: {session['source_id']}")
            existing.append(copy.deepcopy(session))

        self._update(mutate)
        return copy.deepcopy(session)

    def get_source_session(self, session_id: str) -> Dict[str, Any]:
        resolved = _validate_id(session_id, field_name="source_session.id")
        return copy.deepcopy(_find_source_session(self.load(), resolved))

    def list_source_sessions(self) -> List[Dict[str, Any]]:
        return copy.deepcopy(self.load().source_sessions)

    def inspect_source_session(
        self,
        session_id: str,
        *,
        identity: Optional[Mapping[str, Any]] = None,
        fingerprint: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Return reusable/changed state without choosing an Agent strategy."""

        session = self.get_source_session(session_id)
        reasons: List[str] = []
        if identity is not None:
            current_identity = _json_object(identity, field_name="source_session.identity")
            if _canonical_json(current_identity) != _canonical_json(session["identity"]):
                reasons.append("identity_changed")
        if fingerprint is not None:
            current_fingerprint = _optional_text(
                fingerprint, field_name="source_session.fingerprint", limit=512
            )
            if current_fingerprint != session["fingerprint"]:
                reasons.append("fingerprint_changed")
        persisted_status = session["recognition_status"]
        changed = bool(reasons) or persisted_status in {"changed", "needs_revalidation"}
        return {
            "session_id": session["id"],
            "source_id": session["source_id"],
            "status": "changed" if reasons else persisted_status,
            "source_changed": changed,
            "reuse": persisted_status == "known" and not changed,
            "reasons": reasons
            or ([session["invalidation_reason"]] if session["invalidation_reason"] else []),
            "format": session["format"],
            "segmenter": session["segmenter"],
            "extension": session["extension"],
            "confidence": session["confidence"],
            "coverage": copy.deepcopy(session["coverage"]),
        }

    def update_source_session_coverage(
        self, session_id: str, coverage: Mapping[str, Any]
    ) -> Dict[str, Any]:
        resolved = _validate_id(session_id, field_name="source_session.id")
        resolved_coverage = _json_object(coverage, field_name="source_session.coverage")

        def mutate(state: InvestigationState) -> Dict[str, Any]:
            self._require_active(state)
            session = _find_source_session(state, resolved)
            session["coverage"] = copy.deepcopy(resolved_coverage)
            session["updated_at"] = _now_iso()
            return copy.deepcopy(session)

        _, result = self._update(mutate)
        return result

    def invalidate_source_session(
        self,
        session_id: str,
        reason: str,
        *,
        status: str = "needs_revalidation",
    ) -> Dict[str, Any]:
        resolved = _validate_id(session_id, field_name="source_session.id")
        resolved_status = str(status or "").strip().lower()
        if resolved_status not in {"changed", "needs_revalidation"}:
            raise InvestigationError(
                "invalidate_source_session status 必须是 changed / needs_revalidation"
            )
        resolved_reason = _required_text(
            reason, field_name="source_session.invalidation_reason"
        )

        def mutate(state: InvestigationState) -> Dict[str, Any]:
            self._require_active(state)
            session = _find_source_session(state, resolved)
            session["recognition_status"] = resolved_status
            session["invalidation_reason"] = resolved_reason
            session["updated_at"] = _now_iso()
            return copy.deepcopy(session)

        _, result = self._update(mutate)
        return result

    def refresh_source_session(
        self,
        session_id: str,
        *,
        identity: Optional[Mapping[str, Any]] = None,
        fingerprint: Optional[str] = None,
        source_type: Optional[str] = None,
        format: Optional[str] = None,
        segmenter: Optional[str] = None,
        extension: Optional[str] = None,
        confidence: Optional[float] = None,
        coverage: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        resolved = _validate_id(session_id, field_name="source_session.id")

        def mutate(state: InvestigationState) -> Dict[str, Any]:
            self._require_active(state)
            session = _find_source_session(state, resolved)
            if identity is not None:
                session["identity"] = _json_object(
                    identity, field_name="source_session.identity"
                )
            if fingerprint is not None:
                session["fingerprint"] = _optional_text(
                    fingerprint, field_name="source_session.fingerprint", limit=512
                )
            for key, value in (
                ("source_type", source_type),
                ("format", format),
                ("segmenter", segmenter),
                ("extension", extension),
            ):
                if value is not None:
                    session[key] = _optional_text(
                        value, field_name=f"source_session.{key}", limit=256
                    )
            if confidence is not None:
                session["confidence"] = _source_session_confidence(confidence)
            if coverage is not None:
                session["coverage"] = _json_object(
                    coverage, field_name="source_session.coverage"
                )
            session["recognition_status"] = "known"
            session["invalidation_reason"] = ""
            session["updated_at"] = _now_iso()
            return copy.deepcopy(session)

        _, result = self._update(mutate)
        return result
    def add_observation(
        self,
        text: str,
        *,
        evidence_refs: Sequence[str] = (),
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        observation = {
            "id": f"O{uuid.uuid4().hex[:12]}",
            "text": _required_text(text, field_name="observation.text"),
            "evidence_refs": _unique_texts(evidence_refs),
            "metadata": _json_object(metadata or {}, field_name="metadata"),
            "created_at": _now_iso(),
        }

        def mutate(state: InvestigationState) -> None:
            self._require_active(state)
            state.observations.append(observation)

        self._update(mutate)
        return copy.deepcopy(observation)

    def add_hypothesis(
        self,
        claim: str,
        *,
        hypothesis_id: Optional[str] = None,
        rationale: str = "",
    ) -> Dict[str, Any]:
        hypothesis = {
            "id": _validate_id(
                hypothesis_id or f"H{uuid.uuid4().hex[:12]}", field_name="hypothesis.id"
            ),
            "claim": _required_text(claim, field_name="hypothesis.claim"),
            "rationale": _optional_text(rationale, field_name="hypothesis.rationale"),
            "status": "open",
            "test_ids": [],
            "supporting_evidence": [],
            "contradicting_evidence": [],
            "created_at": _now_iso(),
        }

        def mutate(state: InvestigationState) -> None:
            self._require_active(state)
            if any(item["id"] == hypothesis["id"] for item in state.hypotheses):
                raise InvestigationError(f"hypothesis id 已存在: {hypothesis['id']}")
            if any(item["id"] == hypothesis["id"] for item in state.tests + state.executions + state.findings + state.observations):
                raise InvestigationError(f"id 已存在: {hypothesis['id']}")
            state.hypotheses.append(hypothesis)

        self._update(mutate)
        return copy.deepcopy(hypothesis)

    def add_test(
        self,
        hypothesis_id: str,
        intent: str,
        *,
        expected_observation: str,
        contradicting_observation: str,
        strategy: Optional[Mapping[str, Any]] = None,
        test_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        resolved_hypothesis = _validate_id(hypothesis_id, field_name="hypothesis_id")
        test = {
            "id": _validate_id(test_id or f"T{uuid.uuid4().hex[:12]}", field_name="test.id"),
            "hypothesis_id": resolved_hypothesis,
            "intent": _required_text(intent, field_name="test.intent"),
            "expected_observation": _required_text(expected_observation, field_name="test.expected_observation"),
            "contradicting_observation": _required_text(contradicting_observation, field_name="test.contradicting_observation"),
            "strategy": _json_object(strategy or {}, field_name="strategy"),
            "execution_ids": [],
            "latest_execution_id": "",
            "coverage": {},
            "created_at": _now_iso(),
        }

        def mutate(state: InvestigationState) -> None:
            self._require_active(state)
            hypothesis = self._find_hypothesis(state, resolved_hypothesis)
            if hypothesis["status"] != "open":
                raise InvestigationError("已完成判断的 hypothesis 不能新增 test")
            existing_ids = {item["id"] for item in state.hypotheses + state.tests + state.executions + state.findings + state.observations}
            if test["id"] in existing_ids:
                raise InvestigationError(f"id 已存在: {test['id']}")
            state.tests.append(test)
            hypothesis.setdefault("test_ids", []).append(test["id"])

        self._update(mutate)
        return copy.deepcopy(test)

    def record_execution(
        self,
        operation: str,
        result: Mapping[str, Any],
        *,
        hypothesis_id: Optional[str] = None,
        test_id: Optional[str] = None,
        parameters: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Record bounded result metadata without copying ``result['data']``."""

        if not isinstance(result, Mapping):
            raise InvestigationError("result 必须是对象")
        resolved_hypothesis = (
            _validate_id(hypothesis_id, field_name="hypothesis_id")
            if hypothesis_id
            else None
        )
        resolved_test = _validate_id(test_id, field_name="test_id") if test_id else None
        original_evidence = result.get("evidence") or []
        (
            bounded_evidence,
            evidence_truncated,
            evidence_metadata_omitted,
            evidence_fields_truncated,
        ) = _bounded_evidence_with_flags(original_evidence)
        bounded_evidence_refs, evidence_refs_truncated = _bounded_evidence_refs(
            original_evidence
        )
        bounded_parameters, parameters_truncated = _bounded_external_object(
            parameters or {}, field_name="parameters"
        )
        (
            bounded_artifacts,
            artifacts_truncated,
            artifact_fields_truncated,
            artifact_metadata_omitted,
        ) = _bounded_artifacts_with_flag(
            result.get("artifacts") or []
        )
        bounded_coverage, coverage_truncated = _bounded_external_object(
            result.get("coverage") or {}, field_name="coverage"
        )
        bounded_missing, missing_truncated = _bounded_value_with_flag(
            _json_value(result.get("missing_evidence") or [], field_name="missing_evidence")
        )
        bounded_warnings, warnings_truncated = _bounded_text_list(
            result.get("warnings", []),
            field_name="warnings",
            max_items=MAX_EXECUTION_WARNINGS,
        )
        bounded_verification, verification_truncated = _bounded_external_object(
            result.get("verification") or {}, field_name="verification"
        )
        bounded_error, error_truncated = _bounded_error_with_flag(
            result.get("error")
        )
        execution = {
            "id": _validate_id(f"X{uuid.uuid4().hex[:12]}", field_name="execution.id"),
            "operation": _required_text(operation, field_name="operation", limit=256),
            "hypothesis_id": resolved_hypothesis,
            "test_id": resolved_test,
            "status": str(result.get("status") or "unknown")[:128],
            "outcome": str(result.get("outcome") or "unknown")[:128],
            "parameters": bounded_parameters,
            "evidence": bounded_evidence,
            "evidence_refs": bounded_evidence_refs,
            "artifacts": bounded_artifacts,
            "coverage": bounded_coverage,
            "missing_evidence": bounded_missing,
            "warnings": bounded_warnings,
            "error": bounded_error,
            "verification": bounded_verification,
            "run_id": _optional_text(result.get("run_id"), field_name="run_id", limit=256),
            "verdict": _optional_text(result.get("verdict"), field_name="verdict", limit=256),
            "recording": {
                "data_omitted": True,
                "data_present": "data" in result,
                "text_omitted": True,
                "parameters_truncated": parameters_truncated,
                "evidence_truncated": evidence_truncated,
                "evidence_refs_truncated": evidence_refs_truncated,
                "evidence_metadata_omitted": evidence_metadata_omitted,
                "evidence_fields_truncated": evidence_fields_truncated,
                "artifacts_truncated": artifacts_truncated,
                "artifact_fields_truncated": artifact_fields_truncated,
                "artifact_metadata_omitted": artifact_metadata_omitted,
                "coverage_truncated": coverage_truncated,
                "missing_evidence_truncated": missing_truncated,
                "warnings_truncated": warnings_truncated,
                "verification_truncated": verification_truncated,
                "error_truncated": error_truncated,
            },
            "recorded_at": _now_iso(),
        }

        def mutate(state: InvestigationState) -> None:
            self._require_active(state)
            hypothesis = self._find_hypothesis(state, resolved_hypothesis) if resolved_hypothesis else None
            test = self._find_test(state, resolved_test) if resolved_test else None
            if test is not None:
                expected_hypothesis = test["hypothesis_id"]
                if resolved_hypothesis and expected_hypothesis != resolved_hypothesis:
                    raise InvestigationError("test 与 hypothesis 不属于同一调查分支")
                execution["hypothesis_id"] = expected_hypothesis
                if hypothesis is None:
                    hypothesis = self._find_hypothesis(state, expected_hypothesis)
            state.executions.append(execution)
            if test is not None:
                test.setdefault("execution_ids", []).append(execution["id"])
                test["latest_execution_id"] = execution["id"]

        state, _ = self._update(mutate)
        execution["investigation_id"] = state.investigation_id
        execution["revision"] = state.revision
        return copy.deepcopy(execution)

    def add_finding(
        self,
        hypothesis_id: str,
        outcome: str,
        summary: str,
        *,
        supporting_evidence: Sequence[str] = (),
        contradicting_evidence: Sequence[str] = (),
        coverage: Optional[Mapping[str, Any]] = None,
        limitations: Sequence[str] = (),
    ) -> Dict[str, Any]:
        resolved_hypothesis = _validate_id(hypothesis_id, field_name="hypothesis_id")
        resolved_outcome = str(outcome or "").strip().lower()
        if resolved_outcome not in FINDING_OUTCOMES:
            raise InvestigationError("finding outcome 必须是 supported / contradicted / unknown")
        resolved_supporting = _unique_texts(supporting_evidence)
        resolved_contradicting = _unique_texts(contradicting_evidence)
        if resolved_outcome == "supported" and not resolved_supporting:
            raise InvestigationError("supported Finding 必须包含 supporting_evidence")
        if resolved_outcome == "contradicted" and not resolved_contradicting:
            raise InvestigationError(
                "contradicted Finding 必须包含 contradicting_evidence"
            )
        finding = {
            "id": _validate_id(f"F{uuid.uuid4().hex[:12]}", field_name="finding.id"),
            "hypothesis_id": resolved_hypothesis,
            "outcome": resolved_outcome,
            "summary": _required_text(summary, field_name="finding.summary"),
            "supporting_evidence": resolved_supporting,
            "contradicting_evidence": resolved_contradicting,
            "coverage": _json_object(coverage or {}, field_name="coverage"),
            "limitations": _unique_texts(limitations),
            "created_at": _now_iso(),
        }

        def mutate(state: InvestigationState) -> None:
            self._require_active(state)
            hypothesis = self._find_hypothesis(state, resolved_hypothesis)
            if hypothesis["status"] != "open":
                raise InvestigationError("hypothesis 已有 Finding，不能重复定案")
            if not any(item["hypothesis_id"] == resolved_hypothesis for item in state.tests):
                raise InvestigationError("Finding 前必须先为 hypothesis 创建 Test")
            existing_ids = {item["id"] for item in state.hypotheses + state.tests + state.executions + state.findings + state.observations}
            if finding["id"] in existing_ids:
                raise InvestigationError(f"id 已存在: {finding['id']}")
            state.findings.append(finding)
            hypothesis["status"] = resolved_outcome
            hypothesis["supporting_evidence"] = _unique_texts(list(hypothesis.get("supporting_evidence") or []) + finding["supporting_evidence"])
            hypothesis["contradicting_evidence"] = _unique_texts(list(hypothesis.get("contradicting_evidence") or []) + finding["contradicting_evidence"])

        self._update(mutate)
        return copy.deepcopy(finding)

    def propose_knowledge_candidate(
        self,
        finding_id: str,
        governance_store: Optional["KnowledgeGovernanceStore"] = None,
        *,
        candidate_store: Optional["KnowledgeGovernanceStore"] = None,
        knowledge_store: Optional["KnowledgeGovernanceStore"] = None,
        governance_store_path: Optional[Union[str, Path]] = None,
        candidate_store_path: Optional[Union[str, Path]] = None,
        knowledge_store_path: Optional[Union[str, Path]] = None,
        kind: str = "finding",
        domain: str = "generic",
        scope: str = "global",
        created_by: Optional[str] = None,
        case_id: Optional[str] = None,
        applicability: Any = None,
        exclusions: Any = None,
        test_recipes: Optional[Sequence[Any]] = None,
    ) -> "KnowledgeCandidate":
        """Explicitly propose an eligible Finding as a Knowledge Candidate.

        This operation is intentionally separate from :meth:`add_finding`.
        It first writes to the independent ``KnowledgeGovernanceStore`` and
        only then records a small candidate link in this investigation.  A
        failed proposal therefore cannot leave a state file claiming that a
        candidate exists.  Repeating the operation for the same Finding is
        idempotent: an existing state link or matching candidate payload is
        reused instead of creating a second proposal.

        Only a ``supported`` Finding with supporting Evidence and at least one
        related Test is eligible.  ``unknown`` and ``contradicted`` Findings
        are deliberately rejected so they can never enter the reusable-claim
        lifecycle as supported Knowledge.
        """

        # Import lazily to keep the runtime module usable in minimal imports
        # and to avoid a package-initialization cycle through tracecite.__init__.
        from tracecite.knowledge import KnowledgeGovernanceStore

        resolved_finding = _validate_id(finding_id, field_name="finding_id")
        stores = [
            item
            for item in (governance_store, candidate_store, knowledge_store)
            if item is not None
        ]
        if len(stores) > 1 and any(item is not stores[0] for item in stores[1:]):
            raise InvestigationError(
                "governance_store、candidate_store 和 knowledge_store 只能指定一个"
            )
        store_obj = stores[0] if stores else None
        paths = [
            item
            for item in (
                governance_store_path,
                candidate_store_path,
                knowledge_store_path,
            )
            if item is not None
        ]
        if len(paths) > 1:
            resolved_paths = {str(Path(item).expanduser().resolve()) for item in paths}
            if len(resolved_paths) != 1:
                raise InvestigationError(
                    "governance_store_path、candidate_store_path 和 knowledge_store_path 只能指定一个"
                )
        if store_obj is None:
            if paths:
                store_obj = KnowledgeGovernanceStore(Path(paths[0]))
            else:
                raise InvestigationError(
                    "必须提供独立的 governance_store 或 candidate_store_path"
                )
        if not isinstance(store_obj, KnowledgeGovernanceStore):
            raise InvestigationError("governance_store 必须是 KnowledgeGovernanceStore")
        candidate_path = Path(store_obj.path).expanduser().resolve()
        if candidate_path == self.path:
            raise InvestigationError(
                "候选知识库必须与 InvestigationState 分开保存"
            )

        def _caller_json(value: Any, *, field_name: str, default: Any) -> Any:
            checked = default if value is None else value
            return _strict_json_value(checked, field_name=field_name)

        resolved_applicability = _caller_json(
            applicability,
            field_name="candidate.applicability",
            default={},
        )
        resolved_exclusions = _caller_json(
            exclusions,
            field_name="candidate.exclusions",
            default=[],
        )
        if test_recipes is not None:
            if isinstance(test_recipes, (str, bytes)) or not isinstance(
                test_recipes, Sequence
            ):
                raise InvestigationError("candidate.test_recipes 必须是数组")
            resolved_recipes = _strict_json_value(
                list(test_recipes),
                field_name="candidate.test_recipes",
            )
        else:
            resolved_recipes = None

        # Hold the investigation lock across proposal and link persistence.
        # This serializes duplicate callers for one state file.  Governance
        # writes are independent; if the final state write fails, the matching
        # payload is discovered on the next call and linked idempotently.
        with state_lock(self.path):
            state = self.load()
            finding = self._find_finding(state, resolved_finding)
            outcome = str(finding.get("outcome") or "").strip().lower()
            if outcome != "supported":
                raise InvestigationError(
                    "只有 supported Finding 才能提议可复用 Knowledge Candidate；"
                    f"当前 outcome 为 {outcome or 'unknown'}"
                )
            supporting_refs = _citable_evidence_refs(
                finding.get("supporting_evidence") or (),
                field_name="finding.supporting_evidence",
            )
            if not supporting_refs:
                raise InvestigationError(
                    "supported Finding 必须包含 supporting_evidence，才能提议候选"
                )
            contradicting_refs = _citable_evidence_refs(
                finding.get("contradicting_evidence") or (),
                field_name="finding.contradicting_evidence",
            )
            hypothesis = self._find_hypothesis(
                state,
                _validate_id(finding.get("hypothesis_id"), field_name="finding.hypothesis_id"),
            )
            if str(hypothesis.get("status") or "").strip().lower() != "supported":
                raise InvestigationError(
                    "Finding 对应的 hypothesis 必须仍为 supported，不能提议候选"
                )
            relevant_tests = [
                copy.deepcopy(item)
                for item in state.tests
                if item.get("hypothesis_id") == hypothesis["id"]
            ]
            if not relevant_tests:
                raise InvestigationError(
                    "Knowledge Candidate 必须关联至少一个已声明的 Test"
                )
            resolved_creator = _optional_text(
                created_by if created_by is not None else state.created_by,
                field_name="created_by",
            )
            if not resolved_creator:
                raise InvestigationError(
                    "必须提供 created_by（或在 Investigation 创建时设置 created_by）"
                )
            resolved_case = _optional_text(
                case_id if case_id is not None else state.investigation_id,
                field_name="case_id",
            )
            if not resolved_case:
                raise InvestigationError("case_id 不能为空")
            resolved_kind = str(kind).strip() or "finding"
            resolved_domain = str(domain).strip() or "generic"
            resolved_scope = str(scope).strip() or "global"

            # The candidate payload is intentionally complete enough for an
            # independent reviewer, while only the link below enters state.
            strategy_rows = [
                {
                    "id": item["id"],
                    "intent": item["intent"],
                    "strategy": copy.deepcopy(item.get("strategy") or {}),
                }
                for item in relevant_tests
            ]
            recipe_rows = [
                {
                    "id": item["id"],
                    "intent": item["intent"],
                    "expected_observation": item["expected_observation"],
                    "contradicting_observation": item["contradicting_observation"],
                    "strategy": copy.deepcopy(item.get("strategy") or {}),
                }
                for item in relevant_tests
            ]
            if resolved_recipes is not None:
                recipe_rows = resolved_recipes
            source = {
                "schema_version": INVESTIGATION_SCHEMA_VERSION,
                "revision": state.revision,
            }
            payload: Dict[str, Any] = {
                "investigation_id": state.investigation_id,
                "finding_id": finding["id"],
                "hypothesis_id": hypothesis["id"],
                "hypothesis_claim": hypothesis["claim"],
                "outcome": outcome,
                "summary": finding["summary"],
                "applicability": copy.deepcopy(resolved_applicability),
                "exclusions": copy.deepcopy(resolved_exclusions),
                "supporting_refs": list(supporting_refs),
                "contradicting_refs": list(contradicting_refs),
                "coverage": copy.deepcopy(finding.get("coverage") or {}),
                "limitations": list(finding.get("limitations") or []),
                "test_strategy": strategy_rows,
                "test_recipes": recipe_rows,
                "source_schema": INVESTIGATION_SCHEMA_VERSION,
                "source_revision": state.revision,
                "source": source,
                # Nested aliases make the payload self-describing to generic
                # reviewers while retaining the stable direct fields above.
                "hypothesis": {
                    "id": hypothesis["id"],
                    "claim": hypothesis["claim"],
                },
                "finding": {
                    "id": finding["id"],
                    "outcome": outcome,
                    "summary": finding["summary"],
                },
                "supporting_evidence": list(supporting_refs),
                "contradicting_evidence": list(contradicting_refs),
            }
            # Governance validates JSON, but validating here gives callers a
            # consistent InvestigationError boundary before any external write.
            payload = dict(_strict_json_value(payload, field_name="candidate.payload"))

            # A state link is authoritative for this operation.  If a previous
            # attempt created a candidate but failed before state persistence,
            # discover it by its immutable investigation/finding identity and
            # attach that candidate rather than proposing a duplicate.
            linked: Optional[Dict[str, Any]] = None
            for item in state.knowledge_candidates:
                if item.get("finding_id") == finding["id"]:
                    linked = item
                    break
            if linked is not None:
                linked_store = str(
                    linked.get("store_path") or linked.get("link") or ""
                ).strip()
                if linked_store and Path(linked_store).expanduser().resolve() != candidate_path:
                    raise InvestigationError(
                        "候选提案冲突: store_path（同一 Finding 已链接到其他候选库）"
                    )
                try:
                    existing_candidate = store_obj.get(str(linked["candidate_id"]))
                except Exception as exc:
                    raise InvestigationError(
                        "Investigation 已链接候选，但候选库中找不到该候选；"
                        "请修复链接后再提议"
                    ) from exc
                conflicts = _candidate_proposal_conflicts(
                    existing_candidate,
                    payload=payload,
                    kind=resolved_kind,
                    domain=resolved_domain,
                    scope=resolved_scope,
                    created_by=resolved_creator,
                    case_id=resolved_case,
                )
                if conflicts:
                    raise InvestigationError(
                        "候选提案冲突（同一 Finding 已存在不同身份或 payload）: "
                        + ", ".join(conflicts)
                    )
                return existing_candidate

            existing_candidate = None
            for item in store_obj.list_candidates():
                item_payload = item.payload or {}
                if (
                    str(item_payload.get("investigation_id") or "")
                    == state.investigation_id
                    and str(item_payload.get("finding_id") or "") == finding["id"]
                ):
                    existing_candidate = item
                    break
            if existing_candidate is not None:
                conflicts = _candidate_proposal_conflicts(
                    existing_candidate,
                    payload=payload,
                    kind=resolved_kind,
                    domain=resolved_domain,
                    scope=resolved_scope,
                    created_by=resolved_creator,
                    case_id=resolved_case,
                )
                if conflicts:
                    raise InvestigationError(
                        "候选提案冲突（同一 Finding 已存在不同身份或 payload）: "
                        + ", ".join(conflicts)
                    )
            if existing_candidate is None:
                try:
                    existing_candidate = store_obj.propose(
                        kind=resolved_kind,
                        payload=payload,
                        domain=resolved_domain,
                        scope=resolved_scope,
                        created_by=resolved_creator,
                        case_id=resolved_case,
                        # A supported Finding's initial governance case is
                        # backed by its supporting Evidence.  Contradicting
                        # refs stay visible in payload and are considered by
                        # independent review, not counted as support.
                        evidence_refs=supporting_refs,
                    )
                except Exception:
                    # Deliberately do not mutate state on proposal failure.
                    raise

            link = _candidate_link_metadata(
                {
                    "candidate_id": existing_candidate.id,
                    "finding_id": finding["id"],
                    "status": existing_candidate.status,
                    "store_path": str(candidate_path),
                    "link": str(candidate_path),
                    "created_at": _now_iso(),
                },
                field_name="knowledge_candidates.link",
            )
            state.knowledge_candidates.append(link)
            state.revision += 1
            state.updated_at = _now_iso()
            checked = InvestigationState.from_dict(state.to_dict())
            atomic_write_json(self.path, checked.to_dict())
            return existing_candidate

    # Short alias for hosts that call the operation "propose candidate".
    def propose_candidate(self, finding_id: str, governance_store: Optional["KnowledgeGovernanceStore"] = None, **kwargs: Any) -> "KnowledgeCandidate":
        return self.propose_knowledge_candidate(
            finding_id,
            governance_store,
            **kwargs,
        )

    def stop(self, reason: str, *, kind: str = "completed") -> InvestigationState:
        resolved_kind = _required_text(kind, field_name="stop_reason.kind", limit=128)
        if resolved_kind not in STOP_KINDS:
            raise InvestigationError(f"未知 stop_reason.kind: {resolved_kind!r}")
        stop_reason = {
            "kind": resolved_kind,
            "detail": _required_text(reason, field_name="stop_reason.detail"),
            "stopped_at": _now_iso(),
        }

        def mutate(state: InvestigationState) -> None:
            self._require_active(state)
            state.status = "completed"
            state.stop_reason = stop_reason

        state, _ = self._update(mutate)
        return state


def create_investigation(
    path: Union[str, Path],
    question: str,
    *,
    scope: Optional[Mapping[str, Any]] = None,
    created_by: str = "",
    investigation_id: Optional[str] = None,
    budget_policy: Optional[Union[BudgetPolicy, Mapping[str, Any]]] = None,
) -> InvestigationState:
    """Create a versioned investigation at ``path``."""

    return InvestigationStore(path).create(
        question,
        scope=scope,
        created_by=created_by,
        investigation_id=investigation_id,
        budget_policy=budget_policy,
    )


def load_investigation(path: Union[str, Path]) -> InvestigationState:
    """Load and validate a persisted investigation document."""

    return InvestigationStore(path).load()


def propose_knowledge_candidate(
    investigation_path: Union[str, Path],
    finding_id: str,
    governance_store: Optional["KnowledgeGovernanceStore"] = None,
    **kwargs: Any,
) -> "KnowledgeCandidate":
    """Propose one supported Finding through an independent governance store."""

    return InvestigationStore(investigation_path).propose_knowledge_candidate(
        finding_id,
        governance_store,
        **kwargs,
    )


def propose_candidate(
    investigation_path: Union[str, Path],
    finding_id: str,
    governance_store: Optional["KnowledgeGovernanceStore"] = None,
    **kwargs: Any,
) -> "KnowledgeCandidate":
    """Compatibility alias for :func:`propose_knowledge_candidate`."""

    return propose_knowledge_candidate(
        investigation_path,
        finding_id,
        governance_store,
        **kwargs,
    )


def attach_investigation_result(
    result: Mapping[str, Any],
    *,
    operation: str,
    investigation_path: Optional[Union[str, Path]] = None,
    hypothesis_id: Optional[str] = None,
    test_id: Optional[str] = None,
    parameters: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Optionally record a tool result and attach its stable state link."""

    payload = dict(result)
    if investigation_path is None:
        if hypothesis_id or test_id:
            raise InvestigationError("hypothesis_id/test_id 需要同时提供 investigation_path")
        return payload
    store = InvestigationStore(investigation_path)
    execution = store.record_execution(
        operation,
        payload,
        hypothesis_id=hypothesis_id,
        test_id=test_id,
        parameters=parameters,
    )
    payload["investigation"] = {
        "path": str(store.path),
        "investigation_id": execution["investigation_id"],
        "revision": execution["revision"],
        "hypothesis_id": execution.get("hypothesis_id"),
        "test_id": execution.get("test_id"),
        "execution_id": execution["id"],
    }
    return payload


__all__ = [
    "BUDGET_POLICY_SCHEMA_VERSION",
    "BudgetExhausted",
    "BudgetPolicy",
    "BudgetReservation",
    "InvestigationCacheStore",
    "FINDING_OUTCOMES",
    "SOURCE_SESSION_STATUSES",
    "HYPOTHESIS_STATUSES",
    "INVESTIGATION_SCHEMA_VERSION",
    "INVESTIGATION_STATUSES",
    "STOP_KINDS",
    "InvestigationError",
    "InvestigationState",
    "InvestigationStore",
    "attach_investigation_result",
    "create_investigation",
    "load_investigation",
    "propose_candidate",
    "propose_knowledge_candidate",
]
