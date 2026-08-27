"""Generic bounded seen-state for evidence packages and canonical projections."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


CONTEXT_SCHEMA_VERSION = 1
_CONTEXT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _bounded(values: list[str], limit: int) -> tuple[tuple[str, ...], bool]:
    if limit < 1:
        raise ValueError("context limits must be at least 1")
    if len(values) <= limit:
        return tuple(values), False
    return tuple(values[-limit:]), True


def _relation_id(value: Mapping[str, Any]) -> str:
    explicit = str(value.get("id") or "")
    if explicit:
        return explicit
    identity = {
        key: value.get(key)
        for key in ("source_id", "target_id", "kind", "basis")
        if value.get(key) is not None
    }
    if len(identity) < 2:
        return ""
    encoded = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "r-" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]


def _item_id(value: Mapping[str, Any]) -> str:
    return str(value.get("id") or value.get("uri") or "")


@dataclass(frozen=True)
class EvidenceContextState:
    context_id: str
    revision: int = 0
    seen_evidence: tuple[str, ...] = ()
    seen_groups: tuple[str, ...] = ()
    seen_relations: tuple[str, ...] = ()
    schema_version: int = CONTEXT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not _CONTEXT_RE.fullmatch(str(self.context_id)):
            raise ValueError("invalid context_id")
        if self.revision < 0:
            raise ValueError("context revision cannot be negative")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "context_id": self.context_id,
            "revision": self.revision,
            "seen_evidence": list(self.seen_evidence),
            "seen_groups": list(self.seen_groups),
            "seen_relations": list(self.seen_relations),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EvidenceContextState":
        if int(value.get("schema_version") or 0) != CONTEXT_SCHEMA_VERSION:
            raise ValueError("unsupported evidence context schema")
        return cls(
            context_id=str(value.get("context_id") or ""),
            revision=int(value.get("revision") or 0),
            seen_evidence=tuple(str(item) for item in value.get("seen_evidence") or []),
            seen_groups=tuple(str(item) for item in value.get("seen_groups") or []),
            seen_relations=tuple(str(item) for item in value.get("seen_relations") or []),
        )


class EvidenceContextStore:
    def __init__(self, root: str | Path, context_id: str) -> None:
        self.root = Path(root).expanduser().resolve()
        self.context_id = EvidenceContextState(context_id).context_id
        self.path = self.root / "_evidence_contexts" / f"{self.context_id}.json"

    def load(self) -> EvidenceContextState:
        if not self.path.exists():
            return EvidenceContextState(self.context_id)
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(value, Mapping):
            raise ValueError("evidence context file must contain an object")
        state = EvidenceContextState.from_dict(value)
        if state.context_id != self.context_id:
            raise ValueError("evidence context id mismatch")
        return state

    def save(self, state: EvidenceContextState) -> None:
        if state.context_id != self.context_id:
            raise ValueError("cannot save another context id")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(state.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{self.context_id}.", suffix=".tmp", dir=self.path.parent, text=True)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)


def project_evidence_delta(
    payload: Mapping[str, Any],
    state: EvidenceContextState,
    *,
    max_seen_evidence: int = 4096,
    max_seen_groups: int = 2048,
    max_seen_relations: int = 8192,
) -> tuple[dict[str, Any], EvidenceContextState]:
    """Suppress only stable identities; unidentified rows remain visible."""

    result = copy.deepcopy(dict(payload))

    def project(rows: Any, previous: tuple[str, ...], identity, limit: int):
        source_rows = [dict(item) for item in rows or [] if isinstance(item, Mapping)]
        seen = set(previous)
        order = list(previous)
        output: list[dict[str, Any]] = []
        repeated = 0
        unidentified = 0
        for row in source_rows:
            item_id = identity(row)
            if not item_id:
                unidentified += 1
                output.append(row)
                continue
            if item_id in seen:
                repeated += 1
                continue
            seen.add(item_id)
            order.append(item_id)
            output.append(row)
        bounded, pruned = _bounded(order, limit)
        return output, bounded, repeated, unidentified, pruned

    evidence, seen_evidence, repeated_evidence, unidentified_evidence, p1 = project(
        result.get("evidence"), state.seen_evidence, _item_id, max_seen_evidence
    )
    groups, seen_groups, repeated_groups, unidentified_groups, p2 = project(
        result.get("groups"), state.seen_groups, _item_id, max_seen_groups
    )
    relations, seen_relations, repeated_relations, unidentified_relations, p3 = project(
        result.get("relations"), state.seen_relations, _relation_id, max_seen_relations
    )
    result["evidence"] = evidence
    result["groups"] = groups
    result["relations"] = relations
    next_state = EvidenceContextState(
        context_id=state.context_id,
        revision=state.revision + 1,
        seen_evidence=seen_evidence,
        seen_groups=seen_groups,
        seen_relations=seen_relations,
    )
    result["context"] = {
        "schema_version": CONTEXT_SCHEMA_VERSION,
        "id": state.context_id,
        "revision": next_state.revision,
        "mode": "delta",
        "new_evidence": len(evidence),
        "new_groups": len(groups),
        "new_relations": len(relations),
        "repeated_evidence": repeated_evidence,
        "repeated_groups": repeated_groups,
        "repeated_relations": repeated_relations,
        "unidentified_evidence": unidentified_evidence,
        "unidentified_groups": unidentified_groups,
        "unidentified_relations": unidentified_relations,
        "state_pruned": p1 or p2 or p3,
    }
    return result, next_state


class EvidenceContextEngine:
    def __init__(self, root: str | Path, context_id: str, **limits: int) -> None:
        self.store = EvidenceContextStore(root, context_id)
        self.limits = dict(limits)

    def project(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        projected, next_state = project_evidence_delta(payload, self.store.load(), **self.limits)
        self.store.save(next_state)
        return projected


__all__ = [
    "CONTEXT_SCHEMA_VERSION",
    "EvidenceContextEngine",
    "EvidenceContextState",
    "EvidenceContextStore",
    "project_evidence_delta",
]
