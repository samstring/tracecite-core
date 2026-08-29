"""Compatibility package-delta projection over Runtime RetrievalSession state.

Evidence/groups/relations projection remains transport shaping. Persisted seen
identity ownership lives exclusively in ``tracecite.runtime.retrieval_session``.
Legacy public names are retained as aliases during migration.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from tracecite.runtime.retrieval_session import (
    DEFAULT_MAX_SEEN_EVIDENCE,
    DEFAULT_MAX_SEEN_GROUPS,
    DEFAULT_MAX_SEEN_RELATIONS,
    RETRIEVAL_SESSION_SCHEMA_VERSION,
    RetrievalSessionState,
    RetrievalSessionStore,
)


CONTEXT_SCHEMA_VERSION = RETRIEVAL_SESSION_SCHEMA_VERSION
EvidenceContextState = RetrievalSessionState
EvidenceContextStore = RetrievalSessionStore


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


def _project_rows(
    rows: Any,
    previous: tuple[str, ...],
    identity,
) -> tuple[list[dict[str, Any]], list[str], int, int]:
    source_rows = [dict(item) for item in rows or [] if isinstance(item, Mapping)]
    seen = set(previous)
    output: list[dict[str, Any]] = []
    new_ids: list[str] = []
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
        new_ids.append(item_id)
        output.append(row)
    return output, new_ids, repeated, unidentified


def project_evidence_delta(
    payload: Mapping[str, Any],
    state: RetrievalSessionState,
    *,
    max_seen_evidence: int = DEFAULT_MAX_SEEN_EVIDENCE,
    max_seen_groups: int = DEFAULT_MAX_SEEN_GROUPS,
    max_seen_relations: int = DEFAULT_MAX_SEEN_RELATIONS,
) -> tuple[dict[str, Any], RetrievalSessionState]:
    """Suppress stable package identities using one canonical session owner."""

    if not isinstance(state, RetrievalSessionState):
        raise TypeError("project_evidence_delta requires RetrievalSessionState")
    result = copy.deepcopy(dict(payload))

    evidence, new_evidence_ids, repeated_evidence, unidentified_evidence = _project_rows(
        result.get("evidence"), state.seen_evidence, _item_id
    )
    groups, new_group_ids, repeated_groups, unidentified_groups = _project_rows(
        result.get("groups"), state.seen_groups, _item_id
    )
    relations, new_relation_ids, repeated_relations, unidentified_relations = _project_rows(
        result.get("relations"), state.seen_relations, _relation_id
    )

    next_state, state_pruned = state.advance(
        evidence=new_evidence_ids,
        groups=new_group_ids,
        relations=new_relation_ids,
        max_seen_evidence=max_seen_evidence,
        max_seen_groups=max_seen_groups,
        max_seen_relations=max_seen_relations,
    )

    result["evidence"] = evidence
    result["groups"] = groups
    result["relations"] = relations
    result["context"] = {
        "schema_version": CONTEXT_SCHEMA_VERSION,
        "id": state.context_id,
        "revision": next_state.revision,
        "mode": "delta",
        "state_owner": "RetrievalSession",
        "new_evidence": len(evidence),
        "new_groups": len(groups),
        "new_relations": len(relations),
        "repeated_evidence": repeated_evidence,
        "repeated_groups": repeated_groups,
        "repeated_relations": repeated_relations,
        "unidentified_evidence": unidentified_evidence,
        "unidentified_groups": unidentified_groups,
        "unidentified_relations": unidentified_relations,
        "state_pruned": state_pruned,
    }
    return result, next_state


class EvidenceContextEngine:
    """Compatibility facade sharing the canonical RetrievalSessionStore."""

    def __init__(self, root: str | Path, context_id: str, **limits: int) -> None:
        allowed = {"max_seen_evidence", "max_seen_groups", "max_seen_relations"}
        unknown = set(limits) - allowed
        if unknown:
            raise TypeError(f"unsupported EvidenceContextEngine limits: {sorted(unknown)!r}")
        if any(value < 1 for value in limits.values()):
            raise ValueError("context limits must be at least 1")
        self.store = RetrievalSessionStore(root, context_id)
        self.limits = dict(limits)

    def project(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        projected, next_state = project_evidence_delta(
            payload,
            self.store.load(),
            **self.limits,
        )
        self.store.save(next_state)
        return projected

    def state(self) -> RetrievalSessionState:
        return self.store.load()

    def reset(self) -> None:
        self.store.reset()


__all__ = [
    "CONTEXT_SCHEMA_VERSION",
    "EvidenceContextEngine",
    "EvidenceContextState",
    "EvidenceContextStore",
    "project_evidence_delta",
]
