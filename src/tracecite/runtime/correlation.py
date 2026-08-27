"""Deterministic correlation of domain-neutral evidence nodes."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

from tracecite.evidence import EntityRef, EvidenceRelation


class CorrelationError(ValueError):
    """Correlation inputs are malformed or internally inconsistent."""


@dataclass(frozen=True)
class EvidenceNode:
    """Small canonical fact used by correlation/reduction.

    The body may live elsewhere; ``attributes`` should contain bounded metadata
    suitable for deterministic ranking and grouping.
    """

    id: str
    kind: str
    source: str
    timestamp: str = ""
    severity: str = ""
    label: str = ""
    entities: tuple[EntityRef, ...] = ()
    evidence_uri: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        identifier = str(self.id or "").strip()
        if not identifier or len(identifier) > 256:
            raise CorrelationError("node.id must be 1-256 characters")
        kind = str(self.kind or "").strip().lower()
        source = str(self.source or "").strip()
        if not kind or not source:
            raise CorrelationError("node.kind and node.source must be non-empty")
        if not isinstance(self.attributes, Mapping):
            raise CorrelationError("node.attributes must be a mapping")
        entities = tuple(self.entities)
        if any(not isinstance(item, EntityRef) for item in entities):
            raise CorrelationError("node.entities must contain EntityRef values")
        seen: set[tuple[str, str, str]] = set()
        unique: list[EntityRef] = []
        for entity in entities:
            if entity.key not in seen:
                seen.add(entity.key)
                unique.append(entity)
        object.__setattr__(self, "id", identifier)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "severity", str(self.severity or "").strip().lower())
        object.__setattr__(self, "timestamp", str(self.timestamp or "").strip())
        object.__setattr__(self, "label", str(self.label or "")[:1024])
        object.__setattr__(self, "entities", tuple(unique))
        object.__setattr__(self, "evidence_uri", str(self.evidence_uri or "").strip())
        object.__setattr__(self, "attributes", dict(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "source": self.source,
            "entities": [item.to_dict() for item in self.entities],
        }
        for key in ("timestamp", "severity", "label", "evidence_uri"):
            value = getattr(self, key)
            if value:
                payload[key] = value
        if self.attributes:
            payload["attributes"] = dict(self.attributes)
        return payload


def _parse_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    raw = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class CorrelationGraph:
    nodes: tuple[EvidenceNode, ...]
    relations: tuple[EvidenceRelation, ...]

    def __post_init__(self) -> None:
        ids = [node.id for node in self.nodes]
        if len(ids) != len(set(ids)):
            raise CorrelationError("graph node ids must be unique")
        known = set(ids)
        for relation in self.relations:
            if relation.source_id not in known or relation.target_id not in known:
                raise CorrelationError("relation references an unknown evidence node")

    @property
    def by_id(self) -> dict[str, EvidenceNode]:
        return {node.id: node for node in self.nodes}

    def neighbors(self, node_id: str) -> tuple[str, ...]:
        result: set[str] = set()
        for relation in self.relations:
            if relation.source_id == node_id:
                result.add(relation.target_id)
            elif relation.target_id == node_id:
                result.add(relation.source_id)
        return tuple(sorted(result))

    def distance(self, sources: Iterable[str]) -> dict[str, int]:
        """Return minimum undirected hop distance from seed evidence nodes."""

        known = self.by_id
        queue: deque[tuple[str, int]] = deque()
        distances: dict[str, int] = {}
        for source in dict.fromkeys(str(item) for item in sources):
            if source in known and source not in distances:
                distances[source] = 0
                queue.append((source, 0))
        while queue:
            current, distance = queue.popleft()
            for neighbor in self.neighbors(current):
                if neighbor in distances:
                    continue
                distances[neighbor] = distance + 1
                queue.append((neighbor, distance + 1))
        return distances

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [node.to_dict() for node in self.nodes],
            "relations": [relation.to_dict() for relation in self.relations],
        }


def _canonical_relation(relation: EvidenceRelation) -> EvidenceRelation:
    """Orient undirected correlation edges by id for deterministic identity."""

    if relation.source_id <= relation.target_id:
        return relation
    return EvidenceRelation(
        source_id=relation.target_id,
        target_id=relation.source_id,
        kind=relation.kind,
        basis=relation.basis,
        confidence=relation.confidence,
        entity=relation.entity,
        attributes=relation.attributes,
    )


def correlate(
    nodes: Sequence[EvidenceNode],
    *,
    declared_relations: Sequence[EvidenceRelation] = (),
    temporal_window_seconds: float | None = None,
) -> CorrelationGraph:
    """Build a bounded deterministic graph.

    Exact entity groups are connected as a star instead of a clique. This
    preserves reachability while avoiding O(n^2) relation growth for common
    identifiers such as a long-lived session.
    """

    ordered_nodes = tuple(nodes)
    ids = [node.id for node in ordered_nodes]
    if len(ids) != len(set(ids)):
        raise CorrelationError("node ids must be unique")
    by_id = {node.id: node for node in ordered_nodes}

    relations: list[EvidenceRelation] = []
    seen: set[tuple[str, str, str, str, str]] = set()

    def add(relation: EvidenceRelation) -> None:
        if relation.source_id not in by_id or relation.target_id not in by_id:
            raise CorrelationError("declared relation references an unknown node")
        if relation.source_id == relation.target_id:
            return
        canonical = _canonical_relation(relation)
        if canonical.identity in seen:
            return
        seen.add(canonical.identity)
        relations.append(canonical)

    entity_index: dict[tuple[str, str, str], list[tuple[str, EntityRef]]] = defaultdict(list)
    for node in ordered_nodes:
        for entity in node.entities:
            entity_index[entity.key].append((node.id, entity))
    for key in sorted(entity_index):
        members = sorted(entity_index[key], key=lambda item: item[0])
        if len(members) < 2:
            continue
        anchor_id, anchor_entity = members[0]
        for member_id, _ in members[1:]:
            add(
                EvidenceRelation(
                    source_id=anchor_id,
                    target_id=member_id,
                    kind="same_entity",
                    basis="exact_entity",
                    confidence=1.0,
                    entity=anchor_entity,
                )
            )

    for relation in declared_relations:
        if not isinstance(relation, EvidenceRelation):
            raise CorrelationError("declared_relations must contain EvidenceRelation")
        add(relation)

    if temporal_window_seconds is not None:
        if isinstance(temporal_window_seconds, bool) or temporal_window_seconds <= 0:
            raise CorrelationError("temporal_window_seconds must be positive")
        timed = [
            (parsed, node.id)
            for node in ordered_nodes
            if (parsed := _parse_timestamp(node.timestamp)) is not None
        ]
        timed.sort(key=lambda item: (item[0], item[1]))
        for (left_time, left_id), (right_time, right_id) in zip(timed, timed[1:]):
            delta = (right_time - left_time).total_seconds()
            if delta <= temporal_window_seconds:
                confidence = max(0.25, 1.0 - (delta / temporal_window_seconds) * 0.5)
                add(
                    EvidenceRelation(
                        source_id=left_id,
                        target_id=right_id,
                        kind="temporal_near",
                        basis="timestamp_window",
                        confidence=round(confidence, 4),
                        attributes={"delta_seconds": delta},
                    )
                )

    relations.sort(key=lambda item: item.identity)
    return CorrelationGraph(nodes=ordered_nodes, relations=tuple(relations))


__all__ = ["CorrelationError", "CorrelationGraph", "EvidenceNode", "correlate"]
