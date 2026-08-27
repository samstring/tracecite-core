"""Bounded deterministic exploration over evidence providers.

This module is intentionally not an Agent. It moves the mechanical loop
"retrieve -> discover stable entity -> retrieve related evidence" below the
model while leaving hypotheses, causality, and final diagnosis to the Agent.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Mapping, Sequence

from tracecite.extension.evidence import EntityRef, EvidenceRelation
from tracecite.extension.retrieval import EvidenceProvider, ProviderEvidence, RetrieveRequest, RetrieveResult

from .correlation import CorrelationGraph, EvidenceNode, correlate
from .frontier import ExpansionFrontier, ExplorationPolicy, ExplorationStats, budget_stop_reason
from .grouping import GroupingResult, group_evidence
from .reducer import ReductionPolicy, ReductionResult, reduce_evidence


@dataclass(frozen=True)
class ExplorationStep:
    provider: str
    reason: str
    depth: int
    status: str
    requested_ids: tuple[str, ...] = ()
    requested_entities: tuple[str, ...] = ()
    returned_evidence: int = 0
    new_evidence: int = 0
    new_entities: int = 0
    bytes_scanned: int = 0
    diagnostics: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "diagnostics", dict(self.diagnostics))

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "reason": self.reason,
            "depth": self.depth,
            "status": self.status,
            "requested_ids": list(self.requested_ids),
            "requested_entities": list(self.requested_entities),
            "returned_evidence": self.returned_evidence,
            "new_evidence": self.new_evidence,
            "new_entities": self.new_entities,
            "bytes_scanned": self.bytes_scanned,
            "diagnostics": dict(self.diagnostics),
        }


@dataclass(frozen=True)
class EvidenceInvestigation:
    status: str
    stop_reason: str
    graph: CorrelationGraph
    grouping: GroupingResult
    reduction: ReductionResult
    coverage: Mapping[str, Any]
    trace: tuple[ExplorationStep, ...]
    diagnostics: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in {"ok", "partial", "empty"}:
            raise ValueError(f"unsupported investigation status: {self.status!r}")
        object.__setattr__(self, "coverage", dict(self.coverage))
        object.__setattr__(self, "trace", tuple(self.trace))
        object.__setattr__(self, "diagnostics", dict(self.diagnostics))

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "stop_reason": self.stop_reason,
            "coverage": dict(self.coverage),
            "trace": [item.to_dict() for item in self.trace],
            "diagnostics": dict(self.diagnostics),
            "graph": {
                "nodes": len(self.graph.nodes),
                "relations": len(self.graph.relations),
            },
            "grouping": {
                "groups": len(self.grouping.groups),
                "collapsed": self.grouping.collapsed_count,
            },
            "reduction": self.reduction.to_dict(),
        }


def _provider_name(provider: EvidenceProvider) -> str:
    name = str(getattr(provider, "name", "") or "").strip()
    if not name or len(name) > 128:
        raise ValueError("evidence provider name must be 1-128 characters")
    return name


def _as_node(value: ProviderEvidence) -> EvidenceNode:
    return EvidenceNode(
        id=value.id,
        kind=value.kind,
        source=value.source,
        timestamp=value.timestamp,
        severity=value.severity,
        label=value.label,
        entities=value.entities,
        evidence_uri=value.evidence_uri,
        attributes=value.attributes,
    )


def _bytes_scanned(result: RetrieveResult) -> int:
    for container in (result.diagnostics, result.coverage):
        value = container.get("bytes_scanned")
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return value
    return 0


def _relation_key(relation: EvidenceRelation) -> tuple[str, str, str, str, str]:
    return relation.identity


def investigate_evidence(
    providers: Sequence[EvidenceProvider],
    *,
    seed_nodes: Sequence[EvidenceNode] = (),
    seed_evidence_ids: Sequence[str] = (),
    seed_entities: Sequence[EntityRef] = (),
    exploration_policy: ExplorationPolicy | None = None,
    reduction_policy: ReductionPolicy | None = None,
    temporal_window_seconds: float | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> EvidenceInvestigation:
    """Explore related runtime evidence under deterministic hard limits.

    Every provider is attempted at most once for the initial seed request and
    once for each popped EntityRef. Newly discovered entities are queued at the
    next depth. Provider failures and budget truncation are surfaced through
    Coverage; they never become causal Findings.
    """

    policy = exploration_policy or ExplorationPolicy()
    ordered_providers = sorted(tuple(providers), key=_provider_name)
    names = [_provider_name(provider) for provider in ordered_providers]
    if len(names) != len(set(names)):
        raise ValueError("evidence provider names must be unique")

    nodes: dict[str, EvidenceNode] = {}
    sources: set[str] = set()
    pending_relations: dict[tuple[str, str, str, str, str], EvidenceRelation] = {}
    trace: list[ExplorationStep] = []
    conflicts: list[str] = []
    unsupported_entities: list[str] = []
    provider_non_ok: list[dict[str, str]] = []
    provider_errors = 0
    retrievals = 0
    bytes_scanned = 0
    no_growth_rounds = 0
    source_limit_exhausted = False
    evidence_limit_exhausted = False
    start = clock()
    frontier = ExpansionFrontier(policy)

    seed_ids = tuple(dict.fromkeys(str(item).strip() for item in seed_evidence_ids if str(item).strip()))
    seed_entity_values = tuple(seed_entities)
    if any(not isinstance(item, EntityRef) for item in seed_entity_values):
        raise ValueError("seed_entities must contain EntityRef values")
    initial_nodes = tuple(seed_nodes)
    if any(not isinstance(item, EvidenceNode) for item in initial_nodes):
        raise ValueError("seed_nodes must contain EvidenceNode values")
    if not initial_nodes and not seed_ids and not seed_entity_values:
        raise ValueError("investigation requires seed_nodes, seed_evidence_ids, or seed_entities")

    def elapsed() -> float:
        return max(0.0, float(clock() - start))

    def stats() -> ExplorationStats:
        return ExplorationStats(
            retrievals=retrievals,
            evidence=len(nodes),
            sources=len(sources),
            provider_errors=provider_errors,
            no_growth_rounds=no_growth_rounds,
            bytes_scanned=bytes_scanned,
            elapsed_seconds=elapsed(),
            details={"source_limit_exhausted": source_limit_exhausted},
        )

    def admit(node: EvidenceNode) -> bool:
        nonlocal source_limit_exhausted, evidence_limit_exhausted
        existing = nodes.get(node.id)
        if existing is not None:
            if existing.to_dict() != node.to_dict() and node.id not in conflicts:
                conflicts.append(node.id)
            return False
        if len(nodes) >= policy.max_evidence:
            evidence_limit_exhausted = True
            return False
        if node.source not in sources and len(sources) >= policy.max_sources:
            source_limit_exhausted = True
            return False
        nodes[node.id] = node
        sources.add(node.source)
        return True

    def remember_relations(relations: Sequence[EvidenceRelation]) -> None:
        for relation in relations:
            pending_relations.setdefault(_relation_key(relation), relation)

    for node in initial_nodes:
        admit(node)

    def add_frontier_from(node: EvidenceNode, *, depth: int) -> int:
        added = 0
        for entity in node.entities:
            if frontier.add(entity, depth=depth, discovered_from=node.id):
                added += 1
        return added

    for node in tuple(nodes.values()):
        add_frontier_from(node, depth=1)

    def call_provider(provider: EvidenceProvider, request: RetrieveRequest) -> tuple[RetrieveResult | None, str]:
        nonlocal provider_errors, retrievals, bytes_scanned
        name = _provider_name(provider)
        try:
            if not provider.can_handle(request):
                return None, "unsupported"
        except Exception as exc:  # provider boundary must not crash the investigation
            provider_errors += 1
            provider_non_ok.append({"provider": name, "status": "error", "phase": "can_handle"})
            trace.append(
                ExplorationStep(
                    provider=name,
                    reason=request.reason,
                    depth=request.depth,
                    status="error",
                    requested_ids=request.evidence_ids,
                    requested_entities=tuple(item.identity for item in request.entities),
                    diagnostics={"error": type(exc).__name__},
                )
            )
            return None, "error"
        retrievals += 1
        try:
            result = provider.retrieve(request)
            if not isinstance(result, RetrieveResult):
                raise TypeError("provider.retrieve must return RetrieveResult")
        except Exception as exc:
            provider_errors += 1
            provider_non_ok.append({"provider": name, "status": "error", "phase": "retrieve"})
            trace.append(
                ExplorationStep(
                    provider=name,
                    reason=request.reason,
                    depth=request.depth,
                    status="error",
                    requested_ids=request.evidence_ids,
                    requested_entities=tuple(item.identity for item in request.entities),
                    diagnostics={"error": type(exc).__name__},
                )
            )
            return None, "error"
        scanned = _bytes_scanned(result)
        bytes_scanned += scanned
        if not result.complete:
            provider_non_ok.append({"provider": name, "status": result.status, "phase": request.reason})
        remember_relations(result.relations)
        return result, "handled"

    def accept_result(provider: EvidenceProvider, request: RetrieveRequest, result: RetrieveResult) -> tuple[int, int]:
        name = _provider_name(provider)
        new_evidence = 0
        new_entities = 0
        before_frontier = frontier.pending_count
        for candidate in result.evidence:
            node = _as_node(candidate)
            if admit(node):
                new_evidence += 1
                next_depth = 1 if request.depth == 0 else request.depth + 1
                new_entities += add_frontier_from(node, depth=next_depth)
        trace.append(
            ExplorationStep(
                provider=name,
                reason=request.reason,
                depth=request.depth,
                status=result.status,
                requested_ids=request.evidence_ids,
                requested_entities=tuple(item.identity for item in request.entities),
                returned_evidence=len(result.evidence),
                new_evidence=new_evidence,
                new_entities=max(new_entities, frontier.pending_count - before_frontier),
                bytes_scanned=_bytes_scanned(result),
                diagnostics={
                    "complete": result.complete,
                    **dict(result.diagnostics),
                },
            )
        )
        return new_evidence, new_entities

    # Seed lookup is a single logical request fanned out to providers. Seed
    # nodes supplied directly do not require a provider call.
    if seed_ids or seed_entity_values:
        seed_request = RetrieveRequest(
            evidence_ids=seed_ids,
            entities=seed_entity_values,
            limit=policy.per_request_limit,
            depth=0,
            reason="seed",
        )
        handled = 0
        for provider in ordered_providers:
            hard_stop = budget_stop_reason(policy, stats())
            if hard_stop is not None:
                break
            result, state = call_provider(provider, seed_request)
            if state == "handled" and result is not None:
                handled += 1
                accept_result(provider, seed_request, result)
        if handled == 0:
            provider_non_ok.append({"provider": "*", "status": "unavailable", "phase": "seed"})

    stop_reason: str | None = budget_stop_reason(policy, stats())
    interrupted_entity = ""
    while stop_reason is None:
        item = frontier.pop()
        if item is None:
            stop_reason = "frontier_exhausted"
            break
        request = RetrieveRequest(
            entities=(item.entity,),
            limit=policy.per_request_limit,
            depth=item.depth,
            reason=f"expand:{item.entity.identity}",
            attributes={"discovered_from": item.discovered_from},
        )
        handled = 0
        round_new = 0
        for provider in ordered_providers:
            hard_stop = budget_stop_reason(policy, stats())
            if hard_stop is not None:
                stop_reason = hard_stop
                interrupted_entity = item.entity.identity
                break
            result, state = call_provider(provider, request)
            if state == "handled" and result is not None:
                handled += 1
                added, _ = accept_result(provider, request, result)
                round_new += added
        if stop_reason is not None:
            break
        frontier.mark_expanded(item.entity)
        if handled == 0:
            unsupported_entities.append(item.entity.identity)
        if round_new:
            no_growth_rounds = 0
        else:
            no_growth_rounds += 1
        stop_reason = budget_stop_reason(policy, stats())

    active_relations: list[EvidenceRelation] = []
    dangling_relations = 0
    known_ids = set(nodes)
    for relation in pending_relations.values():
        if relation.source_id in known_ids and relation.target_id in known_ids:
            active_relations.append(relation)
        else:
            dangling_relations += 1

    graph = correlate(
        tuple(nodes.values()),
        declared_relations=tuple(active_relations),
        temporal_window_seconds=temporal_window_seconds,
    )
    grouping = group_evidence(graph.nodes)

    seed_node_ids = tuple(node.id for node in initial_nodes)
    base_reduction = reduction_policy or ReductionPolicy()
    merged_seed_ids = tuple(dict.fromkeys((*base_reduction.seed_ids, *seed_node_ids, *seed_ids)))
    merged_seed_entities: list[EntityRef] = []
    seen_seed_entities: set[tuple[str, str, str]] = set()
    for entity in (*base_reduction.seed_entities, *seed_entity_values):
        if entity.key not in seen_seed_entities:
            seen_seed_entities.add(entity.key)
            merged_seed_entities.append(entity)
    resolved_reduction = replace(
        base_reduction,
        seed_ids=merged_seed_ids,
        seed_entities=tuple(merged_seed_entities),
    )
    reduction = reduce_evidence(graph, grouping, policy=resolved_reduction)

    missing_seed_ids = [item for item in seed_ids if item not in known_ids]
    observed_entity_keys = {entity.key for node in graph.nodes for entity in node.entities}
    missing_seed_entities = [
        item.identity for item in seed_entity_values if item.key not in observed_entity_keys
    ]
    frontier_diag = frontier.diagnostics()
    truncated_by_frontier = any(
        frontier_diag[key] > 0 for key in ("dropped_depth", "dropped_kind", "dropped_limit")
    )
    hard_stop = stop_reason not in {None, "frontier_exhausted"}
    incomplete = bool(
        provider_non_ok
        or conflicts
        or unsupported_entities
        or dangling_relations
        or missing_seed_ids
        or missing_seed_entities
        or source_limit_exhausted
        or evidence_limit_exhausted
        or truncated_by_frontier
        or hard_stop
    )
    complete = bool(graph.nodes) and not incomplete and stop_reason == "frontier_exhausted"
    status = "empty" if not graph.nodes else ("ok" if complete else "partial")
    final_stop = "no_evidence" if status == "empty" and stop_reason == "frontier_exhausted" else str(stop_reason or "unknown")

    coverage = {
        "complete": complete,
        "evidence": len(graph.nodes),
        "relations": len(graph.relations),
        "groups": len(grouping.groups),
        "retrievals": retrievals,
        "expanded_entities": frontier.expanded_count,
        "pending_entities": frontier.pending_count,
        "sources": len(sources),
        "bytes_scanned": bytes_scanned,
        "provider_errors": provider_errors,
        "provider_non_ok": len(provider_non_ok),
        "unsupported_entities": len(unsupported_entities),
        "dangling_relations": dangling_relations,
        "conflicting_evidence_ids": len(conflicts),
        "missing_seed_ids": len(missing_seed_ids),
        "missing_seed_entities": len(missing_seed_entities),
        "source_limit_exhausted": source_limit_exhausted,
        "evidence_limit_exhausted": evidence_limit_exhausted,
        "frontier_truncated": truncated_by_frontier,
        "elapsed_seconds": round(elapsed(), 6),
        "stop_reason": final_stop,
    }
    diagnostics = {
        "provider_non_ok": provider_non_ok,
        "unsupported_entity_ids": sorted(set(unsupported_entities)),
        "conflicting_evidence_ids": sorted(conflicts),
        "missing_seed_evidence_ids": missing_seed_ids,
        "missing_seed_entities": missing_seed_entities,
        "dangling_declared_relations": dangling_relations,
        "interrupted_entity": interrupted_entity,
        "frontier": frontier_diag,
        "policy": {
            "max_depth": policy.max_depth,
            "max_retrievals": policy.max_retrievals,
            "max_evidence": policy.max_evidence,
            "max_sources": policy.max_sources,
            "max_wall_seconds": policy.max_wall_seconds,
            "max_bytes_scanned": policy.max_bytes_scanned,
            "max_provider_errors": policy.max_provider_errors,
            "max_no_growth_rounds": policy.max_no_growth_rounds,
            "per_request_limit": policy.per_request_limit,
        },
    }
    return EvidenceInvestigation(
        status=status,
        stop_reason=final_stop,
        graph=graph,
        grouping=grouping,
        reduction=reduction,
        coverage=coverage,
        trace=tuple(trace),
        diagnostics=diagnostics,
    )


__all__ = ["EvidenceInvestigation", "ExplorationStep", "investigate_evidence"]
