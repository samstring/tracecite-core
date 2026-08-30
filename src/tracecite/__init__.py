"""TraceCite: provenance-aware, session-aware Evidence Runtime for Agents."""

from __future__ import annotations

__version__ = "0.1.0"

from .runtime import (
    AggregateOperation, AggregateRequest, EvidenceIdentity, EvidenceRequest, EvidenceRoute,
    EvidenceRoutingPolicy, EvidenceTraversal, ProviderTarget, QueryTarget, RangeTarget,
    RetrievalResult, RetrievalSessionState, RetrievalSessionStore, SourceTarget, SourceVersion,
    TraversalLimits, aggregate, list_capabilities, materialize, replay, retrieve, traverse, verify,
)

__all__ = [
    "AggregateOperation", "AggregateRequest", "EvidenceIdentity", "EvidenceRequest",
    "EvidenceRoute", "EvidenceRoutingPolicy", "EvidenceTraversal", "ProviderTarget",
    "QueryTarget", "RangeTarget", "RetrievalResult", "RetrievalSessionState",
    "RetrievalSessionStore", "SourceTarget", "SourceVersion", "TraversalLimits",
    "aggregate", "list_capabilities", "materialize", "replay", "retrieve", "traverse", "verify",
]
