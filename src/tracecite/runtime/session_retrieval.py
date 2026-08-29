from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping

from .agent_api import EvidenceRequest, RangeTarget, RetrievalResult
from .evidence_identity import file_source_version, pointer_source_key
from .evidence_progress import EvidenceProgressTracker, StopReason
from .evidence_routing import EvidenceRoutingPolicy
from .provider_identity import namespace_provider_request
from .relationship_frontier import attach_relationship_frontier
from .retrieval_guidance import prioritize_actionable_retrieval
from .retrieval_session import (
    DEFAULT_MAX_SEEN_EVIDENCE,
    DEFAULT_MAX_SEEN_RELATIONS,
    RetrievalSessionState,
    RetrievalSessionStore,
)
from .retrieve_contract import retrieve as _retrieve_contract


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _pointer_ids(evidence: tuple[Mapping[str, Any], ...]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            str(item.get("uri") or "").strip()
            for item in evidence
            if str(item.get("uri") or "").strip()
        )
    )


def _relation_ids(canonical: Mapping[str, Any]) -> tuple[str, ...]:
    data = canonical.get("data") or {}
    if not isinstance(data, Mapping):
        return ()
    rows = data.get("observed_relations") or []
    if not isinstance(rows, list):
        return ()
    return tuple(
        dict.fromkeys(
            str(item.get("relation_id") or "").strip()
            for item in rows
            if isinstance(item, Mapping) and str(item.get("relation_id") or "").strip()
        )
    )


def _restore_tracker(state: RetrievalSessionState) -> EvidenceProgressTracker:
    tracker = EvidenceProgressTracker()
    tracker.restore(evidence_ids=state.seen_evidence)
    for source, ranges in state.covered_ranges.items():
        tracker.restore(source=source, line_ranges=ranges)
    return tracker


def _persist(
    store: RetrievalSessionStore,
    state: RetrievalSessionState,
    *,
    evidence_ids: tuple[str, ...],
    relation_ids: tuple[str, ...] = (),
    source_key: str | None = None,
    line_ranges: tuple[tuple[int, int], ...] = (),
) -> None:
    if not evidence_ids and not relation_ids and not line_ranges:
        return
    evidence_limit = max(
        DEFAULT_MAX_SEEN_EVIDENCE,
        len(state.seen_evidence) + len(evidence_ids) + 1,
    )
    relation_limit = max(
        DEFAULT_MAX_SEEN_RELATIONS,
        len(state.seen_relations) + len(relation_ids) + 1,
    )
    next_state, _ = state.advance(
        evidence=evidence_ids,
        relations=relation_ids,
        covered_ranges={source_key: line_ranges} if source_key and line_ranges else None,
        max_seen_evidence=evidence_limit,
        max_seen_relations=relation_limit,
    )
    store.save(next_state)


def _already_covered_range(
    request: EvidenceRequest,
    tracker: EvidenceProgressTracker,
) -> tuple[str, int, int] | None:
    target = request.target
    if not isinstance(target, RangeTarget) or not target.expected_sha256:
        return None
    path = Path(target.source).expanduser().resolve()
    if not path.is_file():
        return None
    expected = str(target.expected_sha256).strip().lower()
    if _sha256(path).lower() != expected:
        return None
    selected_end = target.end_line or target.start_line
    start = max(1, target.start_line - max(0, target.before))
    end = selected_end + max(0, target.after)
    source_key = file_source_version(str(path), expected).key
    if tracker.range_is_covered(source_key, start, end):
        return source_key, start, end
    return None


def retrieve_with_session(
    request: EvidenceRequest,
    session: RetrievalSessionStore,
    *,
    routing_policy: EvidenceRoutingPolicy | None = None,
) -> RetrievalResult:
    """Execute canonical retrieval with independent mechanical session memory.

    This API is for ordinary Agent/MCP retrieval that needs novelty and covered
    range memory but does not need an InvestigationState. It intentionally owns
    no hypotheses, Tests, Findings, causal conclusions, or audit decisions.

    Investigation-linked requests keep using ``runtime.retrieve`` so audit and
    budget semantics remain unchanged. A request cannot use both state owners at
    once.
    """

    if not isinstance(request, EvidenceRequest):
        raise TypeError("retrieve_with_session requires EvidenceRequest")
    if not isinstance(session, RetrievalSessionStore):
        raise TypeError("retrieve_with_session requires RetrievalSessionStore")
    if request.investigation_path is not None:
        raise ValueError("independent retrieval session cannot also use investigation_path")
    if request.hypothesis_id is not None or request.test_id is not None:
        raise ValueError("hypothesis_id/test_id require InvestigationState")

    state = session.load()
    tracker = _restore_tracker(state)
    covered = _already_covered_range(request, tracker)
    if covered is not None:
        source_key, _start, _end = covered
        readiness = tracker.observe(source=source_key)
        stop = StopReason(
            "no_new_evidence",
            scope={"source_version": source_key},
            basis=("immutable_source_identity", "requested_context_already_covered"),
        )
        return RetrievalResult(
            operation="expand",
            status="no_new_evidence",
            canonical_result={
                "operation": "expand",
                "status": "ok",
                "outcome": "not_assessed",
                "evidence": [],
                "coverage": {},
                "data": {},
            },
            progress=readiness,
            stop_reason=stop,
        )

    normalized = namespace_provider_request(request)
    base = attach_relationship_frontier(
        prioritize_actionable_retrieval(
            _retrieve_contract(normalized, routing_policy=routing_policy)
        )
    )
    canonical = dict(base.canonical_result)
    evidence = tuple(
        item for item in canonical.get("evidence") or [] if isinstance(item, Mapping)
    )
    prior = set(state.seen_evidence)
    evidence_ids = _pointer_ids(evidence)
    new_rows = tuple(
        item
        for item in evidence
        if str(item.get("uri") or "").strip() not in prior
    )
    repeated = max(0, len(evidence) - len(new_rows))

    relation_ids = _relation_ids(canonical)
    prior_relations = set(state.seen_relations)
    new_relation_ids = tuple(item for item in relation_ids if item not in prior_relations)

    source_key: str | None = None
    line_ranges: tuple[tuple[int, int], ...] = ()
    coverage = canonical.get("coverage") or {}
    truncated = (
        bool(coverage.get("truncated") or coverage.get("evidence_truncated"))
        if isinstance(coverage, Mapping)
        else False
    )
    if isinstance(request.target, RangeTarget) and evidence:
        source_key = pointer_source_key(evidence[0])
        if isinstance(coverage, Mapping) and not bool(coverage.get("truncated")):
            start = coverage.get("context_start_line")
            end = coverage.get("context_end_line")
            if (
                isinstance(start, int)
                and not isinstance(start, bool)
                and isinstance(end, int)
                and not isinstance(end, bool)
                and end >= start
            ):
                line_ranges = ((start, end),)

    readiness = tracker.observe(
        source=source_key,
        evidence_ids=evidence_ids,
        line_ranges=line_ranges,
        new_relations=len(new_relation_ids),
    )
    _persist(
        session,
        state,
        evidence_ids=evidence_ids,
        relation_ids=relation_ids,
        source_key=source_key,
        line_ranges=line_ranges,
    )

    status = base.status
    stop = base.stop_reason
    if (
        str(canonical.get("status") or "").lower() not in {"error", "no_match"}
        and evidence
        and not new_rows
        and not new_relation_ids
        and not truncated
    ):
        status = "no_new_evidence"
        stop = StopReason("no_new_evidence", basis=("all_returned_evidence_already_seen",))

    return RetrievalResult(
        operation=base.operation,
        status=status,
        canonical_result=canonical,
        progress=readiness,
        new_evidence=evidence if truncated else new_rows,
        repeated_evidence=repeated,
        stop_reason=stop,
    )


__all__ = ["retrieve_with_session"]
