"""Evidence-only public projection for canonical retrieval results.

TraceCite may internally compute routing or integrity state, but the public
retrieval contract must describe evidence, provenance, coverage, uncertainty,
and bounded evidence candidates without planning the Agent's next move.
"""

from __future__ import annotations

import copy
from typing import Any, Mapping

from .agent_api import RetrievalResult

_PLANNER_DATA_KEYS = frozenset(
    {
        "actionable_retrieval",
        "actionable_retrieval_note",
        "relationship_action",
        "relationship_frontier",
        "relationship_frontier_note",
    }
)
_PLANNER_GAP_KEYS = frozenset(
    {
        "actionable",
        "recommended_action",
        "recommended_search",
        "navigation_query",
    }
)


def evidence_only(result: RetrievalResult) -> RetrievalResult:
    """Strip planner/navigation instructions while preserving evidence facts."""

    if not isinstance(result, RetrievalResult):
        raise TypeError("evidence_only requires RetrievalResult")

    canonical = copy.deepcopy(dict(result.canonical_result))
    canonical.pop("next_queries", None)

    data = copy.deepcopy(dict(canonical.get("data") or {}))
    for key in _PLANNER_DATA_KEYS:
        data.pop(key, None)
    canonical["data"] = data

    gaps: list[dict[str, Any]] = []
    for raw in canonical.get("missing_evidence") or []:
        if not isinstance(raw, Mapping):
            continue
        gap = copy.deepcopy(dict(raw))
        for key in _PLANNER_GAP_KEYS:
            gap.pop(key, None)
        gaps.append(gap)
    if gaps:
        canonical["missing_evidence"] = gaps
    elif "missing_evidence" in canonical:
        canonical["missing_evidence"] = []

    return RetrievalResult(
        operation=result.operation,
        status=result.status,
        canonical_result=canonical,
        progress=result.progress,
        new_evidence=result.new_evidence,
        repeated_evidence=result.repeated_evidence,
        acquisition_end_reason=result.acquisition_end_reason,
    )


__all__ = ["evidence_only"]
