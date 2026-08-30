"""Bounded deterministic frontier for caller-scoped Evidence traversal.

The caller selects traversal seeds and scope. This queue only executes that
mechanical traversal under hard limits; it never chooses what the Agent should
investigate next.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from typing import Any, Mapping

from tracecite.extension.evidence import EntityRef


@dataclass(frozen=True)
class TraversalLimits:
    """Hard limits for one deterministic evidence exploration."""

    max_depth: int = 3
    max_retrievals: int = 12
    max_evidence: int = 500
    max_sources: int = 8
    max_wall_seconds: float = 5.0
    max_bytes_scanned: int = 64 * 1024 * 1024
    max_provider_errors: int = 4
    max_no_growth_rounds: int = 2
    per_request_limit: int = 100
    max_frontier: int = 2048
    allowed_entity_kinds: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        integer_fields = (
            "max_depth",
            "max_retrievals",
            "max_evidence",
            "max_sources",
            "max_bytes_scanned",
            "max_provider_errors",
            "max_no_growth_rounds",
            "per_request_limit",
            "max_frontier",
        )
        for name in integer_fields:
            value = getattr(self, name)
            minimum = 0 if name in {"max_depth", "max_provider_errors", "max_no_growth_rounds"} else 1
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ValueError(f"{name} must be an integer >= {minimum}")
        if isinstance(self.max_wall_seconds, bool) or not isinstance(self.max_wall_seconds, (int, float)):
            raise ValueError("max_wall_seconds must be numeric")
        if float(self.max_wall_seconds) <= 0:
            raise ValueError("max_wall_seconds must be positive")
        kinds = tuple(dict.fromkeys(str(item).strip().lower() for item in self.allowed_entity_kinds if str(item).strip()))
        object.__setattr__(self, "max_wall_seconds", float(self.max_wall_seconds))
        object.__setattr__(self, "allowed_entity_kinds", kinds)

    def allows(self, entity: EntityRef) -> bool:
        return not self.allowed_entity_kinds or entity.kind in self.allowed_entity_kinds


@dataclass(frozen=True)
class TraversalItem:
    entity: EntityRef
    depth: int
    discovered_from: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.entity, EntityRef):
            raise ValueError("frontier entity must be EntityRef")
        if isinstance(self.depth, bool) or not isinstance(self.depth, int) or self.depth < 0:
            raise ValueError("frontier depth must be a non-negative integer")
        object.__setattr__(self, "discovered_from", str(self.discovered_from or "")[:256])


class TraversalFrontier:
    """A stable min-depth frontier with duplicate/stale-entry suppression."""

    def __init__(self, policy: TraversalLimits) -> None:
        self.policy = policy
        self._heap: list[tuple[int, str, int, TraversalItem]] = []
        self._best_depth: dict[tuple[str, str, str], int] = {}
        self._expanded: set[tuple[str, str, str]] = set()
        self._counter = 0
        self.dropped_depth = 0
        self.dropped_kind = 0
        self.dropped_limit = 0

    def add(self, entity: EntityRef, *, depth: int, discovered_from: str = "") -> bool:
        key = entity.key
        if key in self._expanded:
            return False
        current = self._best_depth.get(key)
        if current is not None and current <= depth:
            return False
        if depth > self.policy.max_depth:
            self.dropped_depth += 1
            return False
        if not self.policy.allows(entity):
            self.dropped_kind += 1
            return False
        if current is None and len(self._best_depth) >= self.policy.max_frontier:
            self.dropped_limit += 1
            return False
        self._best_depth[key] = depth
        item = TraversalItem(entity=entity, depth=depth, discovered_from=discovered_from)
        self._counter += 1
        heapq.heappush(self._heap, (depth, entity.identity, self._counter, item))
        return True

    def pop(self) -> TraversalItem | None:
        while self._heap:
            depth, _, _, item = heapq.heappop(self._heap)
            key = item.entity.key
            if key in self._expanded:
                continue
            if self._best_depth.get(key) != depth:
                continue
            return item
        return None

    def mark_expanded(self, entity: EntityRef) -> None:
        key = entity.key
        self._expanded.add(key)
        self._best_depth.pop(key, None)

    @property
    def expanded_count(self) -> int:
        return len(self._expanded)

    @property
    def pending_count(self) -> int:
        return len(self._best_depth)

    @property
    def expanded_keys(self) -> frozenset[tuple[str, str, str]]:
        return frozenset(self._expanded)

    def diagnostics(self) -> dict[str, Any]:
        return {
            "pending": self.pending_count,
            "expanded": self.expanded_count,
            "dropped_depth": self.dropped_depth,
            "dropped_kind": self.dropped_kind,
            "dropped_limit": self.dropped_limit,
        }


@dataclass(frozen=True)
class TraversalStats:
    retrievals: int = 0
    evidence: int = 0
    sources: int = 0
    provider_errors: int = 0
    no_growth_rounds: int = 0
    bytes_scanned: int = 0
    elapsed_seconds: float = 0.0
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "details", dict(self.details))


def bounded_end_reason(policy: TraversalLimits, stats: TraversalStats) -> str | None:
    """Return the first hard stop reason in stable priority order.

    ``max_sources`` is admission-based: reaching N sources does not stop the
    investigation if more evidence can still be retrieved from those sources.
    The orchestrator sets ``source_limit_exhausted`` only when a candidate from
    a new source had to be rejected.
    """

    if stats.elapsed_seconds >= policy.max_wall_seconds:
        return "max_wall_seconds"
    if stats.retrievals >= policy.max_retrievals:
        return "max_retrievals"
    if stats.evidence >= policy.max_evidence:
        return "max_evidence"
    if stats.sources >= policy.max_sources and stats.details.get("source_limit_exhausted"):
        return "max_sources"
    if stats.bytes_scanned >= policy.max_bytes_scanned:
        return "max_bytes_scanned"
    if policy.max_provider_errors and stats.provider_errors >= policy.max_provider_errors:
        return "max_provider_errors"
    if policy.max_no_growth_rounds and stats.no_growth_rounds >= policy.max_no_growth_rounds:
        return "no_growth"
    return None


__all__ = [
    "TraversalFrontier",
    "TraversalLimits",
    "TraversalStats",
    "TraversalItem",
    "bounded_end_reason",
]
