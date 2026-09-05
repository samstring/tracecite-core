"""Public Evidence Compute orchestration over physical planner implementations."""

from __future__ import annotations

from typing import Any, Mapping

from . import evidence_compute as legacy
from .evidence_compute import (
    MAX_BATCH_ANALYSES,
    EvidenceAnalysisSpec,
    EvidenceComputeRequest,
)
from .evidence_compute_jsonl_physical import try_run_jsonl_batch
from .evidence_shell import _budget_data
from .evidence_shell_public import EvidenceShellPolicy
from .retrieval_session import RetrievalSessionStore
from .schema import AgentResult


_ANALYSIS_OUTPUT_STAGES = frozenset({"count", "group", "distinct", "project"})


def _normalized_analysis(spec: EvidenceAnalysisSpec) -> tuple[str, list[Any]] | None:
    """Parse one analysis without touching its source."""

    return legacy._normalize_spec(spec)


def _requires_raw_evidence(spec: EvidenceAnalysisSpec) -> bool:
    """Return True when a syntactically valid analysis can only emit raw rows.

    Evidence Compute deliberately transports bounded derived results only. Raw
    Evidence selection belongs to Evidence Shell/``tracecite_run``. Historically
    this contract was checked *after* executing the fallback shell program,
    which meant an invalid ``sort ... | head N`` analysis could scan and sort a
    large source for tens of seconds before being rejected. Contract validation
    belongs ahead of physical planning.
    """

    prepared = _normalized_analysis(spec)
    if prepared is None:
        # Syntax/compatibility errors keep their established planner error path.
        return False
    _, stages = prepared
    return not any(stage.command in _ANALYSIS_OUTPUT_STAGES for stage in stages)


def _contract_error(spec: EvidenceAnalysisSpec) -> dict[str, Any]:
    prepared = _normalized_analysis(spec)
    normalized = prepared[0] if prepared is not None else spec.program
    return {
        "name": spec.name,
        "status": "error",
        "program": normalized,
        "coverage": {"complete": False},
        "execution_engine": "analysis_contract_preflight",
        "error_code": "analysis_requires_bounded_aggregate",
        "error": (
            "batch evidence compute accepts bounded aggregate/project programs only; "
            "use tracecite_run for raw Evidence selection"
        ),
    }


def _unrecorded_compute(
    request: EvidenceComputeRequest,
    *,
    policy: EvidenceShellPolicy,
    session: RetrievalSessionStore | None,
) -> dict[str, Any]:
    """Execute one request without recording the outer batch operation yet."""

    payload = try_run_jsonl_batch(request, policy=policy, session=session)
    if payload is not None:
        return payload
    payload = legacy._try_partitioned_jsonl(request, policy=policy, session=session)
    if payload is not None:
        return payload
    return legacy._fallback_sequential(request, policy=policy, session=session)


def _merge_contract_rejections(
    request: EvidenceComputeRequest,
    *,
    policy: EvidenceShellPolicy,
    session: RetrievalSessionStore | None,
    rejected: Mapping[str, dict[str, Any]],
) -> dict[str, Any]:
    valid_specs = tuple(spec for spec in request.analyses if spec.name not in rejected)

    if valid_specs:
        valid_request = EvidenceComputeRequest(
            source=request.source,
            analyses=valid_specs,
            segmenter=request.segmenter,
            last=request.last,
            since=request.since,
            until=request.until,
        )
        payload = _unrecorded_compute(valid_request, policy=policy, session=session)
        result = dict(payload)
        data = dict(result.get("data") or {})
        valid_outputs = {
            str(item.get("name") or ""): dict(item)
            for item in data.get("outputs") or ()
            if isinstance(item, Mapping)
        }
        outputs = [
            dict(rejected[spec.name]) if spec.name in rejected else valid_outputs[spec.name]
            for spec in request.analyses
        ]
        data["outputs"] = outputs
        data["analysis_count"] = len(outputs)
        data["contract_rejected_analyses"] = len(rejected)
        result["data"] = data
        result["status"] = "partial"
        coverage = dict(result.get("coverage") or {})
        coverage["complete"] = False
        result["coverage"] = coverage
        return legacy._record_compute_session(result, request=request, session=session)

    # Every analysis was rejected from syntax alone. Do not resolve or scan the
    # source merely to discover a contract violation already known at preflight.
    outputs = [dict(rejected[spec.name]) for spec in request.analyses]
    return AgentResult(
        operation="evidence_compute",
        status="partial",
        outcome="not_assessed",
        coverage={"complete": False},
        data={
            "outputs": outputs,
            "analysis_count": len(outputs),
            "contract_rejected_analyses": len(outputs),
            "execution_engine": "analysis_contract_preflight",
            "evidence_budget": _budget_data(policy),
            "time_scope": {
                "last": request.last,
                "since": request.since,
                "until": request.until,
            },
        },
    ).to_dict()


def run_evidence_compute(
    request: EvidenceComputeRequest,
    *,
    policy: EvidenceShellPolicy,
    session: RetrievalSessionStore | None = None,
) -> dict:
    """Run bounded analyses using the best semantics-preserving physical plan."""

    if not isinstance(request, EvidenceComputeRequest):
        raise TypeError("run_evidence_compute requires EvidenceComputeRequest")
    if not isinstance(policy, EvidenceShellPolicy):
        raise TypeError("policy must be EvidenceShellPolicy")

    rejected = {
        spec.name: _contract_error(spec)
        for spec in request.analyses
        if _requires_raw_evidence(spec)
    }
    if rejected:
        return _merge_contract_rejections(
            request,
            policy=policy,
            session=session,
            rejected=rejected,
        )

    payload = _unrecorded_compute(request, policy=policy, session=session)
    return legacy._record_compute_session(payload, request=request, session=session)


__all__ = [
    "MAX_BATCH_ANALYSES",
    "EvidenceAnalysisSpec",
    "EvidenceComputeRequest",
    "run_evidence_compute",
]
