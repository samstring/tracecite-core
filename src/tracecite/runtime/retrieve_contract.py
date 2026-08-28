"""Public adaptive retrieve contract over the canonical Agent API.

The low-level Agent API remains deterministic and target-specific.  This public
wrapper adds two product semantics without changing upper-layer request types:

1. pointer novelty and line-coverage novelty stay distinct for RangeTarget;
2. evidence transport defaults to adaptive DIRECT -> BOUNDED -> INVESTIGATE
   routing so small sources do not pay the full Evidence Intelligence overhead.
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

from . import tools as _tools
from .agent_api import (
    EvidenceRequest,
    ProviderTarget,
    QueryTarget,
    RangeTarget,
    RetrievalResult,
    SourceTarget,
    _observe_tool_result,
    _restore_progress,
    _sha256,
    retrieve as _retrieve,
)
from .evidence_identity import file_source_version
from .evidence_routing import (
    EvidenceRoute,
    EvidenceRoutingPolicy,
    RoutingDecision,
    decide_route,
    refine_route_after_result,
)
from .investigation import InvestigationStore


def _history(request: EvidenceRequest) -> tuple[Mapping[str, object], ...]:
    if request.investigation_path is None:
        return ()
    return tuple(InvestigationStore(request.investigation_path).load().executions)


def _decision(request: EvidenceRequest, policy: EvidenceRoutingPolicy) -> RoutingDecision:
    target = request.target
    source: Path | None = None
    kind = "provider"
    if isinstance(target, SourceTarget):
        kind = "source"
        source = Path(target.source).expanduser().resolve()
    elif isinstance(target, QueryTarget):
        kind = "query"
        source = Path(target.source).expanduser().resolve()
    elif isinstance(target, RangeTarget):
        kind = "range"
        source = Path(target.source).expanduser().resolve()
    elif isinstance(target, ProviderTarget):
        kind = "provider"
    return decide_route(
        target_kind=kind,
        source=source,
        policy=policy,
        executions=_history(request),
    )


def _with_routing(result: RetrievalResult, decision: RoutingDecision) -> RetrievalResult:
    canonical = dict(result.canonical_result)
    data = dict(canonical.get("data") or {})
    data["routing"] = decision.to_dict()
    canonical["data"] = data
    return RetrievalResult(
        operation=result.operation,
        status=result.status,
        canonical_result=canonical,
        progress=result.progress,
        new_evidence=result.new_evidence,
        repeated_evidence=result.repeated_evidence,
        stop_reason=result.stop_reason,
    )


def _line_count(path: Path) -> int:
    count = 0
    last = b""
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(64 * 1024), b""):
            count += block.count(b"\n")
            last = block[-1:]
    if path.stat().st_size and last != b"\n":
        count += 1
    return count


def _direct_source(
    request: EvidenceRequest,
    decision: RoutingDecision,
    policy: EvidenceRoutingPolicy,
) -> RetrievalResult:
    assert isinstance(request.target, SourceTarget)
    target = request.target
    path = Path(target.source).expanduser().resolve()
    if not path.is_file() or path.stat().st_size == 0:
        return _with_routing(_retrieve(request), decision)

    tracker = _restore_progress(request.investigation_path)
    digest = _sha256(path)
    lines = _line_count(path)
    if lines < 1:
        return _with_routing(_retrieve(request), decision)
    result = _tools.expand(
        path,
        1,
        end_line=lines,
        before=0,
        after=0,
        expected_sha256=digest,
        max_chars=policy.direct_char_budget,
        investigation_path=request.investigation_path,
        hypothesis_id=request.hypothesis_id,
        test_id=request.test_id,
        cache=request.cache,
    )
    source_key = file_source_version(str(path), digest).key
    readiness, new_rows, repeated = _observe_tool_result(
        tracker,
        result,
        source_key=source_key,
        range_from_coverage=True,
    )
    resolved = RetrievalResult(
        operation="expand",
        status=str(result.get("status") or "unknown"),
        canonical_result=result,
        progress=readiness,
        new_evidence=new_rows,
        repeated_evidence=repeated,
    )
    coverage = result.get("coverage") or {}
    if isinstance(coverage, Mapping) and bool(coverage.get("truncated")):
        # DIRECT preflight is deliberately conservative, but if rendering still
        # exceeds the budget expose a monotonic downgrade instead of pretending
        # the complete source was delivered.
        decision = RoutingDecision(
            route=EvidenceRoute.BOUNDED,
            reasons=(*decision.reasons, "direct_render_exceeded_budget"),
            source_bytes=decision.source_bytes,
            estimated_direct_chars=decision.estimated_direct_chars,
            direct_char_budget=decision.direct_char_budget,
            previous_executions=decision.previous_executions,
            source_count=decision.source_count,
            max_match_records=decision.max_match_records,
            repeated_evidence_ratio=decision.repeated_evidence_ratio,
        )
    return _with_routing(resolved, decision)


def _investigate_source(
    request: EvidenceRequest,
    decision: RoutingDecision,
    policy: EvidenceRoutingPolicy,
) -> RetrievalResult:
    """Use bounded descriptive survey for a large/deep local source.

    This is still mechanical Evidence Intelligence: no root-cause inference is
    performed.  Semantic hypotheses remain the upper Agent's responsibility.
    """

    assert isinstance(request.target, SourceTarget)
    target = request.target
    tracker = _restore_progress(request.investigation_path)
    result = _tools.survey(
        target.source,
        snapshot=True,
        segmenter=target.segmenter,
        max_templates=policy.survey_max_templates,
        samples_per_template=policy.survey_samples_per_template,
        investigation_path=request.investigation_path,
        hypothesis_id=request.hypothesis_id,
        test_id=request.test_id,
        cache=request.cache,
    )
    readiness, new_rows, repeated = _observe_tool_result(tracker, result)
    resolved = RetrievalResult(
        operation="survey",
        status=str(result.get("status") or "unknown"),
        canonical_result=result,
        progress=readiness,
        new_evidence=new_rows,
        repeated_evidence=repeated,
    )
    return _with_routing(resolved, decision)


def _bounded_query(
    request: EvidenceRequest,
    policy: EvidenceRoutingPolicy,
    *,
    route: EvidenceRoute,
) -> EvidenceRequest:
    assert isinstance(request.target, QueryTarget)
    target = request.target
    if route == EvidenceRoute.INVESTIGATE:
        evidence_cap = policy.investigate_max_evidence
        line_cap = policy.investigate_max_line_chars
    else:
        evidence_cap = policy.bounded_max_evidence
        line_cap = policy.bounded_max_line_chars
    max_evidence = (
        evidence_cap
        if target.max_evidence is None
        else min(target.max_evidence, evidence_cap)
    )
    max_line_chars = (
        line_cap
        if target.max_line_chars is None
        else min(target.max_line_chars, line_cap)
    )
    return EvidenceRequest(
        QueryTarget(
            target.source,
            target.query,
            regex=target.regex,
            snapshot=target.snapshot,
            segmenter=target.segmenter,
            last=target.last,
            since=target.since,
            until=target.until,
            fold=target.fold,
            max_evidence=max_evidence,
            max_line_chars=max_line_chars,
        ),
        investigation_path=request.investigation_path,
        hypothesis_id=request.hypothesis_id,
        test_id=request.test_id,
        cache=request.cache,
        providers=request.providers,
    )


def _correct_range_novelty(result: RetrievalResult, request: EvidenceRequest) -> RetrievalResult:
    if not isinstance(request.target, RangeTarget):
        return result
    if result.status != "no_new_evidence" or result.progress.delta.new_lines <= 0:
        return result

    canonical_evidence = tuple(
        dict(item)
        for item in result.canonical_result.get("evidence") or []
        if isinstance(item, Mapping)
    )
    status = str(result.canonical_result.get("status") or "ok")
    if status == "error":
        return result
    return RetrievalResult(
        operation=result.operation,
        status=status,
        canonical_result=result.canonical_result,
        progress=result.progress,
        new_evidence=canonical_evidence,
        repeated_evidence=result.repeated_evidence,
        stop_reason=None,
    )


def retrieve(
    request: EvidenceRequest,
    *,
    routing_policy: EvidenceRoutingPolicy | None = None,
) -> RetrievalResult:
    """Execute the stable retrieval contract with adaptive transport routing.

    Callers normally provide only ``EvidenceRequest``.  Advanced integrations
    and benchmarks may override routing with ``EvidenceRoutingPolicy`` without
    changing the request schema or adding platform-specific APIs.
    """

    if not isinstance(request, EvidenceRequest):
        raise TypeError("retrieve requires EvidenceRequest")
    policy = routing_policy or EvidenceRoutingPolicy()
    if not isinstance(policy, EvidenceRoutingPolicy):
        raise TypeError("routing_policy must be EvidenceRoutingPolicy")
    decision = _decision(request, policy)

    if isinstance(request.target, SourceTarget):
        if decision.route == EvidenceRoute.DIRECT:
            return _direct_source(request, decision, policy)
        if decision.route == EvidenceRoute.INVESTIGATE:
            return _investigate_source(request, decision, policy)
        return _with_routing(_retrieve(request), decision)

    routed_request = request
    if isinstance(request.target, QueryTarget) and decision.route != EvidenceRoute.DIRECT:
        routed_request = _bounded_query(request, policy, route=decision.route)
    result = _correct_range_novelty(_retrieve(routed_request), routed_request)
    decision = refine_route_after_result(decision, result.canonical_result, policy=policy)
    return _with_routing(result, decision)


__all__ = ["retrieve"]
