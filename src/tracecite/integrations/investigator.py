"""Agent-facing composition of deterministic exploration and EvidencePackage."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Sequence

from tracecite.extension.evidence import EntityRef
from tracecite.extension.retrieval import EvidenceProvider
from tracecite.runtime.correlation import EvidenceNode
from tracecite.runtime.frontier import ExplorationPolicy
from tracecite.runtime.orchestrator import EvidenceInvestigation, investigate_evidence
from tracecite.runtime.reducer import ReductionPolicy

from .evidence_package import EvidencePackage, build_evidence_package


@dataclass(frozen=True)
class InvestigationPackageResult:
    investigation: EvidenceInvestigation
    package: EvidencePackage

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.investigation.status,
            "stop_reason": self.investigation.stop_reason,
            "coverage": dict(self.investigation.coverage),
            "diagnostics": dict(self.investigation.diagnostics),
            "trace": [item.to_dict() for item in self.investigation.trace],
            "package": self.package.to_dict(),
        }


def investigate(
    providers: Sequence[EvidenceProvider],
    *,
    seed_nodes: Sequence[EvidenceNode] = (),
    seed_evidence_ids: Sequence[str] = (),
    seed_entities: Sequence[EntityRef] = (),
    exploration_policy: ExplorationPolicy | None = None,
    reduction_policy: ReductionPolicy | None = None,
    temporal_window_seconds: float | None = None,
    max_tokens: int = 3000,
    recovery_limit: int = 32,
    clock: Callable[[], float] | None = None,
) -> InvestigationPackageResult:
    """Run bounded deterministic exploration and project the result for an Agent."""

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
    investigation = investigate_evidence(providers, **kwargs)
    package = build_evidence_package(
        investigation.graph,
        investigation.grouping,
        investigation.reduction,
        max_tokens=max_tokens,
        recovery_limit=recovery_limit,
    )
    return InvestigationPackageResult(investigation=investigation, package=package)


__all__ = ["InvestigationPackageResult", "investigate"]
