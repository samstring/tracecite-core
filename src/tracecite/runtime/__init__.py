"""TraceCite Evidence Runtime public contract."""

from .agent_api import (
    EvidenceRequest, ProviderTarget, QueryTarget, RangeTarget, RetrievalResult,
    RetrieveTarget, SourceTarget, CanonicalTraversalResult, traverse,
)
from .evidence_runtime_api import (
    AggregateOperation, AggregateRequest, aggregate, materialize, replay, retrieve, verify,
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
from .evidence_shell_agent import (
    DEFAULT_MAX_EVIDENCE_BYTES, DEFAULT_MAX_EVIDENCE_TOKENS,
    EvidenceShellPolicy, EvidenceShellRequest, run_evidence_shell,
)
from .evidence_compute import (
    MAX_BATCH_ANALYSES, EvidenceAnalysisSpec, EvidenceComputeRequest, run_evidence_compute,
)
from .source_versions import (
    QuestionSourceView, SourceFingerprint, SourceSegment, SourceVersionStore,
)
from .session_source_view import SessionSourceView, SessionSourceVersionStore
from .retrieval_session import (
    RetrievalOperation, RetrievalSessionState, RetrievalSessionStore,
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
    "DEFAULT_MAX_EVIDENCE_BYTES", "DEFAULT_MAX_EVIDENCE_TOKENS",
    "EvidenceAnalysisSpec", "EvidenceComputeRequest", "MAX_BATCH_ANALYSES",
    "EvidenceDelta", "EvidenceGap", "EvidenceIdentity", "EvidenceProgress",
    "EvidenceProgressTracker", "EvidenceRequest", "EvidenceRoute", "EvidenceRoutingPolicy",
    "EvidenceShellPolicy", "EvidenceShellRequest", "EvidenceTraversal", "ProviderTarget",
    "QueryTarget", "QuestionSourceView", "RangeTarget", "RetrievalOperation", "RetrievalResult",
    "RetrievalSessionState", "RetrievalSessionStore", "RetrieveTarget", "RoutingDecision",
    "SessionSourceView", "SessionSourceVersionStore", "SourceFingerprint", "SourceSegment",
    "SourceTarget", "SourceVersion", "SourceVersionKind", "SourceVersionStore",
    "TraversalFrontier", "TraversalItem", "TraversalLimits", "TraversalStats",
    "TraversalStep", "aggregate", "decide_route", "estimate_line_addressable_chars",
    "execute_capability", "file_source_version", "get_capability", "list_capabilities",
    "BudgetExhausted", "BudgetPolicy", "InvestigationError", "InvestigationState",
    "InvestigationStore", "create_investigation", "load_investigation", "materialize",
    "pointer_source_key", "refine_route_after_result", "register_capability", "replay", "retrieve",
    "run_evidence_compute", "run_evidence_shell", "traverse", "traverse_evidence", "verify",
]
