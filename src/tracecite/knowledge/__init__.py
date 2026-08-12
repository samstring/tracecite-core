"""Domain-neutral governance for knowledge proposed by agents.

The evidence/runtime layer does not define domain knowledge.  This module only
owns the lifecycle around it: proposals are stored separately, independent
cases verify them, and an explicit reviewer authorizes promotion through a
domain adapter.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence


GOVERNANCE_SCHEMA_VERSION = 1
CANDIDATE_STATUSES = (
    "candidate",
    "verified",
    "contradicted",
    "promoted",
)
VERIFICATION_OUTCOMES = ("support", "contradict")


class KnowledgeGovernanceError(RuntimeError):
    """A proposal, verification, promotion, or integrity check failed."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


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

    def recompute_status(self, policy: GovernancePolicy) -> None:
        if self.status == "promoted":
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
            "promotion_result": dict(self.promotion_result),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "KnowledgeCandidate":
        return cls(
            id=str(raw.get("id") or ""),
            kind=str(raw.get("kind") or ""),
            payload=dict(raw.get("payload") or {}),
            domain=str(raw.get("domain") or ""),
            scope=str(raw.get("scope") or "global"),
            created_by=str(raw.get("created_by") or ""),
            created_at=str(raw.get("created_at") or ""),
            status=str(raw.get("status") or "candidate"),
            verifications=[
                KnowledgeVerification.from_dict(item)
                for item in raw.get("verifications") or []
                if isinstance(item, Mapping)
            ],
            promoted_at=str(raw.get("promoted_at") or ""),
            approved_by=str(raw.get("approved_by") or ""),
            promotion_result=dict(raw.get("promotion_result") or {}),
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
        if version != GOVERNANCE_SCHEMA_VERSION:
            raise KnowledgeGovernanceError(
                f"不支持 governance schema {version}"
            )
        raw.setdefault("revision", 0)
        raw.setdefault("policy", self.default_policy.to_dict())
        raw.setdefault("candidates", [])
        raw.setdefault("managed_targets", {})
        return raw

    def _save(self, raw: Dict[str, Any]) -> None:
        raw["revision"] = int(raw.get("revision") or 0) + 1
        _atomic_write_json(self.path, raw)

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
        try:
            json.dumps(dict(payload), ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            raise KnowledgeGovernanceError("payload 必须可以序列化为 JSON") from exc
        now = _now_iso()
        candidate = KnowledgeCandidate(
            id=f"kc-{uuid.uuid4().hex[:16]}",
            kind=resolved_kind,
            payload=dict(payload),
            domain=str(domain).strip() or "generic",
            scope=str(scope).strip() or "global",
            created_by=resolved_creator,
            created_at=now,
            verifications=[
                KnowledgeVerification(
                    case_id=resolved_case,
                    outcome="support",
                    evidence_refs=_unique_strings(
                        evidence_refs, field_name="evidence_refs"
                    ),
                    verified_by=resolved_creator,
                    verified_at=now,
                    note="proposal evidence",
                )
            ],
        )
        raw = self._load()
        candidate.recompute_status(self._policy(raw))
        self._replace_candidate(raw, candidate)
        self._save(raw)
        return candidate

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
        raw = self._load()
        candidate = self._candidate(raw, candidate_id)
        if candidate.status == "promoted":
            raise KnowledgeGovernanceError("已晋升候选不能继续验证")
        if any(item.case_id == resolved_case for item in candidate.verifications):
            raise KnowledgeGovernanceError(
                f"case_id 已验证，不能重复计数: {resolved_case}"
            )
        candidate.verifications.append(
            KnowledgeVerification(
                case_id=resolved_case,
                outcome=resolved_outcome,
                evidence_refs=_unique_strings(
                    evidence_refs, field_name="evidence_refs"
                ),
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
        raw = self._load()
        targets = dict(raw.get("managed_targets") or {})
        existing = targets.get(resolved_name)
        if existing is not None:
            return self.check_target(resolved_name, target)
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

    def check_target(self, name: str, path: Path) -> Dict[str, Any]:
        resolved_name = str(name).strip()
        target = Path(path).resolve()
        raw = self._load()
        record = (raw.get("managed_targets") or {}).get(resolved_name)
        if not isinstance(record, Mapping):
            return {
                "name": resolved_name,
                "path": str(target),
                "status": "unmanaged",
            }
        if str(record.get("path")) != str(target):
            return {
                "name": resolved_name,
                "path": str(target),
                "status": "path_mismatch",
                "expected_path": str(record.get("path")),
            }
        if not target.is_file():
            return {
                "name": resolved_name,
                "path": str(target),
                "status": "missing",
                "expected_sha256": str(record.get("sha256") or ""),
            }
        actual = _sha256(target)
        expected = str(record.get("sha256") or "")
        return {
            "name": resolved_name,
            "path": str(target),
            "status": "ok" if actual == expected else "modified",
            "expected_sha256": expected,
            "actual_sha256": actual,
            "last_promotion_id": str(record.get("last_promotion_id") or ""),
        }

    def promote(
        self,
        candidate_id: str,
        *,
        approved_by: str,
        promoter: Promoter,
        target_name: str,
        target_path: Path,
    ) -> KnowledgeCandidate:
        reviewer = str(approved_by).strip()
        if not reviewer:
            raise KnowledgeGovernanceError("approved_by 不能为空")
        raw = self._load()
        policy = self._policy(raw)
        candidate = self._candidate(raw, candidate_id)
        candidate.recompute_status(policy)
        if candidate.status != "verified":
            raise KnowledgeGovernanceError(
                f"候选状态为 {candidate.status!r}，不能晋升"
            )
        if policy.require_distinct_reviewer and reviewer == candidate.created_by:
            raise KnowledgeGovernanceError("创建者不能批准自己创建的候选")
        if not candidate.evidence_refs:
            raise KnowledgeGovernanceError("候选没有证据引用，不能晋升")

        target = self.check_target(target_name, target_path)
        if target["status"] == "unmanaged":
            self.register_target(target_name, target_path)
            target = self.check_target(target_name, target_path)
        if target["status"] != "ok":
            raise KnowledgeGovernanceError(
                f"正式知识完整性检查失败: {target['status']}"
            )

        try:
            result = dict(promoter(candidate))
            json.dumps(result, ensure_ascii=False)
        except KnowledgeGovernanceError:
            raise
        except Exception as exc:
            raise KnowledgeGovernanceError(f"领域晋升适配器执行失败: {exc}") from exc

        if not Path(target_path).is_file():
            raise KnowledgeGovernanceError("晋升后正式知识文件不存在")
        raw = self._load()
        candidate = self._candidate(raw, candidate_id)
        candidate.status = "promoted"
        candidate.approved_by = reviewer
        candidate.promoted_at = _now_iso()
        candidate.promotion_result = result
        self._replace_candidate(raw, candidate)
        targets = dict(raw.get("managed_targets") or {})
        targets[target_name] = {
            "path": str(Path(target_path).resolve()),
            "sha256": _sha256(Path(target_path)),
            "updated_at": _now_iso(),
            "last_promotion_id": candidate.id,
        }
        raw["managed_targets"] = targets
        self._save(raw)
        return candidate


__all__ = [
    "CANDIDATE_STATUSES",
    "GOVERNANCE_SCHEMA_VERSION",
    "VERIFICATION_OUTCOMES",
    "GovernancePolicy",
    "KnowledgeCandidate",
    "KnowledgeGovernanceError",
    "KnowledgeGovernanceStore",
    "KnowledgeVerification",
]
