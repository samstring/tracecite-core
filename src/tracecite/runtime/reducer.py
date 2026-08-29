"""Deterministic bounded evidence retention without causal ranking semantics."""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from typing import Any, Mapping

from tracecite.extension.evidence import EntityRef, EvidenceRelation

from .correlation import CorrelationGraph, EvidenceNode
from .grouping import GroupingResult


_SEVERITY_SCORE = {
    "fatal": 30.0,
    "critical": 26.0,
    "error": 22.0,
    "warning": 12.0,
    "warn": 12.0,
    "info": 4.0,
    "debug": 1.0,
    "trace": 0.0,
    "": 0.0,
}


@dataclass(frozen=True)
class ReductionPolicy:
    max_items: int = 12
    seed_ids: tuple[str, ...] = ()
    seed_entities: tuple[EntityRef, ...] = ()
    source_diversity_bonus: float = 8.0
    representative_bonus: float = 10.0
    max_graph_distance: int = 6

    def __post_init__(self) -> None:
        if isinstance(self.max_items, bool) or self.max_items < 1:
            raise ValueError("max_items must be at least 1")
        if isinstance(self.max_graph_distance, bool) or self.max_graph_distance < 0:
            raise ValueError("max_graph_distance must be non-negative")
        if any(not isinstance(item, EntityRef) for item in self.seed_entities):
            raise ValueError("seed_entities must contain EntityRef values")
        object.__setattr__(self, "seed_ids", tuple(dict.fromkeys(str(item) for item in self.seed_ids if str(item))))
        object.__setattr__(self, "seed_entities", tuple(self.seed_entities))


@dataclass(frozen=True)
class ScoredEvidence:
    id: str
    score: float
    reasons: tuple[str, ...]
    group_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "score": round(self.score, 3),
            "score_semantics": "retention_priority",
            "reasons": list(self.reasons),
            "group_id": self.group_id,
        }


@dataclass(frozen=True)
class ReductionResult:
    selected_ids: tuple[str, ...]
    ranked: tuple[ScoredEvidence, ...]
    candidate_count: int
    omitted_non_representative: int
    omitted_by_limit: int
    diagnostics: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "diagnostics", dict(self.diagnostics))

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected_ids": list(self.selected_ids),
            "ranked": [item.to_dict() for item in self.ranked],
            "candidate_count": self.candidate_count,
            "omitted_non_representative": self.omitted_non_representative,
            "omitted_by_limit": self.omitted_by_limit,
            "diagnostics": dict(self.diagnostics),
        }


def _seed_entity_keys(policy: ReductionPolicy, graph: CorrelationGraph) -> set[tuple[str, str, str]]:
    keys = {entity.key for entity in policy.seed_entities}
    for seed_id in policy.seed_ids:
        node = graph.by_id.get(seed_id)
        if node is not None:
            keys.update(entity.key for entity in node.entities)
    return keys


def _relation_retention_cost(relation: EvidenceRelation) -> int:
    """Map observable relation strength to mechanical retention expansion cost.

    Exact entity joins and explicit confidence-1 declarations are one hop.
    Heuristic/partial-confidence relations cost more, so temporal proximity can
    expand the retained frontier without receiving the same priority as exact
    identity. This cost is not a probability of causation.
    """

    if relation.basis == "exact_entity" or relation.confidence >= 1.0:
        return 1
    if relation.confidence >= 0.75:
        return 2
    if relation.confidence >= 0.5:
        return 3
    return 4


def _retention_distances(
    graph: CorrelationGraph,
    seed_ids: list[str],
    *,
    max_cost: int,
) -> dict[str, int]:
    """Return minimum confidence-aware path cost for retention only."""

    known = graph.by_id
    adjacency: dict[str, list[tuple[str, int]]] = {node_id: [] for node_id in known}
    for relation in graph.relations:
        cost = _relation_retention_cost(relation)
        adjacency.setdefault(relation.source_id, []).append((relation.target_id, cost))
        adjacency.setdefault(relation.target_id, []).append((relation.source_id, cost))

    distances: dict[str, int] = {}
    queue: list[tuple[int, str]] = []
    for seed_id in dict.fromkeys(seed_ids):
        if seed_id in known:
            distances[seed_id] = 0
            heapq.heappush(queue, (0, seed_id))

    while queue:
        cost, node_id = heapq.heappop(queue)
        if distances.get(node_id) != cost:
            continue
        for neighbor, edge_cost in adjacency.get(node_id, ()):
            candidate = cost + edge_cost
            if candidate > max_cost:
                continue
            previous = distances.get(neighbor)
            if previous is None or candidate < previous:
                distances[neighbor] = candidate
                heapq.heappush(queue, (candidate, neighbor))
    return distances


def _base_score(
    node: EvidenceNode,
    *,
    retention_distances: Mapping[str, int],
    seed_entity_keys: set[tuple[str, str, str]],
    representative_ids: set[str],
    group_id: str,
) -> ScoredEvidence:
    # Every component below is a retention/navigation heuristic. The number is
    # deliberately not a finding confidence or root-cause likelihood.
    score = 0.0
    reasons: list[str] = []
    distance = retention_distances.get(node.id)
    if distance is not None:
        graph_score = max(0.0, 40.0 - 8.0 * distance)
        score += graph_score
        reasons.append(f"retention_path_cost:{distance}")
    if any(entity.key in seed_entity_keys for entity in node.entities):
        score += 32.0
        reasons.append("seed_entity")
    if seed_entity_keys and any(entity.key not in seed_entity_keys for entity in node.entities):
        score += 20.0
        reasons.append("entity_diversity")
    severity_score = _SEVERITY_SCORE.get(node.severity, 0.0)
    if severity_score:
        score += severity_score
        reasons.append(f"severity_retention:{node.severity}")
    if node.id in representative_ids:
        score += 10.0
        reasons.append("group_representative")
    if node.evidence_uri:
        score += 3.0
        reasons.append("citable")
    return ScoredEvidence(id=node.id, score=score, reasons=tuple(reasons), group_id=group_id)


def reduce_evidence(
    graph: CorrelationGraph,
    grouping: GroupingResult,
    *,
    policy: ReductionPolicy | None = None,
) -> ReductionResult:
    """Select a small evidence set by retention priority, never cause likelihood."""

    resolved = policy or ReductionPolicy()
    by_id = graph.by_id
    known_ids = set(by_id)
    unknown_seeds = [item for item in resolved.seed_ids if item not in known_ids]
    seed_ids = [item for item in resolved.seed_ids if item in known_ids]
    distances = _retention_distances(
        graph,
        seed_ids,
        max_cost=resolved.max_graph_distance,
    )
    seed_entity_keys = _seed_entity_keys(resolved, graph)

    representative_ids = {
        node_id
        for group in grouping.groups
        for node_id in group.representative_ids
        if node_id in known_ids
    }
    candidate_ids = representative_ids | set(seed_ids)
    if not grouping.groups:
        candidate_ids = set(known_ids)

    scored: list[ScoredEvidence] = []
    for node_id in sorted(candidate_ids):
        node = by_id[node_id]
        group_id = str(grouping.node_to_group.get(node_id) or "")
        scored.append(
            _base_score(
                node,
                retention_distances=distances,
                seed_entity_keys=seed_entity_keys,
                representative_ids=representative_ids,
                group_id=group_id,
            )
        )
    scored.sort(key=lambda item: (-item.score, item.id))

    selected: list[str] = []
    seen_sources: set[str] = set()
    remaining = list(scored)
    while remaining and len(selected) < resolved.max_items:
        best_index = 0
        best_value: tuple[float, str] | None = None
        for index, item in enumerate(remaining):
            source = by_id[item.id].source
            adjusted = item.score + (resolved.source_diversity_bonus if source not in seen_sources else 0.0)
            value = (adjusted, item.id)
            if best_value is None or adjusted > best_value[0] or (
                adjusted == best_value[0] and item.id < best_value[1]
            ):
                best_index = index
                best_value = value
        chosen = remaining.pop(best_index)
        selected.append(chosen.id)
        seen_sources.add(by_id[chosen.id].source)

    omitted_non_representative = max(0, len(graph.nodes) - len(candidate_ids))
    omitted_by_limit = max(0, len(scored) - len(selected))
    return ReductionResult(
        selected_ids=tuple(selected),
        ranked=tuple(scored),
        candidate_count=len(scored),
        omitted_non_representative=omitted_non_representative,
        omitted_by_limit=omitted_by_limit,
        diagnostics={
            "score_semantics": "retention_priority_not_causal_likelihood",
            "relation_strength_model": "confidence_weighted_retention_path_cost",
            "unknown_seed_ids": unknown_seeds,
            "connected_candidates": sum(1 for item in scored if item.id in distances),
            "source_count": len({by_id[item.id].source for item in scored}),
        },
    )


__all__ = ["ReductionPolicy", "ReductionResult", "ScoredEvidence", "reduce_evidence"]
