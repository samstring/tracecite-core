"""Domain-neutral governance for knowledge proposed by agents.

The evidence/runtime layer does not define domain knowledge.  This module only
owns the lifecycle around it: proposals are stored separately, independent
cases verify them, and an explicit reviewer authorizes promotion through a
domain adapter.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Union

from tracecite_core.state_file import state_lock


GOVERNANCE_SCHEMA_VERSION = 2
LEGACY_GOVERNANCE_SCHEMA_VERSION = 1
CANDIDATE_STATUSES = (
    "candidate",
    "verified",
    "contradicted",
    "promoted",
    "superseded",
)
VERIFICATION_OUTCOMES = ("support", "contradict")
VALIDITY_STATES = (
    "not_promoted",
    "not_reviewed",
    "current",
    "stale",
    "expired",
    "superseded",
)

MAX_METADATA_KEYS = 32
MAX_METADATA_ITEMS = 64
MAX_METADATA_TEXT = 512
MAX_METADATA_BYTES = 8192
MAX_REVALIDATION_HISTORY = 32
MAX_PROMOTION_RESULT_BYTES = 16384
_VALIDITY_KEYS = frozenset(
    {
        "source_version",
        "tool_version",
        "schema_version",
        "reviewed_at",
        "reviewed_by",
        "expires_at",
        "revalidate_after",
        "conditions",
    }
)


class KnowledgeGovernanceError(RuntimeError):
    """A proposal, verification, promotion, or integrity check failed."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _text(value: Any, *, field_name: str, required: bool = False) -> str:
    if value is None:
        resolved = ""
    elif isinstance(value, bool):
        resolved = str(value).lower()
    else:
        resolved = str(value).strip()
    if len(resolved) > MAX_METADATA_TEXT:
        raise KnowledgeGovernanceError(
            f"{field_name} 超过 {MAX_METADATA_TEXT} 个字符"
        )
    if required and not resolved:
        raise KnowledgeGovernanceError(f"{field_name} 不能为空")
    return resolved


def _parse_datetime(value: Any, *, field_name: str, required: bool = False) -> str:
    resolved = _text(value, field_name=field_name, required=required)
    if not resolved:
        return ""
    try:
        parsed = datetime.fromisoformat(resolved.replace("Z", "+00:00"))
    except ValueError as exc:
        raise KnowledgeGovernanceError(
            f"{field_name} 必须是 ISO-8601 时间"
        ) from exc
    if parsed.tzinfo is None:
        # Preserve the caller's spelling for compatibility, but interpret
        # legacy naive timestamps as UTC during comparisons.
        return resolved
    return resolved


def _datetime_value(value: str, *, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise KnowledgeGovernanceError(
            f"{field_name} 必须是 ISO-8601 时间"
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _bounded_json(value: Any, *, field_name: str, depth: int = 0) -> Any:
    """Validate JSON metadata without imposing domain-specific keys."""

    if depth > 6:
        raise KnowledgeGovernanceError(f"{field_name} 嵌套层级过深")
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise KnowledgeGovernanceError(f"{field_name} 必须是有限 JSON 数字")
        return value
    if isinstance(value, str):
        if len(value) > MAX_METADATA_TEXT:
            raise KnowledgeGovernanceError(
                f"{field_name} 文本超过 {MAX_METADATA_TEXT} 个字符"
            )
        return value
    if isinstance(value, Mapping):
        if len(value) > MAX_METADATA_KEYS:
            raise KnowledgeGovernanceError(
                f"{field_name} 字段数超过 {MAX_METADATA_KEYS}"
            )
        result: Dict[str, Any] = {}
        for key, item in value.items():
            resolved_key = _text(key, field_name=f"{field_name}.key", required=True)
            result[resolved_key] = _bounded_json(
                item,
                field_name=f"{field_name}.{resolved_key}",
                depth=depth + 1,
            )
        return result
    if isinstance(value, (list, tuple)):
        if len(value) > MAX_METADATA_ITEMS:
            raise KnowledgeGovernanceError(
                f"{field_name} 项数超过 {MAX_METADATA_ITEMS}"
            )
        return [
            _bounded_json(item, field_name=f"{field_name}[{index}]", depth=depth + 1)
            for index, item in enumerate(value)
        ]
    raise KnowledgeGovernanceError(f"{field_name} 必须是 JSON 值")


def _bounded_payload(value: Any, *, field_name: str) -> Any:
    checked = _bounded_json(value, field_name=field_name)
    try:
        encoded = json.dumps(checked, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise KnowledgeGovernanceError(f"{field_name} 必须可以序列化为 JSON") from exc
    if len(encoded.encode("utf-8")) > MAX_METADATA_BYTES:
        raise KnowledgeGovernanceError(
            f"{field_name} 超过 {MAX_METADATA_BYTES} 字节"
        )
    return checked


def _bounded_promotion_result(value: Any) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        raise KnowledgeGovernanceError("promotion_result 必须是对象")
    checked = _bounded_json(dict(value), field_name="promotion_result")
    encoded = json.dumps(checked, ensure_ascii=False, sort_keys=True)
    if len(encoded.encode("utf-8")) > MAX_PROMOTION_RESULT_BYTES:
        raise KnowledgeGovernanceError(
            f"promotion_result 超过 {MAX_PROMOTION_RESULT_BYTES} 字节"
        )
    return dict(checked)


def _default_validity(*, promoted_at: str = "", created_at: str = "") -> Dict[str, Any]:
    return {
        "source_version": "unknown",
        "tool_version": "unknown",
        "schema_version": "unknown",
        "reviewed_at": promoted_at or created_at or "",
        "reviewed_by": "",
        "expires_at": "",
        "revalidate_after": "",
        "conditions": {},
    }


def _normalise_validity(
    value: Optional[Mapping[str, Any]],
    *,
    promoted_at: str = "",
    created_at: str = "",
    require_reviewed_at: bool = False,
) -> Dict[str, Any]:
    raw = dict(value or {})
    unknown = sorted(set(raw) - _VALIDITY_KEYS)
    if unknown:
        raise KnowledgeGovernanceError(
            "validity 包含未知字段: " + ", ".join(str(item) for item in unknown)
        )
    defaults = _default_validity(promoted_at=promoted_at, created_at=created_at)
    source_version = _text(
        raw.get("source_version", defaults["source_version"]),
        field_name="validity.source_version",
        required=True,
    )
    tool_version = _text(
        raw.get("tool_version", defaults["tool_version"]),
        field_name="validity.tool_version",
        required=True,
    )
    schema_version = _text(
        raw.get("schema_version", defaults["schema_version"]),
        field_name="validity.schema_version",
        required=True,
    )
    reviewed_at = _parse_datetime(
        raw.get("reviewed_at", defaults["reviewed_at"]),
        field_name="validity.reviewed_at",
        required=require_reviewed_at,
    )
    reviewed_by = _text(
        raw.get("reviewed_by", defaults["reviewed_by"]),
        field_name="validity.reviewed_by",
    )
    expires_at = _parse_datetime(
        raw.get("expires_at", defaults["expires_at"]),
        field_name="validity.expires_at",
    )
    revalidate_after = _parse_datetime(
        raw.get("revalidate_after", defaults["revalidate_after"]),
        field_name="validity.revalidate_after",
    )
    conditions = _bounded_payload(
        raw.get("conditions", defaults["conditions"]),
        field_name="validity.conditions",
    )
    result = {
        "source_version": source_version,
        "tool_version": tool_version,
        "schema_version": schema_version,
        "reviewed_at": reviewed_at,
        "reviewed_by": reviewed_by,
        "expires_at": expires_at,
        "revalidate_after": revalidate_after,
        "conditions": conditions,
    }
    encoded = json.dumps(result, ensure_ascii=False, sort_keys=True)
    if len(encoded.encode("utf-8")) > MAX_METADATA_BYTES:
        raise KnowledgeGovernanceError(
            f"validity 超过 {MAX_METADATA_BYTES} 字节"
        )
    return result


def _validity_from_args(
    *,
    validity: Optional[Mapping[str, Any]] = None,
    validity_metadata: Optional[Mapping[str, Any]] = None,
    source_version: Any = "unknown",
    tool_version: Any = "unknown",
    schema_version: Any = "unknown",
    reviewed_at: Any = None,
    reviewed_by: Any = "",
    expires_at: Any = None,
    revalidate_after: Any = None,
    conditions: Any = None,
    require_reviewed_at: bool = True,
) -> Dict[str, Any]:
    if validity is not None and validity_metadata is not None:
        raise KnowledgeGovernanceError(
            "validity 和 validity_metadata 只能指定一个"
        )
    provided = validity if validity is not None else validity_metadata
    raw = dict(provided or {})
    explicit = {
        "source_version": source_version,
        "tool_version": tool_version,
        "schema_version": schema_version,
        "reviewed_by": reviewed_by,
    }
    if reviewed_at is not None:
        explicit["reviewed_at"] = reviewed_at
    if expires_at is not None:
        explicit["expires_at"] = expires_at
    if revalidate_after is not None:
        explicit["revalidate_after"] = revalidate_after
    if conditions is not None:
        explicit["conditions"] = conditions
    # Direct arguments are defaults for compatibility, but a supplied mapping
    # wins unless the caller explicitly supplied a non-default direct value.
    for key, value in explicit.items():
        if key not in raw or value not in (None, "", "unknown", {}):
            raw[key] = value
    if reviewed_at is None:
        raw.setdefault("reviewed_at", _now_iso())
    return _normalise_validity(raw, require_reviewed_at=require_reviewed_at)


def _evaluate_validity(
    candidate: "KnowledgeCandidate", *, now: Optional[Union[str, datetime]] = None
) -> Dict[str, Any]:
    current = datetime.now(timezone.utc) if now is None else now
    if isinstance(current, str):
        current_dt = _datetime_value(current, field_name="now")
    elif isinstance(current, datetime):
        current_dt = current if current.tzinfo else current.replace(tzinfo=timezone.utc)
        current_dt = current_dt.astimezone(timezone.utc)
    else:
        raise KnowledgeGovernanceError("now 必须是 ISO-8601 时间或 datetime")
    validity = _normalise_validity(
        candidate.validity,
        promoted_at=candidate.promoted_at,
        created_at=candidate.created_at,
        require_reviewed_at=False,
    )
    state = "current"
    reason = "reviewed"
    if candidate.status == "superseded" or candidate.superseded_by:
        state = "superseded"
        reason = "superseded_by_new_version"
    elif candidate.status != "promoted":
        state = "not_promoted"
        reason = "candidate_not_promoted"
    elif not validity.get("reviewed_at"):
        state = "not_reviewed"
        reason = "missing_review_timestamp"
    elif validity.get("expires_at") and current_dt >= _datetime_value(
        validity["expires_at"], field_name="validity.expires_at"
    ):
        state = "expired"
        reason = "expires_at_reached"
    elif validity.get("revalidate_after") and current_dt >= _datetime_value(
        validity["revalidate_after"], field_name="validity.revalidate_after"
    ):
        state = "stale"
        reason = "revalidate_after_reached"
    return {
        "candidate_id": candidate.id,
        "state": state,
        "usable": state == "current",
        "reason": reason,
        "now": current_dt.astimezone(timezone.utc).isoformat(timespec="seconds"),
        "validity": dict(validity),
        "supersedes": candidate.supersedes,
        "superseded_by": candidate.superseded_by,
        "version": candidate.version,
        "conditions_unverified": bool(validity.get("conditions")),
    }


def _unique_strings(values: Sequence[str], *, field_name: str) -> List[str]:
    result: List[str] = []
    seen = set()
    for value in values:
        item = str(value).strip()
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    if not result:
        raise KnowledgeGovernanceError(f"{field_name} 不能为空")
    return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    )
    temporary = Path(handle.name)
    try:
        with handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


@dataclass(frozen=True)
class GovernancePolicy:
    """Promotion requirements shared by every domain adapter."""

    min_independent_cases: int = 2
    require_distinct_reviewer: bool = True
    allow_contradictions: bool = False

    def __post_init__(self) -> None:
        if self.min_independent_cases < 2:
            raise KnowledgeGovernanceError("min_independent_cases 不能小于 2")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "min_independent_cases": self.min_independent_cases,
            "require_distinct_reviewer": self.require_distinct_reviewer,
            "allow_contradictions": self.allow_contradictions,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "GovernancePolicy":
        return cls(
            min_independent_cases=int(raw.get("min_independent_cases") or 2),
            require_distinct_reviewer=bool(
                raw.get("require_distinct_reviewer", True)
            ),
            allow_contradictions=bool(raw.get("allow_contradictions", False)),
        )


@dataclass(frozen=True)
class KnowledgeVerification:
    case_id: str
    outcome: str
    evidence_refs: List[str]
    verified_by: str
    verified_at: str
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "case_id": self.case_id,
            "outcome": self.outcome,
            "evidence_refs": list(self.evidence_refs),
            "verified_by": self.verified_by,
            "verified_at": self.verified_at,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "KnowledgeVerification":
        return cls(
            case_id=str(raw.get("case_id") or ""),
            outcome=str(raw.get("outcome") or ""),
            evidence_refs=[str(item) for item in raw.get("evidence_refs") or []],
            verified_by=str(raw.get("verified_by") or ""),
            verified_at=str(raw.get("verified_at") or ""),
            note=str(raw.get("note") or ""),
        )


@dataclass(frozen=True)
class KnowledgeValidity:
    """Version and review metadata for promoted knowledge.

    The values are intentionally generic strings/JSON conditions.  Domain
    packages decide how to interpret them; Core only validates their shape,
    size, and timestamps.
    """

    source_version: str = "unknown"
    tool_version: str = "unknown"
    schema_version: str = "unknown"
    reviewed_at: str = ""
    reviewed_by: str = ""
    expires_at: str = ""
    revalidate_after: str = ""
    conditions: Any = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return _normalise_validity(
            {
                "source_version": self.source_version,
                "tool_version": self.tool_version,
                "schema_version": self.schema_version,
                "reviewed_at": self.reviewed_at,
                "reviewed_by": self.reviewed_by,
                "expires_at": self.expires_at,
                "revalidate_after": self.revalidate_after,
                "conditions": self.conditions,
            },
            require_reviewed_at=False,
        )

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "KnowledgeValidity":
        value = _normalise_validity(raw, require_reviewed_at=False)
        return cls(**value)


@dataclass
class KnowledgeCandidate:
    id: str
    kind: str
    payload: Dict[str, Any]
    domain: str
    scope: str
    created_by: str
    created_at: str
    status: str = "candidate"
    verifications: List[KnowledgeVerification] = field(default_factory=list)
    promoted_at: str = ""
    approved_by: str = ""
    promotion_result: Dict[str, Any] = field(default_factory=dict)
    validity: Dict[str, Any] = field(default_factory=dict)
    version: int = 1
    supersedes: str = ""
    superseded_by: str = ""
    revalidation_history: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def support_count(self) -> int:
        return sum(item.outcome == "support" for item in self.verifications)

    @property
    def contradiction_count(self) -> int:
        return sum(item.outcome == "contradict" for item in self.verifications)

    @property
    def evidence_refs(self) -> List[str]:
        refs: List[str] = []
        seen = set()
        for verification in self.verifications:
            for ref in verification.evidence_refs:
                if ref not in seen:
                    seen.add(ref)
                    refs.append(ref)
        return refs

    @property
    def validity_metadata(self) -> Dict[str, Any]:
        return dict(self.validity)

    @property
    def lineage(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "supersedes": self.supersedes,
            "superseded_by": self.superseded_by,
        }

    def recompute_status(self, policy: GovernancePolicy) -> None:
        if self.status in {"promoted", "superseded"}:
            return
        if self.contradiction_count and not policy.allow_contradictions:
            self.status = "contradicted"
        elif self.support_count >= policy.min_independent_cases:
            self.status = "verified"
        else:
            self.status = "candidate"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "payload": dict(self.payload),
            "domain": self.domain,
            "scope": self.scope,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "status": self.status,
            "support_count": self.support_count,
            "contradiction_count": self.contradiction_count,
            "evidence_refs": self.evidence_refs,
            "verifications": [item.to_dict() for item in self.verifications],
            "promoted_at": self.promoted_at,
            "approved_by": self.approved_by,
            "promotion_result": _bounded_promotion_result(self.promotion_result),
            "validity": dict(self.validity),
            "version": self.version,
            "supersedes": self.supersedes,
            "superseded_by": self.superseded_by,
            "lineage": self.lineage,
            "revalidation_history": [dict(item) for item in self.revalidation_history],
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "KnowledgeCandidate":
        if not isinstance(raw, Mapping):
            raise KnowledgeGovernanceError("candidate 必须是对象")
        status = str(raw.get("status") or "candidate")
        if status not in CANDIDATE_STATUSES:
            raise KnowledgeGovernanceError(f"未知候选状态: {status!r}")
        lineage_raw = raw.get("lineage")
        if lineage_raw is not None and not isinstance(lineage_raw, Mapping):
            raise KnowledgeGovernanceError("candidate.lineage 必须是对象")
        lineage = dict(lineage_raw or {})
        try:
            version = max(1, int(raw.get("version") or lineage.get("version") or 1))
        except (TypeError, ValueError) as exc:
            raise KnowledgeGovernanceError("candidate.version 必须是整数") from exc
        history_raw = raw.get("revalidation_history", [])
        if not isinstance(history_raw, list):
            raise KnowledgeGovernanceError("revalidation_history 必须是数组")
        if len(history_raw) > MAX_REVALIDATION_HISTORY:
            raise KnowledgeGovernanceError(
                f"revalidation_history 超过 {MAX_REVALIDATION_HISTORY} 条"
            )
        if any(not isinstance(item, Mapping) for item in history_raw):
            raise KnowledgeGovernanceError(
                "revalidation_history 的每一项必须是对象"
            )
        return cls(
            id=str(raw.get("id") or ""),
            kind=str(raw.get("kind") or ""),
            payload=dict(raw.get("payload") or {}),
            domain=str(raw.get("domain") or ""),
            scope=str(raw.get("scope") or "global"),
            created_by=str(raw.get("created_by") or ""),
            created_at=str(raw.get("created_at") or ""),
            status=status,
            verifications=[
                KnowledgeVerification.from_dict(item)
                for item in raw.get("verifications") or []
                if isinstance(item, Mapping)
            ],
            promoted_at=str(raw.get("promoted_at") or ""),
            approved_by=str(raw.get("approved_by") or ""),
            promotion_result=_bounded_promotion_result(
                raw.get("promotion_result") if raw.get("promotion_result") is not None else {}
            ),
            validity=_normalise_validity(
                raw.get("validity") if isinstance(raw.get("validity"), Mapping) else None,
                promoted_at=str(raw.get("promoted_at") or ""),
                created_at=str(raw.get("created_at") or ""),
                require_reviewed_at=False,
            ),
            version=version,
            supersedes=str(raw.get("supersedes") or lineage.get("supersedes") or ""),
            superseded_by=str(raw.get("superseded_by") or lineage.get("superseded_by") or ""),
            revalidation_history=[
                _bounded_payload(item, field_name="revalidation_history")
                for item in history_raw
            ],
        )


Promoter = Callable[[KnowledgeCandidate], Mapping[str, Any]]


class KnowledgeGovernanceStore:
    """JSON-backed candidate store kept separate from curated knowledge."""

    def __init__(
        self,
        path: Path,
        *,
        policy: Optional[GovernancePolicy] = None,
    ) -> None:
        self.path = Path(path)
        self.default_policy = policy or GovernancePolicy()

    def _empty(self) -> Dict[str, Any]:
        return {
            "schema_version": GOVERNANCE_SCHEMA_VERSION,
            "revision": 0,
            "policy": self.default_policy.to_dict(),
            "candidates": [],
            "managed_targets": {},
        }

    @staticmethod
    def _migrate_candidate(raw: Mapping[str, Any]) -> Dict[str, Any]:
        candidate = dict(raw)
        candidate.setdefault("version", 1)
        candidate.setdefault("supersedes", "")
        candidate.setdefault("superseded_by", "")
        candidate.setdefault("revalidation_history", [])
        candidate.setdefault(
            "validity",
            _default_validity(
                promoted_at=str(candidate.get("promoted_at") or ""),
                created_at=str(candidate.get("created_at") or ""),
            ),
        )
        return candidate

    @classmethod
    def _migrate_raw(cls, raw: Mapping[str, Any]) -> Dict[str, Any]:
        migrated = dict(raw)
        version = int(migrated.get("schema_version") or 0)
        if version == LEGACY_GOVERNANCE_SCHEMA_VERSION:
            migrated["schema_version"] = GOVERNANCE_SCHEMA_VERSION
            migrated["candidates"] = [
                cls._migrate_candidate(item)
                for item in migrated.get("candidates") or []
                if isinstance(item, Mapping)
            ]
        migrated.setdefault("revision", 0)
        migrated.setdefault("policy", GovernancePolicy().to_dict())
        migrated.setdefault("candidates", [])
        migrated.setdefault("managed_targets", {})
        return migrated

    def _load(self) -> Dict[str, Any]:
        if not self.path.is_file():
            return self._empty()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise KnowledgeGovernanceError(
                f"候选知识库不是合法 JSON: {self.path}: {exc}"
            ) from exc
        if not isinstance(raw, dict):
            raise KnowledgeGovernanceError("候选知识库顶层必须是对象")
        version = int(raw.get("schema_version") or 0)
        if version not in {LEGACY_GOVERNANCE_SCHEMA_VERSION, GOVERNANCE_SCHEMA_VERSION}:
            raise KnowledgeGovernanceError(
                f"不支持 governance schema {version}"
            )
        migrated = self._migrate_raw(raw)
        if "policy" not in raw:
            migrated["policy"] = self.default_policy.to_dict()
        self._validate_raw(migrated)
        return migrated

    def _save(self, raw: Dict[str, Any]) -> None:
        raw["revision"] = int(raw.get("revision") or 0) + 1
        _atomic_write_json(self.path, raw)

    def migrate(self) -> Dict[str, Any]:
        """Persist a legacy v1 store as the current schema under its lock."""

        with state_lock(self.path):
            raw = self._load()
            self._validate_raw(raw)
            self._save(raw)
            return dict(raw)

    @staticmethod
    def _validate_raw(raw: Mapping[str, Any]) -> None:
        try:
            version = int(raw.get("schema_version") or 0)
        except (TypeError, ValueError) as exc:
            raise KnowledgeGovernanceError("governance schema_version 必须是整数") from exc
        if version != GOVERNANCE_SCHEMA_VERSION:
            raise KnowledgeGovernanceError(f"不支持 governance schema {version}")
        if not isinstance(raw.get("candidates"), list):
            raise KnowledgeGovernanceError("candidates 必须是数组")
        if not isinstance(raw.get("managed_targets"), Mapping):
            raise KnowledgeGovernanceError("managed_targets 必须是对象")
        if not isinstance(raw.get("policy"), Mapping):
            raise KnowledgeGovernanceError("policy 必须是对象")
        for item in raw.get("candidates") or []:
            if not isinstance(item, Mapping):
                raise KnowledgeGovernanceError("candidate 必须是对象")
            candidate = KnowledgeCandidate.from_dict(item)
            if candidate.status not in CANDIDATE_STATUSES:
                raise KnowledgeGovernanceError(
                    f"未知候选状态: {candidate.status!r}"
                )

    @staticmethod
    def _policy(raw: Mapping[str, Any]) -> GovernancePolicy:
        return GovernancePolicy.from_dict(raw.get("policy") or {})

    @staticmethod
    def _candidate(raw: Mapping[str, Any], candidate_id: str) -> KnowledgeCandidate:
        for item in raw.get("candidates") or []:
            if isinstance(item, Mapping) and str(item.get("id")) == candidate_id:
                return KnowledgeCandidate.from_dict(item)
        raise KnowledgeGovernanceError(f"未知候选知识: {candidate_id}")

    @staticmethod
    def _replace_candidate(raw: Dict[str, Any], candidate: KnowledgeCandidate) -> None:
        items = list(raw.get("candidates") or [])
        for index, item in enumerate(items):
            if isinstance(item, Mapping) and str(item.get("id")) == candidate.id:
                items[index] = candidate.to_dict()
                raw["candidates"] = items
                return
        items.append(candidate.to_dict())
        raw["candidates"] = items

    def propose(
        self,
        *,
        kind: str,
        payload: Mapping[str, Any],
        domain: str,
        scope: str,
        created_by: str,
        case_id: str,
        evidence_refs: Sequence[str],
        supersedes: str = "",
    ) -> KnowledgeCandidate:
        resolved_kind = str(kind).strip()
        resolved_creator = str(created_by).strip()
        resolved_case = str(case_id).strip()
        if not resolved_kind:
            raise KnowledgeGovernanceError("kind 不能为空")
        if not resolved_creator:
            raise KnowledgeGovernanceError("created_by 不能为空")
        if not resolved_case:
            raise KnowledgeGovernanceError("case_id 不能为空")
        if not isinstance(payload, Mapping):
            raise KnowledgeGovernanceError("payload 必须是对象")
        try:
            json.dumps(dict(payload), ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            raise KnowledgeGovernanceError("payload 必须可以序列化为 JSON") from exc
        checked_payload = dict(payload)
        now = _now_iso()
        resolved_supersedes = str(supersedes or "").strip()
        references = _unique_strings(evidence_refs, field_name="evidence_refs")
        with state_lock(self.path):
            raw = self._load()
            old: Optional[KnowledgeCandidate] = None
            if resolved_supersedes:
                old = self._candidate(raw, resolved_supersedes)
                for item in raw.get("candidates") or []:
                    if (
                        isinstance(item, Mapping)
                        and str(item.get("supersedes") or "") == old.id
                    ):
                        # A retry (including a concurrent retry) reuses the
                        # already-created replacement.  A promoted old
                        # candidate remains current until that replacement is
                        # itself promoted.
                        return KnowledgeCandidate.from_dict(item)
                if old.superseded_by:
                    # Repeating a supersession request is idempotent.  A
                    # missing replacement is treated as store corruption.
                    return self._candidate(raw, old.superseded_by)
                if old.status == "superseded":
                    raise KnowledgeGovernanceError("候选已经标记为 superseded，但缺少替代版本")
            candidate = KnowledgeCandidate(
                id=f"kc-{uuid.uuid4().hex[:16]}",
                kind=resolved_kind,
                payload=checked_payload,
                domain=str(domain).strip() or "generic",
                scope=str(scope).strip() or "global",
                created_by=resolved_creator,
                created_at=now,
                validity=_default_validity(created_at=now),
                version=(old.version + 1) if old is not None else 1,
                supersedes=resolved_supersedes,
                verifications=[
                    KnowledgeVerification(
                        case_id=resolved_case,
                        outcome="support",
                        evidence_refs=references,
                        verified_by=resolved_creator,
                        verified_at=now,
                        note="proposal evidence",
                    )
                ],
            )
            candidate.recompute_status(self._policy(raw))
            if old is not None and old.status != "promoted":
                old.status = "superseded"
                old.superseded_by = candidate.id
                self._replace_candidate(raw, old)
            self._replace_candidate(raw, candidate)
            self._save(raw)
            return candidate

    def supersede(
        self,
        candidate_id: str,
        *,
        kind: Optional[str] = None,
        payload: Optional[Mapping[str, Any]] = None,
        domain: Optional[str] = None,
        scope: Optional[str] = None,
        created_by: str,
        case_id: str,
        evidence_refs: Sequence[str],
    ) -> KnowledgeCandidate:
        """Create a new candidate version and mark the old one superseded."""

        old = self.get(candidate_id)
        if old.superseded_by:
            return self.get(old.superseded_by)
        if payload is None:
            raise KnowledgeGovernanceError("superseding candidate 必须提供 payload")
        return self.propose(
            kind=kind if kind is not None else old.kind,
            payload=payload,
            domain=domain if domain is not None else old.domain,
            scope=scope if scope is not None else old.scope,
            created_by=created_by,
            case_id=case_id,
            evidence_refs=evidence_refs,
            supersedes=old.id,
        )

    def verify(
        self,
        candidate_id: str,
        *,
        case_id: str,
        outcome: str,
        evidence_refs: Sequence[str],
        verified_by: str,
        note: str = "",
    ) -> KnowledgeCandidate:
        resolved_outcome = str(outcome).strip().lower()
        if resolved_outcome not in VERIFICATION_OUTCOMES:
            raise KnowledgeGovernanceError(
                f"outcome 必须是: {', '.join(VERIFICATION_OUTCOMES)}"
            )
        resolved_case = str(case_id).strip()
        resolved_actor = str(verified_by).strip()
        if not resolved_case or not resolved_actor:
            raise KnowledgeGovernanceError("case_id 和 verified_by 不能为空")
        references = _unique_strings(evidence_refs, field_name="evidence_refs")
        with state_lock(self.path):
            raw = self._load()
            candidate = self._candidate(raw, candidate_id)
            if candidate.status in {"promoted", "superseded"}:
                raise KnowledgeGovernanceError("已晋升或 superseded 候选不能继续验证")
            if any(item.case_id == resolved_case for item in candidate.verifications):
                raise KnowledgeGovernanceError(
                    f"case_id 已验证，不能重复计数: {resolved_case}"
                )
            candidate.verifications.append(
                KnowledgeVerification(
                    case_id=resolved_case,
                    outcome=resolved_outcome,
                    evidence_refs=references,
                    verified_by=resolved_actor,
                    verified_at=_now_iso(),
                    note=str(note),
                )
            )
            candidate.recompute_status(self._policy(raw))
            self._replace_candidate(raw, candidate)
            self._save(raw)
            return candidate

    def list_candidates(self, *, status: str = "") -> List[KnowledgeCandidate]:
        raw = self._load()
        items = [
            KnowledgeCandidate.from_dict(item)
            for item in raw.get("candidates") or []
            if isinstance(item, Mapping)
        ]
        if status:
            items = [item for item in items if item.status == status]
        return items

    def get(self, candidate_id: str) -> KnowledgeCandidate:
        return self._candidate(self._load(), candidate_id)

    def register_target(self, name: str, path: Path) -> Dict[str, Any]:
        resolved_name = str(name).strip()
        target = Path(path).resolve()
        if not resolved_name:
            raise KnowledgeGovernanceError("target name 不能为空")
        if not target.is_file():
            raise KnowledgeGovernanceError(f"受管知识文件不存在: {target}")
        with state_lock(self.path):
            raw = self._load()
            targets = dict(raw.get("managed_targets") or {})
            existing = targets.get(resolved_name)
            if existing is not None:
                return self._check_target_record(resolved_name, target, raw)
            record = {
                "path": str(target),
                "sha256": _sha256(target),
                "updated_at": _now_iso(),
                "last_promotion_id": "",
            }
            targets[resolved_name] = record
            raw["managed_targets"] = targets
            self._save(raw)
            return {"name": resolved_name, "status": "registered", **record}

    @staticmethod
    def _check_target_record(
        name: str, target: Path, raw: Mapping[str, Any]
    ) -> Dict[str, Any]:
        record = (raw.get("managed_targets") or {}).get(name)
        if not isinstance(record, Mapping):
            return {
                "name": name,
                "path": str(target),
                "status": "unmanaged",
            }
        if str(record.get("path")) != str(target):
            return {
                "name": name,
                "path": str(target),
                "status": "path_mismatch",
                "expected_path": str(record.get("path")),
            }
        if not target.is_file():
            return {
                "name": name,
                "path": str(target),
                "status": "missing",
                "expected_sha256": str(record.get("sha256") or ""),
            }
        actual = _sha256(target)
        expected = str(record.get("sha256") or "")
        return {
            "name": name,
            "path": str(target),
            "status": "ok" if actual == expected else "modified",
            "expected_sha256": expected,
            "actual_sha256": actual,
            "last_promotion_id": str(record.get("last_promotion_id") or ""),
        }

    def check_target(self, name: str, path: Path) -> Dict[str, Any]:
        resolved_name = str(name).strip()
        target = Path(path).resolve()
        raw = self._load()
        return self._check_target_record(resolved_name, target, raw)

    def evaluate_validity(
        self,
        candidate_id: str,
        *,
        now: Optional[Union[str, datetime]] = None,
    ) -> Dict[str, Any]:
        """Return an explicit trust decision for promoted knowledge.

        Callers must inspect ``usable`` before using a promoted candidate.
        Expired and revalidation-due records are never silently treated as
        current; conditions are returned but deliberately not interpreted by
        the generic Core.
        """

        candidate = self.get(candidate_id)
        return _evaluate_validity(candidate, now=now)

    def is_current(
        self,
        candidate_id: str,
        *,
        now: Optional[Union[str, datetime]] = None,
    ) -> bool:
        return bool(self.evaluate_validity(candidate_id, now=now)["usable"])

    def revalidate(
        self,
        candidate_id: str,
        *,
        reviewed_by: str,
        validity: Optional[Mapping[str, Any]] = None,
        validity_metadata: Optional[Mapping[str, Any]] = None,
        source_version: Any = None,
        tool_version: Any = None,
        schema_version: Any = None,
        reviewed_at: Any = None,
        expires_at: Any = None,
        revalidate_after: Any = None,
        conditions: Any = None,
    ) -> KnowledgeCandidate:
        """Explicitly refresh validity metadata for an approved candidate.

        Revalidation changes review metadata only.  Any semantic change must
        create a new version through :meth:`supersede`, preserving lineage.
        """

        reviewer = str(reviewed_by).strip()
        if not reviewer:
            raise KnowledgeGovernanceError("reviewed_by 不能为空")
        with state_lock(self.path):
            raw = self._load()
            candidate = self._candidate(raw, candidate_id)
            if candidate.status == "superseded" or candidate.superseded_by:
                raise KnowledgeGovernanceError("superseded 候选不能重新验证")
            if candidate.status != "promoted":
                raise KnowledgeGovernanceError("只有已晋升候选才能重新验证")
            current_validity = _normalise_validity(
                candidate.validity,
                promoted_at=candidate.promoted_at,
                created_at=candidate.created_at,
                require_reviewed_at=True,
            )
            existing_reviewer = str(current_validity.get("reviewed_by") or "")
            if reviewer == candidate.created_by or reviewer == candidate.approved_by:
                # A byte-for-byte repeat from the same reviewer is safe and
                # idempotent; a new review must be independent.
                requested = dict(current_validity)
                if validity is not None or validity_metadata is not None:
                    requested.update(dict(validity or validity_metadata or {}))
                if reviewed_at is not None:
                    requested["reviewed_at"] = reviewed_at
                if (
                    reviewer == existing_reviewer
                    and _normalise_validity(requested, require_reviewed_at=True)
                    == current_validity
                ):
                    return candidate
                raise KnowledgeGovernanceError("创建者或原审核人不能独立重新验证")
            if reviewer == existing_reviewer:
                raise KnowledgeGovernanceError("原审核人不能独立重新验证")
            if validity is not None and validity_metadata is not None:
                raise KnowledgeGovernanceError(
                    "validity 和 validity_metadata 只能指定一个"
                )
            provided = dict(validity or validity_metadata or {})
            provided.setdefault("source_version", current_validity["source_version"])
            provided.setdefault("tool_version", current_validity["tool_version"])
            provided.setdefault("schema_version", current_validity["schema_version"])
            # A successful explicit review clears old scheduling deadlines
            # unless the reviewer declares new ones.  Otherwise a record would
            # remain stale/expired immediately after revalidation.
            provided.setdefault("expires_at", "")
            provided.setdefault("revalidate_after", "")
            provided.setdefault("conditions", current_validity.get("conditions") or {})
            provided["reviewed_by"] = reviewer
            if reviewed_at is not None:
                provided["reviewed_at"] = reviewed_at
            else:
                provided["reviewed_at"] = _now_iso()
            if expires_at is not None:
                provided["expires_at"] = expires_at
            if revalidate_after is not None:
                provided["revalidate_after"] = revalidate_after
            if conditions is not None:
                provided["conditions"] = conditions
            if source_version is not None:
                provided["source_version"] = source_version
            if tool_version is not None:
                provided["tool_version"] = tool_version
            if schema_version is not None:
                provided["schema_version"] = schema_version
            next_validity = _normalise_validity(provided, require_reviewed_at=True)
            history = list(candidate.revalidation_history)
            history.append(
                {
                    "reviewed_at": next_validity["reviewed_at"],
                    "reviewed_by": reviewer,
                    "validity": dict(next_validity),
                }
            )
            candidate.revalidation_history = history[-MAX_REVALIDATION_HISTORY:]
            candidate.validity = next_validity
            self._replace_candidate(raw, candidate)
            self._save(raw)
            return candidate

    def promote(
        self,
        candidate_id: str,
        *,
        approved_by: str,
        promoter: Promoter,
        target_name: str,
        target_path: Path,
        validity: Optional[Mapping[str, Any]] = None,
        validity_metadata: Optional[Mapping[str, Any]] = None,
        source_version: Any = "unknown",
        tool_version: Any = "unknown",
        schema_version: Any = "unknown",
        reviewed_at: Any = None,
        reviewed_by: Optional[str] = None,
        expires_at: Any = None,
        revalidate_after: Any = None,
        conditions: Any = None,
    ) -> KnowledgeCandidate:
        reviewer = str(approved_by).strip()
        if not reviewer:
            raise KnowledgeGovernanceError("approved_by 不能为空")
        resolved_target_name = str(target_name).strip()
        target = Path(target_path).resolve()
        if not resolved_target_name:
            raise KnowledgeGovernanceError("target_name 不能为空")
        if not target.is_file():
            raise KnowledgeGovernanceError(f"受管知识文件不存在: {target}")
        with state_lock(self.path):
            raw = self._load()
            policy = self._policy(raw)
            candidate = self._candidate(raw, candidate_id)
            if candidate.status == "promoted":
                target_record = self._check_target_record(
                    resolved_target_name, target, raw
                )
                if target_record["status"] != "ok":
                    raise KnowledgeGovernanceError(
                        f"正式知识完整性检查失败: {target_record['status']}"
                    )
                return candidate
            candidate.recompute_status(policy)
            if candidate.status != "verified":
                raise KnowledgeGovernanceError(
                    f"候选状态为 {candidate.status!r}，不能晋升"
                )
            if policy.require_distinct_reviewer and reviewer == candidate.created_by:
                raise KnowledgeGovernanceError("创建者不能批准自己创建的候选")
            if not candidate.evidence_refs:
                raise KnowledgeGovernanceError("候选没有证据引用，不能晋升")
            resolved_validity = _validity_from_args(
                validity=validity,
                validity_metadata=validity_metadata,
                source_version=source_version,
                tool_version=tool_version,
                schema_version=schema_version,
                reviewed_at=reviewed_at,
                reviewed_by=reviewed_by if reviewed_by is not None else reviewer,
                expires_at=expires_at,
                revalidate_after=revalidate_after,
                conditions=conditions,
                require_reviewed_at=True,
            )
            candidate.validity = resolved_validity

            target_record = self._check_target_record(
                resolved_target_name, target, raw
            )
            if target_record["status"] == "unmanaged":
                targets = dict(raw.get("managed_targets") or {})
                targets[resolved_target_name] = {
                    "path": str(target),
                    "sha256": _sha256(target),
                    "updated_at": _now_iso(),
                    "last_promotion_id": "",
                }
                raw["managed_targets"] = targets
                target_record = self._check_target_record(
                    resolved_target_name, target, raw
                )
            if target_record["status"] != "ok":
                raise KnowledgeGovernanceError(
                    f"正式知识完整性检查失败: {target_record['status']}"
                )

            try:
                result = _bounded_promotion_result(promoter(candidate))
            except KnowledgeGovernanceError:
                raise
            except Exception as exc:
                raise KnowledgeGovernanceError(f"领域晋升适配器执行失败: {exc}") from exc

            if not target.is_file():
                raise KnowledgeGovernanceError("晋升后正式知识文件不存在")
            candidate.status = "promoted"
            candidate.approved_by = reviewer
            candidate.promoted_at = _now_iso()
            candidate.validity = _normalise_validity(
                resolved_validity,
                promoted_at=candidate.promoted_at,
                created_at=candidate.created_at,
                require_reviewed_at=True,
            )
            candidate.promotion_result = result
            self._replace_candidate(raw, candidate)
            if candidate.supersedes:
                old = self._candidate(raw, candidate.supersedes)
                old.status = "superseded"
                old.superseded_by = candidate.id
                self._replace_candidate(raw, old)
            targets = dict(raw.get("managed_targets") or {})
            targets[resolved_target_name] = {
                "path": str(target),
                "sha256": _sha256(target),
                "updated_at": _now_iso(),
                "last_promotion_id": candidate.id,
            }
            raw["managed_targets"] = targets
            self._save(raw)
            return candidate


__all__ = [
    "CANDIDATE_STATUSES",
    "GOVERNANCE_SCHEMA_VERSION",
    "VALIDITY_STATES",
    "VERIFICATION_OUTCOMES",
    "GovernancePolicy",
    "KnowledgeCandidate",
    "KnowledgeGovernanceError",
    "KnowledgeGovernanceStore",
    "KnowledgeValidity",
    "KnowledgeVerification",
]
