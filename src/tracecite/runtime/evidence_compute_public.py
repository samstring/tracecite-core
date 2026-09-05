"""Public Evidence Compute orchestration over physical planner implementations."""

from __future__ import annotations

from .evidence_compute import (
    MAX_BATCH_ANALYSES,
    EvidenceAnalysisSpec,
    EvidenceComputeRequest,
    _record_compute_session,
    run_evidence_compute as _run_legacy_compute,
)
from .evidence_compute_jsonl_physical import try_run_jsonl_batch
from .evidence_shell_public import EvidenceShellPolicy
from .retrieval_session import RetrievalSessionStore


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

    payload = try_run_jsonl_batch(request, policy=policy, session=session)
    if payload is None:
        return _run_legacy_compute(request, policy=policy, session=session)
    return _record_compute_session(payload, request=request, session=session)


__all__ = [
    "MAX_BATCH_ANALYSES",
    "EvidenceAnalysisSpec",
    "EvidenceComputeRequest",
    "run_evidence_compute",
]
