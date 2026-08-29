"""Compatibility search-delta projection over Runtime RetrievalSession state.

This module no longer owns persisted seen-state. ``ContextState`` and
``ContextStateStore`` remain compatibility aliases to the Runtime-owned
``RetrievalSessionState`` / ``RetrievalSessionStore`` contract.
"""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any, Mapping

from tracecite.runtime.retrieval_session import (
    DEFAULT_MAX_SEEN_EVIDENCE,
    DEFAULT_MAX_SEEN_RESULTS,
    RETRIEVAL_SESSION_SCHEMA_VERSION,
    RetrievalSessionState,
    RetrievalSessionStore,
)


CONTEXT_SCHEMA_VERSION = RETRIEVAL_SESSION_SCHEMA_VERSION
ContextState = RetrievalSessionState
ContextStateStore = RetrievalSessionStore


def project_search_delta(
    payload: Mapping[str, Any],
    state: RetrievalSessionState,
    *,
    result_id: str | None = None,
    max_seen_evidence: int = DEFAULT_MAX_SEEN_EVIDENCE,
    max_seen_results: int = DEFAULT_MAX_SEEN_RESULTS,
) -> tuple[dict[str, Any], RetrievalSessionState]:
    """Project unseen search Evidence while advancing canonical session state."""

    if payload.get("operation") != "search":
        raise ValueError("Context Engine currently projects canonical search Results")
    if not isinstance(state, RetrievalSessionState):
        raise TypeError("project_search_delta requires RetrievalSessionState")
    if result_id is not None:
        result_id = str(result_id)
        if not re.fullmatch(r"[0-9a-f]{64}", result_id):
            raise ValueError("result_id must be a 64-character lowercase SHA-256 digest")

    result = copy.deepcopy(dict(payload))
    original_evidence = [
        dict(item)
        for item in payload.get("evidence") or []
        if isinstance(item, Mapping)
    ]
    seen = set(state.seen_evidence)
    delta_evidence: list[dict[str, Any]] = []
    new_evidence_ids: list[str] = []
    repeated = 0
    unidentified = 0

    for item in original_evidence:
        uri = str(item.get("uri") or "")
        if not uri:
            unidentified += 1
            delta_evidence.append(item)
            continue
        if uri in seen:
            repeated += 1
            continue
        seen.add(uri)
        new_evidence_ids.append(uri)
        delta_evidence.append(item)

    result_repeated = bool(result_id and result_id in set(state.seen_results))
    next_state, state_pruned = state.advance(
        evidence=new_evidence_ids,
        results=(result_id,) if result_id else (),
        max_seen_evidence=max_seen_evidence,
        max_seen_results=max_seen_results,
    )

    result["evidence"] = delta_evidence
    data = dict(result.get("data") or {})
    data["context"] = {
        "schema_version": CONTEXT_SCHEMA_VERSION,
        "id": state.context_id,
        "revision": next_state.revision,
        "mode": "delta",
        "state_owner": "RetrievalSession",
        "result_repeated": result_repeated,
        "new_evidence": len(delta_evidence),
        "repeated_evidence": repeated,
        "unidentified_evidence": unidentified,
        "seen_evidence": len(next_state.seen_evidence),
        "state_pruned": state_pruned,
    }
    result["data"] = data

    coverage = dict(result.get("coverage") or {})
    canonical_returned = int(coverage.get("evidence_returned") or len(original_evidence))
    coverage["canonical_evidence_returned"] = canonical_returned
    coverage["evidence_returned"] = len(delta_evidence)
    coverage["context_evidence_new"] = len(delta_evidence)
    coverage["context_evidence_repeated"] = repeated
    coverage["context_state_pruned"] = state_pruned
    result["coverage"] = coverage

    if original_evidence and not delta_evidence:
        warnings = list(result.get("warnings") or [])
        warning = "all citable evidence in this result was already seen in the selected Agent context"
        if warning not in warnings:
            warnings.append(warning)
        result["warnings"] = warnings
    return result, next_state


class ContextEngine:
    """Compatibility facade using the canonical RetrievalSessionStore."""

    def __init__(
        self,
        root: str | Path,
        context_id: str,
        *,
        max_seen_evidence: int = DEFAULT_MAX_SEEN_EVIDENCE,
        max_seen_results: int = DEFAULT_MAX_SEEN_RESULTS,
    ) -> None:
        if max_seen_evidence < 1 or max_seen_results < 1:
            raise ValueError("context seen-state limits must be at least 1")
        self.store = RetrievalSessionStore(root, context_id)
        self.max_seen_evidence = max_seen_evidence
        self.max_seen_results = max_seen_results

    def project_search(
        self,
        payload: Mapping[str, Any],
        *,
        result_id: str | None = None,
    ) -> dict[str, Any]:
        projected, next_state = project_search_delta(
            payload,
            self.store.load(),
            result_id=result_id,
            max_seen_evidence=self.max_seen_evidence,
            max_seen_results=self.max_seen_results,
        )
        self.store.save(next_state)
        return projected

    def state(self) -> RetrievalSessionState:
        return self.store.load()

    def reset(self) -> None:
        self.store.reset()


__all__ = [
    "CONTEXT_SCHEMA_VERSION",
    "DEFAULT_MAX_SEEN_EVIDENCE",
    "DEFAULT_MAX_SEEN_RESULTS",
    "ContextEngine",
    "ContextState",
    "ContextStateStore",
    "project_search_delta",
]
