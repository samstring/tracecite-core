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

from .agent_api import EvidenceRequest, QueryTarget, RangeTarget, RetrievalResult
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


def _logicalize_fidelity(payload: dict[str, Any], source: Path) -> dict[str, Any]:
    """Keep immutable snapshot paths internal while labels show the logical source name."""

    logical_name = source.name
    evidence = payload.get("evidence")
    if isinstance(evidence, list):
        rewritten: list[Any] = []
        for raw in evidence:
            if not isinstance(raw, Mapping):
                rewritten.append(raw)
                continue
            item = dict(raw)
            snapshot_name = Path(str(item.get("source_path") or "")).name
            label = str(item.get("label") or "")
            if snapshot_name and snapshot_name != logical_name and label:
                item["label"] = label.replace(f"{snapshot_name}:", f"{logical_name}:")
            rewritten.append(item)
        payload["evidence"] = rewritten

    missing = payload.get("missing_evidence")
    if isinstance(missing, list):
        rewritten_missing: list[Any] = []
        for raw in missing:
            if not isinstance(raw, Mapping):
                rewritten_missing.append(raw)
                continue
            item = dict(raw)
            if item.get("source"):
                item["source"] = logical_name
            rewritten_missing.append(item)
        payload["missing_evidence"] = rewritten_missing

    data = payload.get("data")
    if isinstance(data, Mapping):
        data_copy = dict(data)
        integrity = data_copy.get("evidence_integrity")
        if isinstance(integrity, Mapping):
            integrity_copy = dict(integrity)
            scoped = integrity_copy.get("scoped_identity")
            if isinstance(scoped, list):
                scoped_copy: list[Any] = []
                for raw in scoped:
                    if isinstance(raw, Mapping):
                        item = dict(raw)
                        item["source"] = logical_name
                        scoped_copy.append(item)
                    else:
                        scoped_copy.append(raw)
                integrity_copy["scoped_identity"] = scoped_copy
            data_copy["evidence_integrity"] = integrity_copy
        payload["data"] = data_copy
    return payload


def _fidelity(payload: Mapping[str, Any], *, source: Path) -> dict[str, Any]:
    candidate = dict(payload)
    original_operation = str(candidate.get("operation") or "evidence_shell")
    candidate["operation"] = "search"
    enriched = enrich_search_leaf_context(candidate)
    enriched["operation"] = original_operation
    return _logicalize_fidelity(enriched, source)


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
        actionable = item.get("actionable") is not False
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


def _attach_novelty_basis(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    if not isinstance(data, Mapping):
        return payload
    novelty = data.get("novelty")
    if not isinstance(novelty, Mapping):
        return payload
    if str(novelty.get("state") or "") != "no_new_evidence":
        return payload
    data_copy = dict(data)
    novelty_copy = dict(novelty)
    novelty_copy.setdefault("basis", ["all_returned_evidence_already_seen"])
    data_copy["novelty"] = novelty_copy
    payload["data"] = data_copy
    return payload


def _canonical_reference_payload(
    request: EvidenceRequest,
    payload: dict[str, Any],
    projected_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Keep repeated exact refs canonical for explicit formal Test linkage.

    ``RetrievalResult.to_dict`` still projects only ``new_evidence``, so these
    repeated pointers do not re-enter ordinary Agent context as Evidence bodies.
    Formal benchmark/host adapters may deliberately inspect canonical refs to
    emit an ``@EVIDENCE_REF`` token for the Test that just matched them.
    """

    if request.test_id is None or projected_rows:
        return payload
    data = payload.get("data")
    repeated = data.get("matched_existing_evidence") if isinstance(data, Mapping) else None
    if not isinstance(repeated, list):
        return payload
    refs = [dict(item) for item in repeated if isinstance(item, Mapping)]
    if not refs:
        return payload
    canonical = dict(payload)
    canonical["evidence"] = refs
    return canonical


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
    payload = _fidelity(payload, source=Path(target.source).expanduser().resolve())
    payload = _attach_novelty_basis(payload)
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
    canonical_payload = _canonical_reference_payload(request, payload, rows)

    return RetrievalResult(
        operation="search",
        status=status,
        canonical_result=canonical_payload,
        progress=progress,
        new_evidence=tuple(rows),
        repeated_evidence=max(0, repeated),
    )


def materialize(
    target: RangeTarget,
    *,
    session: RetrievalSessionStore | None = None,
    routing_policy: EvidenceRoutingPolicy | None = None,
) -> RetrievalResult:
    """Return explicitly requested raw context even when its Evidence ID was seen before.

    Retrieval novelty still reports zero new Evidence, but a caller that asks to
    materialize an exact immutable range has performed useful I/O and receives
    that raw context with status ``ok`` instead of having the read disguised as
    ``no_new_evidence``.
    """

    result = _legacy.materialize(
        target,
        session=session,
        routing_policy=routing_policy,
    )
    if result.status != "no_new_evidence":
        return result
    data = result.canonical_result.get("data") or {}
    if not isinstance(data, Mapping) or "text" not in data:
        return result
    return RetrievalResult(
        operation=result.operation,
        status="ok",
        canonical_result=result.canonical_result,
        progress=result.progress,
        new_evidence=result.new_evidence,
        repeated_evidence=result.repeated_evidence,
        acquisition_end_reason=result.acquisition_end_reason,
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
