"""Public Evidence Runtime API with SessionSourceView QueryTarget semantics.

Non-text operations delegate to the existing canonical implementation. Text
QueryTarget retrieval is normalized through the Evidence Shell while keeping
RetrievalSession novelty, InvestigationStore execution linkage, and bounded
structured-leaf fidelity enrichment.
"""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any, Mapping

from .agent_api import EvidenceRequest, QueryTarget, RetrievalResult
from .evidence_fidelity import enrich_search_leaf_context
from .evidence_progress import EvidenceGap, EvidenceProgressTracker
from .evidence_routing import EvidenceRoutingPolicy
from .evidence_shell_public import EvidenceShellPolicy, EvidenceShellRequest, run_evidence_shell
from .investigation import InvestigationStore
from .retrieval_session import RetrievalSessionState, RetrievalSessionStore
from . import evidence_api as _legacy


AggregateOperation = _legacy.AggregateOperation
AggregateRequest = _legacy.AggregateRequest
aggregate = _legacy.aggregate
materialize = _legacy.materialize
replay = _legacy.replay
verify = _legacy.verify


def _tracker(state: RetrievalSessionState | None) -> EvidenceProgressTracker:
    tracker = EvidenceProgressTracker()
    if state is None:
        return tracker
    tracker.restore(evidence_ids=state.seen_evidence)
    for source, ranges in state.covered_ranges.items():
        tracker.restore(source=source, line_ranges=ranges)
    return tracker


def _rows(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        dict(item)
        for item in payload.get("evidence") or []
        if isinstance(item, Mapping)
    ]


def _pointer_ids(rows: list[Mapping[str, Any]]) -> tuple[str, ...]:
    return tuple(
        str(item.get("uri") or "").strip()
        for item in rows
        if str(item.get("uri") or "").strip()
    )


def _effective_session(
    request: EvidenceRequest,
    session: RetrievalSessionStore | None,
) -> RetrievalSessionStore | None:
    if session is not None:
        return session
    if request.investigation_path is None:
        return None
    return RetrievalSessionStore.for_investigation(request.investigation_path)


def _search_program(target: QueryTarget) -> str:
    command = "regex" if target.regex else "search"
    return f"{command} {shlex.quote(target.query)}"


def _fidelity(payload: Mapping[str, Any]) -> dict[str, Any]:
    candidate = dict(payload)
    original_operation = str(candidate.get("operation") or "evidence_shell")
    candidate["operation"] = "search"
    enriched = enrich_search_leaf_context(candidate)
    enriched["operation"] = original_operation
    return enriched


def _audit_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    if result.get("evidence"):
        return result
    data = result.get("data") or {}
    repeated = data.get("matched_existing_evidence") if isinstance(data, Mapping) else None
    if isinstance(repeated, list):
        result["evidence"] = [
            dict(item) for item in repeated if isinstance(item, Mapping)
        ]
    return result


def _record_query_execution(request: EvidenceRequest, payload: Mapping[str, Any]) -> None:
    if request.investigation_path is None:
        return
    target = request.target
    assert isinstance(target, QueryTarget)
    InvestigationStore(request.investigation_path).record_execution(
        "search",
        _audit_payload(payload),
        hypothesis_id=request.hypothesis_id,
        test_id=request.test_id,
        parameters={
            "source": str(Path(target.source).expanduser().resolve()),
            "query": target.query,
            "regex": target.regex,
            "segmenter": target.segmenter,
            "last": target.last,
            "since": target.since,
            "until": target.until,
            "shell_program": _search_program(target),
        },
    )


def _progress_gaps(payload: Mapping[str, Any]) -> list[EvidenceGap]:
    gaps: list[EvidenceGap] = []
    for index, item in enumerate(payload.get("missing_evidence") or []):
        if not isinstance(item, Mapping):
            continue
        if item.get("actionable") is False:
            actionable = False
        else:
            actionable = True
        identifier = str(item.get("identifier_value") or "").strip()
        kind = str(item.get("kind") or "evidence_gap").strip()
        gap_id = f"{kind}:{identifier or index}"[:128]
        gaps.append(
            EvidenceGap(
                id=gap_id,
                detail=str(item.get("detail") or ""),
                actionable=actionable,
            )
        )
    return gaps


def _query_via_shell(
    request: EvidenceRequest,
    *,
    session: RetrievalSessionStore | None,
) -> RetrievalResult:
    target = request.target
    assert isinstance(target, QueryTarget)
    effective_session = _effective_session(request, session)
    before = effective_session.load() if effective_session is not None else None

    payload = run_evidence_shell(
        EvidenceShellRequest(
            source=target.source,
            program=_search_program(target),
            segmenter=target.segmenter,
            last=target.last,
            since=target.since,
            until=target.until,
            fold=target.fold,
        ),
        policy=EvidenceShellPolicy(),
        session=effective_session,
    )
    payload = _fidelity(payload)
    _record_query_execution(request, payload)

    rows = _rows(payload)
    tracker = _tracker(before)
    tracker.set_gaps(_progress_gaps(payload))
    progress = tracker.observe(evidence_ids=_pointer_ids(rows))
    coverage = payload.get("coverage") or {}
    repeated = int(coverage.get("repeated_evidence") or 0) if isinstance(coverage, Mapping) else 0
    data = payload.get("data") or {}
    novelty = data.get("novelty") if isinstance(data, Mapping) else None
    novelty_state = str(novelty.get("state") or "") if isinstance(novelty, Mapping) else ""
    canonical_status = str(payload.get("status") or "unknown")
    status = (
        "no_new_evidence"
        if canonical_status == "ok" and novelty_state == "no_new_evidence"
        else canonical_status
    )

    return RetrievalResult(
        operation="search",
        status=status,
        canonical_result=payload,
        progress=progress,
        new_evidence=tuple(rows),
        repeated_evidence=max(0, repeated),
    )


def retrieve(
    request: EvidenceRequest,
    *,
    session: RetrievalSessionStore | None = None,
    routing_policy: EvidenceRoutingPolicy | None = None,
) -> RetrievalResult:
    if not isinstance(request, EvidenceRequest):
        raise TypeError("retrieve requires EvidenceRequest")
    if isinstance(request.target, QueryTarget):
        return _query_via_shell(request, session=session)
    return _legacy.retrieve(
        request,
        session=session,
        routing_policy=routing_policy,
    )


__all__ = [
    "AggregateOperation",
    "AggregateRequest",
    "aggregate",
    "materialize",
    "replay",
    "retrieve",
    "verify",
]
