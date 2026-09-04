"""Small canonical Agent API over Runtime evidence primitives.

Mechanical novelty and immutable-range coverage are owned by RetrievalSession.
This module exposes evidence-acquisition facts only: retrieval status, novelty,
coverage, provenance and explicit bounded acquisition-end reasons.  It never
turns no-growth or repeated evidence into an investigation stop recommendation.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence, Union

from tracecite.extension.evidence import EntityRef
from tracecite.extension.retrieval import (
    EvidenceProvider,
    RetrieveRequest as ProviderRetrieveRequest,
    RetrieveResult as ProviderRetrieveResult,
)

from . import tools as _tools
from .correlation import EvidenceNode
from .evidence_identity import file_source_version, pointer_source_key
from .evidence_progress import AcquisitionEndReason, EvidenceProgress, EvidenceProgressTracker
from .traversal_frontier import TraversalLimits
from .investigation import InvestigationStore
from .traversal import EvidenceTraversal, traverse_evidence
from .reducer import ReductionPolicy
from .retrieval_session import (
    DEFAULT_MAX_SEEN_EVIDENCE,
    RetrievalSessionState,
    RetrievalSessionStore,
)


@dataclass(frozen=True)
class SourceTarget:
    """Inspect one local source or source collection without a semantic query."""

    source: Union[str, Path]
    glob: str = "*"
    recursive: bool = False
    segmenter: str = "auto"


@dataclass(frozen=True)
class QueryTarget:
    """Search one local source while preserving canonical tool semantics."""

    source: Union[str, Path]
    query: str
    regex: bool = False
    snapshot: bool = True
    segmenter: str = "auto"
    last: str | None = None
    since: str | None = None
    until: str | None = None
    fold: bool = False
    max_evidence: int | None = None
    max_line_chars: int | None = None

    def __post_init__(self) -> None:
        if not str(self.query or ""):
            raise ValueError("query target requires a non-empty query")


@dataclass(frozen=True)
class RangeTarget:
    """Materialize a bounded local Evidence range.

    Duplicate-body suppression is permitted only when ``expected_sha256``
    proves the current immutable source version is the version already covered
    by the linked RetrievalSession.
    """

    source: Union[str, Path]
    start_line: int
    end_line: int | None = None
    before: int = 3
    after: int = 3
    expected_sha256: str | None = None
    max_chars: int = 20_000

    def __post_init__(self) -> None:
        if isinstance(self.start_line, bool) or not isinstance(self.start_line, int) or self.start_line < 1:
            raise ValueError("start_line must be a positive integer")
        if self.end_line is not None and (
            isinstance(self.end_line, bool)
            or not isinstance(self.end_line, int)
            or self.end_line < self.start_line
        ):
            raise ValueError("end_line must be >= start_line")
        if self.max_chars < 1:
            raise ValueError("max_chars must be positive")


@dataclass(frozen=True)
class ProviderTarget:
    """Delegate one bounded identity/entity request to EvidenceProvider(s)."""

    request: ProviderRetrieveRequest

    def __post_init__(self) -> None:
        if not isinstance(self.request, ProviderRetrieveRequest):
            raise ValueError("provider target requires ProviderRetrieveRequest")


RetrieveTarget = Union[SourceTarget, QueryTarget, RangeTarget, ProviderTarget]


@dataclass(frozen=True)
class EvidenceRequest:
    """High-level retrieval request used by Agent/MCP/Mobile adapters."""

    target: RetrieveTarget
    investigation_path: Union[str, Path, None] = None
    hypothesis_id: str | None = None
    test_id: str | None = None
    cache: bool = True
    providers: tuple[EvidenceProvider, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.target, (SourceTarget, QueryTarget, RangeTarget, ProviderTarget)):
            raise ValueError("unsupported retrieval target")
        providers = tuple(self.providers)
        object.__setattr__(self, "providers", providers)
        if isinstance(self.target, ProviderTarget) and not providers:
            raise ValueError("provider target requires at least one EvidenceProvider")


@dataclass(frozen=True)
class RetrievalResult:
    """Canonical result plus a novelty-aware Agent projection."""

    operation: str
    status: str
    canonical_result: Mapping[str, Any]
    progress: EvidenceProgress
    new_evidence: tuple[Mapping[str, Any], ...] = ()
    repeated_evidence: int = 0
    acquisition_end_reason: AcquisitionEndReason | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "canonical_result", dict(self.canonical_result))
        object.__setattr__(self, "new_evidence", tuple(dict(item) for item in self.new_evidence))

    def to_dict(self) -> dict[str, Any]:
        payload = dict(self.canonical_result)
        payload["operation"] = self.operation
        payload["status"] = self.status
        payload["evidence"] = [dict(item) for item in self.new_evidence]
        coverage = dict(payload.get("coverage") or {})
        coverage["new_evidence"] = len(self.new_evidence)
        coverage["repeated_evidence"] = self.repeated_evidence
        payload["coverage"] = coverage
        data = dict(payload.get("data") or {})
        data["progress"] = self.progress.to_dict()
        if self.acquisition_end_reason is not None:
            data["acquisition_end_reason"] = self.acquisition_end_reason.to_dict()
        payload["data"] = data
        return payload


@dataclass(frozen=True)
class CanonicalTraversalResult:
    """Current deterministic provider traversal result plus mechanical progress.

    ``investigate``/``EvidenceTraversal`` are retained only until the
    dedicated traversal refactor.  The end reason here describes only why this
    bounded mechanical acquisition ended.
    """

    traversal: EvidenceTraversal
    progress: EvidenceProgress
    acquisition_end_reason: AcquisitionEndReason | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = self.traversal.to_dict()
        payload["progress"] = self.progress.to_dict()
        if self.acquisition_end_reason is not None:
            payload["acquisition_end_reason"] = self.acquisition_end_reason.to_dict()
        return payload


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _pointer_ids(evidence: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            str(item.get("uri") or "").strip()
            for item in evidence
            if str(item.get("uri") or "").strip()
        )
    )


def _with_novelty(
    canonical: Mapping[str, Any],
    *,
    state: str,
    basis: Sequence[str] = (),
    source_version: str | None = None,
) -> dict[str, Any]:
    payload = dict(canonical)
    data = dict(payload.get("data") or {})
    novelty: dict[str, Any] = {
        "state": str(state),
        "basis": [str(item) for item in basis if str(item)],
    }
    if source_version:
        novelty["source_version"] = source_version
    data["novelty"] = novelty
    payload["data"] = data
    return payload


def _progress_store(investigation_path: Union[str, Path, None]) -> RetrievalSessionStore | None:
    if investigation_path is None:
        return None
    return RetrievalSessionStore.for_investigation(investigation_path)


def _bind_progress_store(
    tracker: EvidenceProgressTracker,
    store: RetrievalSessionStore,
) -> EvidenceProgressTracker:
    setattr(tracker, "_retrieval_session_store", store)
    return tracker


def _restore_from_session(state: RetrievalSessionState) -> EvidenceProgressTracker:
    tracker = EvidenceProgressTracker()
    tracker.restore(evidence_ids=state.seen_evidence)
    for source, ranges in state.covered_ranges.items():
        tracker.restore(source=source, line_ranges=ranges)
    return tracker


def _restore_progress(investigation_path: Union[str, Path, None]) -> EvidenceProgressTracker:
    """Restore only canonical RetrievalSession state.

    InvestigationState audit executions are never replayed into retrieval
    novelty. If a caller explicitly supplies an investigation path, it gets a
    dedicated RetrievalSession namespace and starts empty unless that canonical
    session already exists.
    """

    if investigation_path is None:
        return EvidenceProgressTracker()
    store = RetrievalSessionStore.for_investigation(investigation_path)
    tracker = _restore_from_session(store.load())
    return _bind_progress_store(tracker, store)

def _persist_observation(
    investigation_path: Union[str, Path, None],
    *,
    tracker: EvidenceProgressTracker,
    evidence_ids: Sequence[str],
    source_key: str | None,
    line_ranges: Sequence[tuple[int, int]],
) -> None:
    store = _progress_store(investigation_path)
    if store is None:
        candidate = getattr(tracker, "_retrieval_session_store", None)
        store = candidate if isinstance(candidate, RetrievalSessionStore) else None
    if store is None:
        return
    state = store.load()
    evidence_limit = max(
        DEFAULT_MAX_SEEN_EVIDENCE,
        len(state.seen_evidence) + len(tuple(evidence_ids)) + 1,
    )
    next_state, _ = state.advance(
        evidence=evidence_ids,
        covered_ranges={source_key: tuple(line_ranges)} if source_key and line_ranges else None,
        max_seen_evidence=evidence_limit,
    )
    store.save(next_state)


def _observe_tool_result(
    tracker: EvidenceProgressTracker,
    result: Mapping[str, Any],
    *,
    source_key: str | None = None,
    range_from_coverage: bool = False,
    investigation_path: Union[str, Path, None] = None,
) -> tuple[EvidenceProgress, tuple[Mapping[str, Any], ...], int]:
    evidence = tuple(item for item in result.get("evidence") or [] if isinstance(item, Mapping))
    prior = tracker.seen_evidence_ids
    ids = _pointer_ids(evidence)
    ranges: tuple[tuple[int, int], ...] = ()
    coverage = result.get("coverage") or {}
    if (
        range_from_coverage
        and source_key
        and isinstance(coverage, Mapping)
        and not bool(coverage.get("truncated"))
    ):
        start = coverage.get("context_start_line")
        end = coverage.get("context_end_line")
        if (
            isinstance(start, int)
            and not isinstance(start, bool)
            and isinstance(end, int)
            and not isinstance(end, bool)
            and end >= start
        ):
            ranges = ((start, end),)
    progress = tracker.observe(source=source_key, evidence_ids=ids, line_ranges=ranges)
    _persist_observation(
        investigation_path,
        tracker=tracker,
        evidence_ids=ids,
        source_key=source_key,
        line_ranges=ranges,
    )
    new_rows = tuple(
        item for item in evidence if str(item.get("uri") or "").strip() not in prior
    )
    repeated = max(0, len(evidence) - len(new_rows))
    return progress, new_rows, repeated


def _no_new_result(
    *,
    operation: str,
    tracker: EvidenceProgressTracker,
    source_key: str | None,
    basis: Sequence[str],
) -> RetrievalResult:
    progress = tracker.observe(source=source_key)
    canonical = _with_novelty(
        {
            "operation": operation,
            "status": "ok",
            "outcome": "not_assessed",
            "evidence": [],
            "coverage": {},
            "data": {},
        },
        state="no_new_evidence",
        basis=basis,
        source_version=source_key,
    )
    return RetrievalResult(
        operation=operation,
        status="no_new_evidence",
        canonical_result=canonical,
        progress=progress,
    )


def _retrieve_provider(request: EvidenceRequest, tracker: EvidenceProgressTracker) -> RetrievalResult:
    assert isinstance(request.target, ProviderTarget)
    target = request.target.request
    provider_rows: list[dict[str, Any]] = []
    evidence_rows: list[dict[str, Any]] = []
    provider_statuses: list[str] = []
    seen_provider_keys: set[str] = set()
    for provider in sorted(request.providers, key=lambda item: str(getattr(item, "name", ""))):
        name = str(getattr(provider, "name", "") or "").strip()
        if not name:
            raise ValueError("evidence provider requires a non-empty name")
        if not provider.can_handle(target):
            continue
        result = provider.retrieve(target)
        if not isinstance(result, ProviderRetrieveResult):
            raise TypeError("provider.retrieve must return RetrieveResult")
        provider_statuses.append(result.status)
        provider_rows.append({"provider": name, **result.to_dict()})
        for item in result.evidence:
            identity = item.evidence_uri or f"provider://{name}/{item.id}"
            if identity in seen_provider_keys:
                continue
            seen_provider_keys.add(identity)
            evidence_rows.append(
                {
                    "uri": identity,
                    "label": item.label or item.kind,
                    "metadata": item.to_dict(),
                }
            )
    if not provider_rows:
        canonical: dict[str, Any] = {
            "operation": "retrieve",
            "status": "no_match",
            "outcome": "unknown",
            "evidence": [],
            "coverage": {"providers_handled": 0},
            "data": {"provider_results": []},
        }
    else:
        status = "ok" if all(item == "ok" for item in provider_statuses) else "partial"
        canonical = {
            "operation": "retrieve",
            "status": status,
            "outcome": "not_assessed",
            "evidence": evidence_rows,
            "coverage": {"providers_handled": len(provider_rows)},
            "data": {"provider_results": provider_rows},
        }
    progress, new_rows, repeated = _observe_tool_result(
        tracker,
        canonical,
        investigation_path=request.investigation_path,
    )
    if request.investigation_path is not None:
        InvestigationStore(request.investigation_path).record_execution(
            "retrieve",
            canonical,
            hypothesis_id=request.hypothesis_id,
            test_id=request.test_id,
            parameters={"provider_request": target.to_dict()},
        )
    resolved_status = str(canonical.get("status") or "ok")
    if evidence_rows and not new_rows:
        canonical = _with_novelty(
            canonical,
            state="no_new_evidence",
            basis=("provider_records_already_seen",),
        )
        resolved_status = "no_new_evidence"
    return RetrievalResult(
        operation="retrieve",
        status=resolved_status,
        canonical_result=canonical,
        progress=progress,
        new_evidence=new_rows,
        repeated_evidence=repeated,
    )


def retrieve(request: EvidenceRequest) -> RetrievalResult:
    """Execute one canonical evidence acquisition request."""

    if not isinstance(request, EvidenceRequest):
        raise TypeError("retrieve requires EvidenceRequest")
    tracker = _restore_progress(request.investigation_path)
    target = request.target

    if isinstance(target, SourceTarget):
        result = _tools.probe(
            target.source,
            glob=target.glob,
            recursive=target.recursive,
            segmenter=target.segmenter,
            investigation_path=request.investigation_path,
            hypothesis_id=request.hypothesis_id,
            test_id=request.test_id,
            cache=request.cache,
        )
        progress, new_rows, repeated = _observe_tool_result(
            tracker,
            result,
            investigation_path=request.investigation_path,
        )
        return RetrievalResult(
            operation="probe",
            status=str(result.get("status") or "unknown"),
            canonical_result=result,
            progress=progress,
            new_evidence=new_rows,
            repeated_evidence=repeated,
        )

    if isinstance(target, QueryTarget):
        result = _tools.search(
            target.source,
            target.query,
            regex=target.regex,
            snapshot=target.snapshot,
            segmenter=target.segmenter,
            last=target.last,
            since=target.since,
            until=target.until,
            fold=target.fold,
            max_evidence=target.max_evidence,
            max_line_chars=target.max_line_chars,
            investigation_path=request.investigation_path,
            hypothesis_id=request.hypothesis_id,
            test_id=request.test_id,
            cache=request.cache,
        )
        progress, new_rows, repeated = _observe_tool_result(
            tracker,
            result,
            investigation_path=request.investigation_path,
        )
        status = str(result.get("status") or "unknown")
        evidence_count = len(result.get("evidence") or [])
        canonical = dict(result)
        if result.get("status") != "error" and evidence_count and not new_rows:
            canonical = _with_novelty(
                canonical,
                state="no_new_evidence",
                basis=("all_returned_evidence_already_seen",),
            )
            status = "no_new_evidence"
        return RetrievalResult(
            operation="search",
            status=status,
            canonical_result=canonical,
            progress=progress,
            new_evidence=new_rows,
            repeated_evidence=repeated,
        )

    if isinstance(target, RangeTarget):
        path = Path(target.source).expanduser().resolve()
        selected_end = target.end_line or target.start_line
        context_start = max(1, target.start_line - max(0, target.before))
        context_end = selected_end + max(0, target.after)
        source_key: str | None = None
        if target.expected_sha256 and path.is_file():
            expected = str(target.expected_sha256).lower()
            expected_source_key = file_source_version(str(path), expected).key
            if tracker.range_is_covered(
                expected_source_key, context_start, context_end
            ) and _sha256(path) == expected:
                return _no_new_result(
                    operation="expand",
                    tracker=tracker,
                    source_key=expected_source_key,
                    basis=("immutable_source_identity", "requested_context_already_covered"),
                )
        result = _tools.expand(
            path,
            target.start_line,
            end_line=target.end_line,
            before=target.before,
            after=target.after,
            expected_sha256=target.expected_sha256,
            max_chars=target.max_chars,
            investigation_path=request.investigation_path,
            hypothesis_id=request.hypothesis_id,
            test_id=request.test_id,
            cache=request.cache,
        )
        if source_key is None:
            evidence = [item for item in result.get("evidence") or [] if isinstance(item, Mapping)]
            if evidence:
                source_key = pointer_source_key(evidence[0])
        progress, new_rows, repeated = _observe_tool_result(
            tracker,
            result,
            source_key=source_key,
            range_from_coverage=True,
            investigation_path=request.investigation_path,
        )
        status = str(result.get("status") or "unknown")
        coverage = result.get("coverage") or {}
        truncated = bool(coverage.get("truncated")) if isinstance(coverage, Mapping) else False
        canonical = dict(result)
        if result.get("status") != "error" and not truncated and result.get("evidence") and not new_rows:
            canonical = _with_novelty(
                canonical,
                state="no_new_evidence",
                basis=("expanded_evidence_already_seen",),
                source_version=source_key,
            )
            status = "no_new_evidence"
        return RetrievalResult(
            operation="expand",
            status=status,
            canonical_result=canonical,
            progress=progress,
            new_evidence=(
                tuple(item for item in result.get("evidence") or [] if isinstance(item, Mapping))
                if truncated
                else new_rows
            ),
            repeated_evidence=repeated,
        )

    if isinstance(target, ProviderTarget):
        return _retrieve_provider(request, tracker)
    raise AssertionError("unreachable retrieval target")


def traverse(
    providers: Sequence[EvidenceProvider],
    *,
    seed_nodes: Sequence[EvidenceNode] = (),
    seed_evidence_ids: Sequence[str] = (),
    seed_entities: Sequence[EntityRef] = (),
    exploration_policy: TraversalLimits | None = None,
    reduction_policy: ReductionPolicy | None = None,
    temporal_window_seconds: float | None = None,
    clock: Callable[[], float] | None = None,
) -> CanonicalTraversalResult:
    """Run the current bounded mechanical provider exploration implementation.

    The dedicated traversal refactor will replace the investigation naming and
    require caller-owned seed/scope/direction.  This function does not make an
    epistemic stop decision.
    """

    kwargs: dict[str, Any] = {
        "seed_nodes": seed_nodes,
        "seed_evidence_ids": seed_evidence_ids,
        "seed_entities": seed_entities,
        "exploration_policy": exploration_policy,
        "reduction_policy": reduction_policy,
        "temporal_window_seconds": temporal_window_seconds,
    }
    if clock is not None:
        kwargs["clock"] = clock
    traversal = traverse_evidence(providers, **kwargs)
    tracker = EvidenceProgressTracker()
    identities = tuple(
        dict.fromkeys(
            node.evidence_uri or node.id
            for node in traversal.graph.nodes
            if node.evidence_uri or node.id
        )
    )
    progress = tracker.observe(
        evidence_ids=identities,
        new_entities=sum(len(node.entities) for node in traversal.graph.nodes),
        new_relations=len(traversal.graph.relations),
        frontier_exhausted=traversal.stop_reason in {"frontier_exhausted", "no_evidence"},
        scope_exhausted=bool(traversal.coverage.get("complete")),
    )
    acquisition_end_reason: AcquisitionEndReason | None = None
    if traversal.stop_reason == "frontier_exhausted":
        acquisition_end_reason = AcquisitionEndReason(
            "frontier_exhausted",
            basis=("mechanical_frontier_empty",),
        )
    elif traversal.stop_reason == "no_evidence":
        acquisition_end_reason = AcquisitionEndReason(
            "frontier_exhausted",
            basis=("mechanical_frontier_empty", "no_evidence"),
        )
    elif "provider" in traversal.stop_reason:
        acquisition_end_reason = AcquisitionEndReason(
            "provider_unavailable",
            basis=(traversal.stop_reason,),
        )
    return CanonicalTraversalResult(
        traversal=traversal,
        progress=progress,
        acquisition_end_reason=acquisition_end_reason,
    )


__all__ = [
    "CanonicalTraversalResult",
    "EvidenceRequest",
    "ProviderTarget",
    "QueryTarget",
    "RangeTarget",
    "RetrievalResult",
    "RetrieveTarget",
    "SourceTarget",
    "traverse",
    "retrieve",
]
