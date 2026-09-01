"""TraceCite Evidence Runtime public contract."""

from .agent_api import (
    EvidenceRequest, ProviderTarget, QueryTarget, RangeTarget, RetrievalResult,
    RetrieveTarget, SourceTarget, CanonicalTraversalResult, traverse,
)
from .evidence_api import (
    AggregateOperation, AggregateRequest, aggregate, materialize, replay, retrieve, verify,
)
from .evidence_coordinates import (
    DEFAULT_EVIDENCE_NEIGHBOR_LIMIT, DEFAULT_EVIDENCE_NEIGHBOR_RADIUS_LINES,
    DEFAULT_POSITION_PEER_LIMIT, DEFAULT_SEEN_RANGE_LIMIT, MAX_EVIDENCE_NEIGHBOR_LIMIT,
    MAX_EVIDENCE_NEIGHBOR_RADIUS_LINES, MAX_POSITION_PEER_LIMIT, MAX_SEEN_RANGE_LIMIT,
    attach_seen_evidence_distances, attach_seen_range_distances, attach_source_line_coordinates,
)
from .evidence_identity import (
    EvidenceIdentity, SourceVersion, SourceVersionKind, file_source_version, pointer_source_key,
)
from .evidence_progress import (
    AcquisitionEndKind, AcquisitionEndReason, CoverageStatus, EvidenceDelta, EvidenceGap,
    EvidenceProgress, EvidenceProgressTracker,
)
from .evidence_routing import (
    EvidenceRoute, EvidenceRoutingPolicy, RoutingDecision, decide_route,
    estimate_line_addressable_chars, refine_route_after_result,
)
from .retrieval_session import (
    DEFAULT_MAX_SEEN_EVIDENCE_COORDINATES, EvidenceCoordinate, RetrievalOperation,
    RetrievalSessionState, RetrievalSessionStore,
)
from .traversal import EvidenceTraversal, TraversalStep, traverse_evidence
from .traversal_frontier import TraversalFrontier, TraversalItem, TraversalLimits, TraversalStats
from .capabilities import (
    CapabilityError, CapabilitySpec, execute_capability, get_capability, list_capabilities, register_capability,
)
# Optional Host/Agent work-state APIs remain explicit secondary surfaces.
# They are not consulted by RetrievalSession novelty or Evidence routing.
from .investigation import (
    BudgetExhausted, BudgetPolicy, InvestigationError, InvestigationState, InvestigationStore,
    create_investigation, load_investigation,
)

# Activate the mechanical Finding persistence gate whenever Runtime exposes
# InvestigationStore. Validation helpers remain a secondary module and are not
# added to the public Runtime surface.
from . import finding_validation as _finding_validation

__all__ = [
    "AcquisitionEndKind", "AcquisitionEndReason", "AggregateOperation", "AggregateRequest",
    "CanonicalTraversalResult", "CapabilityError", "CapabilitySpec", "CoverageStatus",
    "DEFAULT_EVIDENCE_NEIGHBOR_LIMIT", "DEFAULT_EVIDENCE_NEIGHBOR_RADIUS_LINES",
    "DEFAULT_MAX_SEEN_EVIDENCE_COORDINATES", "DEFAULT_POSITION_PEER_LIMIT",
    "DEFAULT_SEEN_RANGE_LIMIT", "EvidenceCoordinate", "EvidenceDelta", "EvidenceGap",
    "EvidenceIdentity", "EvidenceProgress", "EvidenceProgressTracker", "EvidenceRequest",
    "EvidenceRoute", "EvidenceRoutingPolicy", "EvidenceTraversal", "MAX_EVIDENCE_NEIGHBOR_LIMIT",
    "MAX_EVIDENCE_NEIGHBOR_RADIUS_LINES", "MAX_POSITION_PEER_LIMIT", "MAX_SEEN_RANGE_LIMIT",
    "ProviderTarget", "QueryTarget", "RangeTarget", "RetrievalOperation", "RetrievalResult",
    "RetrievalSessionState", "RetrievalSessionStore", "RetrieveTarget", "RoutingDecision",
    "SourceTarget", "SourceVersion", "SourceVersionKind", "TraversalFrontier", "TraversalItem",
    "TraversalLimits", "TraversalStats", "TraversalStep", "aggregate",
    "attach_seen_evidence_distances", "attach_seen_range_distances", "attach_source_line_coordinates",
    "decide_route", "estimate_line_addressable_chars", "execute_capability", "file_source_version",
    "get_capability", "list_capabilities", "BudgetExhausted", "BudgetPolicy", "InvestigationError",
    "InvestigationState", "InvestigationStore", "create_investigation", "load_investigation",
    "materialize", "pointer_source_key", "refine_route_after_result", "register_capability",
    "replay", "retrieve", "traverse", "traverse_evidence", "verify",
]
