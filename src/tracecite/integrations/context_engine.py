"""Persistent seen-state and delta projection for stateful Agent hosts.

The Context Engine never mutates canonical Runtime Results or Evidence Ledger
entries. It stores only bounded transport memory (which evidence/result
identities an Agent has already seen) and derives a smaller per-turn view.
"""

from __future__ import annotations

import copy
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


CONTEXT_SCHEMA_VERSION = 1
DEFAULT_MAX_SEEN_EVIDENCE = 4096
DEFAULT_MAX_SEEN_RESULTS = 512
_CONTEXT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _validate_context_id(value: str) -> str:
    context_id = str(value).strip()
    if not _CONTEXT_ID_RE.fullmatch(context_id):
        raise ValueError(
            "context_id must be 1-128 characters using letters, digits, '.', '_' or '-'"
        )
    return context_id


def _bounded_tail(values: list[str], limit: int) -> tuple[tuple[str, ...], bool]:
    if limit < 1:
        raise ValueError("context seen-state limits must be at least 1")
    if len(values) <= limit:
        return tuple(values), False
    return tuple(values[-limit:]), True


@dataclass(frozen=True)
class ContextState:
    """Bounded transport memory for one Agent conversation/context."""

    context_id: str
    revision: int = 0
    seen_evidence: tuple[str, ...] = ()
    seen_results: tuple[str, ...] = ()
    schema_version: int = CONTEXT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _validate_context_id(self.context_id)
        if self.schema_version != CONTEXT_SCHEMA_VERSION:
            raise ValueError("unsupported ContextState schema version")
        if self.revision < 0:
            raise ValueError("context revision cannot be negative")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "context_id": self.context_id,
            "revision": self.revision,
            "seen_evidence": list(self.seen_evidence),
            "seen_results": list(self.seen_results),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ContextState":
        schema_version = int(payload.get("schema_version") or 0)
        if schema_version != CONTEXT_SCHEMA_VERSION:
            raise ValueError("unsupported ContextState schema version")
        context_id = _validate_context_id(str(payload.get("context_id") or ""))
        revision = int(payload.get("revision") or 0)
        evidence = payload.get("seen_evidence") or []
        results = payload.get("seen_results") or []
        if not isinstance(evidence, list) or not all(isinstance(item, str) for item in evidence):
            raise ValueError("ContextState seen_evidence must be a string list")
        if not isinstance(results, list) or not all(isinstance(item, str) for item in results):
            raise ValueError("ContextState seen_results must be a string list")
        return cls(
            context_id=context_id,
            revision=revision,
            seen_evidence=tuple(evidence),
            seen_results=tuple(results),
            schema_version=schema_version,
        )


class ContextStateStore:
    """Atomically persist bounded Agent seen-state beside a private Ledger."""

    def __init__(self, root: str | Path, context_id: str) -> None:
        self.root = Path(root).expanduser().resolve()
        self.context_id = _validate_context_id(context_id)
        self.path = self.root / "_contexts" / f"{self.context_id}.json"

    def load(self) -> ContextState:
        if not self.path.exists():
            return ContextState(context_id=self.context_id)
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            raise ValueError("ContextState file must contain a JSON object")
        state = ContextState.from_dict(payload)
        if state.context_id != self.context_id:
            raise ValueError("ContextState context_id mismatch")
        return state

    def save(self, state: ContextState) -> None:
        if state.context_id != self.context_id:
            raise ValueError("cannot save ContextState under a different context_id")
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
            if temporary.exists():
                temporary.unlink()

    def reset(self) -> None:
        if self.path.exists():
            self.path.unlink()


def project_search_delta(
    payload: Mapping[str, Any],
    state: ContextState,
    *,
    result_id: str | None = None,
    max_seen_evidence: int = DEFAULT_MAX_SEEN_EVIDENCE,
    max_seen_results: int = DEFAULT_MAX_SEEN_RESULTS,
) -> tuple[dict[str, Any], ContextState]:
    """Return only evidence not previously seen by this Agent context.

    ``payload`` is treated as immutable canonical input. Evidence without a URI
    cannot be safely deduplicated and is therefore retained in every view.
    """

    if payload.get("operation") != "search":
        raise ValueError("Context Engine currently projects canonical search Results")
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
    seen_order = list(state.seen_evidence)
    delta_evidence: list[dict[str, Any]] = []
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
        seen_order.append(uri)
        delta_evidence.append(item)

    bounded_evidence, evidence_pruned = _bounded_tail(seen_order, max_seen_evidence)
    result_order = list(state.seen_results)
    result_repeated = bool(result_id and result_id in set(state.seen_results))
    if result_id and result_id not in set(state.seen_results):
        result_order.append(result_id)
    bounded_results, results_pruned = _bounded_tail(result_order, max_seen_results)

    next_state = ContextState(
        context_id=state.context_id,
        revision=state.revision + 1,
        seen_evidence=bounded_evidence,
        seen_results=bounded_results,
    )
    state_pruned = evidence_pruned or results_pruned

    result["evidence"] = delta_evidence
    data = dict(result.get("data") or {})
    data["context"] = {
        "schema_version": CONTEXT_SCHEMA_VERSION,
        "id": state.context_id,
        "revision": next_state.revision,
        "mode": "delta",
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
    """Stateful facade that persists seen-state after each successful projection."""

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
        self.store = ContextStateStore(root, context_id)
        self.max_seen_evidence = max_seen_evidence
        self.max_seen_results = max_seen_results

    def project_search(
        self,
        payload: Mapping[str, Any],
        *,
        result_id: str | None = None,
    ) -> dict[str, Any]:
        state = self.store.load()
        projected, next_state = project_search_delta(
            payload,
            state,
            result_id=result_id,
            max_seen_evidence=self.max_seen_evidence,
            max_seen_results=self.max_seen_results,
        )
        self.store.save(next_state)
        return projected

    def state(self) -> ContextState:
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
