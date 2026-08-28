"""Explainable evidence-progress and retrieval-readiness state.

This module deliberately tracks only mechanical evidence state. It can say
that evidence did or did not grow, that a source/scope/frontier is exhausted,
and whether caller-supplied evidence requirements are satisfied. It does not
infer causality or declare that a root cause has been found.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Literal, Mapping, Sequence


RequirementStatus = Literal["pending", "satisfied", "unknown", "blocked"]
CoverageStatus = Literal["unknown", "partial", "complete", "stale"]
ReadinessStatus = Literal["unknown", "insufficient", "partial", "ready"]
StopKind = Literal[
    "no_new_evidence",
    "source_exhausted",
    "frontier_exhausted",
    "budget_exhausted",
    "provider_unavailable",
    "source_changed",
]


@dataclass(frozen=True)
class StopReason:
    """Mechanical explanation for why evidence acquisition can stop.

    A stop reason never states that a diagnosis or root cause is correct. The
    scope and basis make the stop auditable instead of exposing a bare boolean.
    """

    kind: StopKind
    scope: Mapping[str, object] = field(default_factory=dict)
    basis: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in {
            "no_new_evidence",
            "source_exhausted",
            "frontier_exhausted",
            "budget_exhausted",
            "provider_unavailable",
            "source_changed",
        }:
            raise ValueError(f"unsupported stop kind: {self.kind!r}")
        if not isinstance(self.scope, Mapping):
            raise ValueError("stop scope must be a mapping")
        basis = tuple(
            dict.fromkeys(str(item).strip() for item in self.basis if str(item).strip())
        )
        object.__setattr__(self, "scope", dict(self.scope))
        object.__setattr__(self, "basis", basis)

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "scope": dict(self.scope),
            "basis": list(self.basis),
        }


@dataclass(frozen=True)
class EvidenceRequirement:
    """One caller-supplied evidence requirement for answering a question."""

    id: str
    status: RequirementStatus = "pending"
    evidence_ids: tuple[str, ...] = ()
    actionable: bool = True

    def __post_init__(self) -> None:
        requirement_id = str(self.id or "").strip()
        if not requirement_id or len(requirement_id) > 128:
            raise ValueError("requirement id must be 1-128 characters")
        if self.status not in {"pending", "satisfied", "unknown", "blocked"}:
            raise ValueError(f"unsupported requirement status: {self.status!r}")
        evidence_ids = tuple(
            dict.fromkeys(str(item).strip() for item in self.evidence_ids if str(item).strip())
        )
        object.__setattr__(self, "id", requirement_id)
        object.__setattr__(self, "evidence_ids", evidence_ids)
        object.__setattr__(self, "actionable", bool(self.actionable))

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "status": self.status,
            "evidence_ids": list(self.evidence_ids),
            "actionable": self.actionable,
        }


@dataclass(frozen=True)
class EvidenceGap:
    """A known evidence gap. Gaps are observations, not causal hypotheses."""

    id: str
    detail: str = ""
    actionable: bool = True

    def __post_init__(self) -> None:
        gap_id = str(self.id or "").strip()
        if not gap_id or len(gap_id) > 128:
            raise ValueError("gap id must be 1-128 characters")
        object.__setattr__(self, "id", gap_id)
        object.__setattr__(self, "detail", str(self.detail or "")[:512])
        object.__setattr__(self, "actionable", bool(self.actionable))

    def to_dict(self) -> dict[str, object]:
        return {"id": self.id, "detail": self.detail, "actionable": self.actionable}


@dataclass(frozen=True)
class EvidenceDelta:
    """Novel evidence added by one retrieval/projection operation."""

    new_evidence: int = 0
    new_entities: int = 0
    new_relations: int = 0
    new_lines: int = 0

    def __post_init__(self) -> None:
        for name in ("new_evidence", "new_entities", "new_relations", "new_lines"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")

    @property
    def grew(self) -> bool:
        return any(
            value > 0
            for value in (self.new_evidence, self.new_entities, self.new_relations, self.new_lines)
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "new_evidence": self.new_evidence,
            "new_entities": self.new_entities,
            "new_relations": self.new_relations,
            "new_lines": self.new_lines,
            "grew": self.grew,
        }


@dataclass(frozen=True)
class EvidenceReadiness:
    """Explainable mechanical progress/readiness projection.

    ``ready_for_reasoning`` remains ``None`` when no explicit requirements
    were supplied. TraceCite must not silently invent what evidence is
    sufficient to answer the caller's question.
    """

    delta: EvidenceDelta
    seen_evidence: int
    seen_lines: int
    source_complete: bool
    frontier_exhausted: bool
    scope_exhausted: bool
    retrieval_complete: bool
    consecutive_no_growth: int
    requirements_total: int
    requirements_satisfied: int
    actionable_gaps: int
    ready_for_reasoning: bool | None
    stop_recommended: bool
    stop_reason: str
    coverage_status: CoverageStatus = "unknown"
    readiness: ReadinessStatus = "unknown"
    stop: StopReason | None = None

    def to_dict(self) -> dict[str, object]:
        stop_payload: dict[str, object] = {
            "recommended": self.stop_recommended,
            "reason": self.stop_reason,
        }
        if self.stop is not None:
            stop_payload.update(self.stop.to_dict())
        return {
            "delta": self.delta.to_dict(),
            "seen_evidence": self.seen_evidence,
            "seen_lines": self.seen_lines,
            "coverage_status": self.coverage_status,
            "source_complete": self.source_complete,
            "frontier_exhausted": self.frontier_exhausted,
            "scope_exhausted": self.scope_exhausted,
            "retrieval_complete": self.retrieval_complete,
            "consecutive_no_growth": self.consecutive_no_growth,
            "requirements": {
                "total": self.requirements_total,
                "satisfied": self.requirements_satisfied,
            },
            "actionable_gaps": self.actionable_gaps,
            "readiness": self.readiness,
            "ready_for_reasoning": self.ready_for_reasoning,
            "stop": stop_payload,
        }


@dataclass
class EvidenceProgressTracker:
    """Track novelty, covered line ranges, and explainable stop state.

    The tracker does not perform semantic similarity or root-cause reasoning.
    Callers may supply explicit requirements/gaps, while evidence identity and
    versioned source ranges are handled deterministically here.
    """

    requirements: Sequence[EvidenceRequirement] = ()
    no_growth_threshold: int = 1
    _seen_evidence_ids: set[str] = field(default_factory=set, init=False, repr=False)
    _ranges: dict[str, list[tuple[int, int]]] = field(default_factory=dict, init=False, repr=False)
    _source_complete: set[str] = field(default_factory=set, init=False, repr=False)
    _frontier_exhausted: bool = field(default=False, init=False, repr=False)
    _scope_exhausted: bool = field(default=False, init=False, repr=False)
    _no_growth: int = field(default=0, init=False, repr=False)
    _gaps: dict[str, EvidenceGap] = field(default_factory=dict, init=False, repr=False)
    _requirements: dict[str, EvidenceRequirement] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        if isinstance(self.no_growth_threshold, bool) or not isinstance(self.no_growth_threshold, int):
            raise ValueError("no_growth_threshold must be a positive integer")
        if self.no_growth_threshold < 1:
            raise ValueError("no_growth_threshold must be a positive integer")
        for requirement in self.requirements:
            if not isinstance(requirement, EvidenceRequirement):
                raise ValueError("requirements must contain EvidenceRequirement values")
            if requirement.id in self._requirements:
                raise ValueError(f"duplicate requirement id: {requirement.id}")
            self._requirements[requirement.id] = requirement

    @staticmethod
    def _normalize_range(start: int, end: int) -> tuple[int, int]:
        if isinstance(start, bool) or isinstance(end, bool):
            raise ValueError("line ranges must use positive integers")
        if not isinstance(start, int) or not isinstance(end, int) or start < 1 or end < start:
            raise ValueError("line ranges must satisfy 1 <= start <= end")
        return start, end

    @staticmethod
    def _merge_ranges(ranges: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
        ordered = sorted(ranges)
        merged: list[tuple[int, int]] = []
        for start, end in ordered:
            if not merged or start > merged[-1][1] + 1:
                merged.append((start, end))
                continue
            old_start, old_end = merged[-1]
            merged[-1] = (old_start, max(old_end, end))
        return merged

    @property
    def seen_evidence_ids(self) -> frozenset[str]:
        """Return immutable mechanical identity history for projection logic."""

        return frozenset(self._seen_evidence_ids)

    def has_seen_evidence(self, evidence_id: str) -> bool:
        return str(evidence_id).strip() in self._seen_evidence_ids

    def covered_ranges(self, source: str) -> tuple[tuple[int, int], ...]:
        return tuple(self._ranges.get(str(source), ()))

    def range_is_covered(self, source: str, start: int, end: int) -> bool:
        start, end = self._normalize_range(start, end)
        return any(left <= start and right >= end for left, right in self._ranges.get(str(source), ()))

    def source_is_complete(self, source: str) -> bool:
        return str(source) in self._source_complete

    def unseen_ranges(self, source: str, start: int, end: int) -> tuple[tuple[int, int], ...]:
        """Return only portions of ``[start, end]`` not already visible."""

        start, end = self._normalize_range(start, end)
        pending: list[tuple[int, int]] = [(start, end)]
        for covered_start, covered_end in self._ranges.get(str(source), ()):
            next_pending: list[tuple[int, int]] = []
            for left, right in pending:
                if covered_end < left or covered_start > right:
                    next_pending.append((left, right))
                    continue
                if covered_start > left:
                    next_pending.append((left, covered_start - 1))
                if covered_end < right:
                    next_pending.append((covered_end + 1, right))
            pending = next_pending
            if not pending:
                break
        return tuple(pending)

    def restore(
        self,
        *,
        source: str | None = None,
        evidence_ids: Sequence[str] = (),
        line_ranges: Sequence[tuple[int, int]] = (),
        source_complete: bool = False,
        frontier_exhausted: bool | None = None,
        scope_exhausted: bool | None = None,
    ) -> None:
        """Restore persisted mechanical history without creating a new round.

        Reconstruction from InvestigationState must not increment the current
        no-growth counter merely because historical ranges are replayed.
        """

        normalized_ids = tuple(
            dict.fromkeys(str(item).strip() for item in evidence_ids if str(item).strip())
        )
        self._seen_evidence_ids.update(normalized_ids)
        if line_ranges:
            if not source:
                raise ValueError("source is required when line_ranges are supplied")
            source_key = str(source)
            normalized = [self._normalize_range(start, end) for start, end in line_ranges]
            self._ranges[source_key] = self._merge_ranges(
                [*self._ranges.get(source_key, ()), *normalized]
            )
        if source_complete:
            if not source:
                raise ValueError("source is required when source_complete=True")
            self._source_complete.add(str(source))
        if frontier_exhausted is not None:
            self._frontier_exhausted = bool(frontier_exhausted)
        if scope_exhausted is not None:
            self._scope_exhausted = bool(scope_exhausted)

    def mark_requirement(
        self,
        requirement_id: str,
        *,
        status: RequirementStatus,
        evidence_ids: Sequence[str] = (),
        actionable: bool | None = None,
    ) -> None:
        current = self._requirements.get(requirement_id)
        if current is None:
            raise KeyError(requirement_id)
        self._requirements[requirement_id] = EvidenceRequirement(
            id=current.id,
            status=status,
            evidence_ids=tuple(evidence_ids) or current.evidence_ids,
            actionable=current.actionable if actionable is None else actionable,
        )

    def set_gaps(self, gaps: Sequence[EvidenceGap]) -> None:
        values: dict[str, EvidenceGap] = {}
        for gap in gaps:
            if not isinstance(gap, EvidenceGap):
                raise ValueError("gaps must contain EvidenceGap values")
            values[gap.id] = gap
        self._gaps = values

    def observe(
        self,
        *,
        source: str | None = None,
        evidence_ids: Sequence[str] = (),
        line_ranges: Sequence[tuple[int, int]] = (),
        new_entities: int = 0,
        new_relations: int = 0,
        source_complete: bool = False,
        frontier_exhausted: bool | None = None,
        scope_exhausted: bool | None = None,
    ) -> EvidenceReadiness:
        normalized_ids = tuple(
            dict.fromkeys(str(item).strip() for item in evidence_ids if str(item).strip())
        )
        new_evidence_ids = [item for item in normalized_ids if item not in self._seen_evidence_ids]
        self._seen_evidence_ids.update(normalized_ids)

        new_lines = 0
        if line_ranges:
            if not source:
                raise ValueError("source is required when line_ranges are supplied")
            source_key = str(source)
            additions: list[tuple[int, int]] = []
            for raw_start, raw_end in line_ranges:
                start, end = self._normalize_range(raw_start, raw_end)
                unseen = self.unseen_ranges(source_key, start, end)
                new_lines += sum(right - left + 1 for left, right in unseen)
                additions.extend(unseen)
            if additions:
                self._ranges[source_key] = self._merge_ranges(
                    [*self._ranges.get(source_key, ()), *additions]
                )

        if source_complete:
            if not source:
                raise ValueError("source is required when source_complete=True")
            self._source_complete.add(str(source))
        if frontier_exhausted is not None:
            self._frontier_exhausted = bool(frontier_exhausted)
        if scope_exhausted is not None:
            self._scope_exhausted = bool(scope_exhausted)

        delta = EvidenceDelta(
            new_evidence=len(new_evidence_ids),
            new_entities=new_entities,
            new_relations=new_relations,
            new_lines=new_lines,
        )
        self._no_growth = 0 if delta.grew else self._no_growth + 1
        return self.snapshot(delta=delta, source=source)

    def snapshot(self, *, delta: EvidenceDelta | None = None, source: str | None = None) -> EvidenceReadiness:
        delta = delta or EvidenceDelta()
        source_is_complete = bool(source and str(source) in self._source_complete)
        retrieval_complete = self._frontier_exhausted or self._scope_exhausted

        requirements_total = len(self._requirements)
        requirements_satisfied = sum(
            1 for item in self._requirements.values() if item.status == "satisfied"
        )
        requirements_complete = bool(requirements_total) and requirements_satisfied == requirements_total
        actionable_gaps = sum(1 for item in self._gaps.values() if item.actionable)

        ready_for_reasoning: bool | None
        if not requirements_total:
            ready_for_reasoning = None
        else:
            ready_for_reasoning = bool(
                requirements_complete and retrieval_complete and actionable_gaps == 0
            )

        if source_is_complete:
            coverage_status: CoverageStatus = "complete"
        elif self._ranges or self._seen_evidence_ids:
            coverage_status = "partial"
        else:
            coverage_status = "unknown"

        if ready_for_reasoning is True:
            readiness: ReadinessStatus = "ready"
        elif not requirements_total:
            readiness = "unknown"
        elif requirements_satisfied or self._seen_evidence_ids:
            readiness = "partial"
        else:
            readiness = "insufficient"

        no_growth_stop = self._no_growth >= self.no_growth_threshold
        formal_stop: StopReason | None = None
        if ready_for_reasoning is True:
            stop_reason = "requirements_satisfied_and_retrieval_complete"
            stop_recommended = True
            if self._frontier_exhausted:
                formal_stop = StopReason(
                    "frontier_exhausted",
                    basis=("requirements_satisfied", "frontier_empty"),
                )
            elif self._scope_exhausted:
                formal_stop = StopReason(
                    "source_exhausted",
                    scope={"source": str(source)} if source else {},
                    basis=("requirements_satisfied", "scope_exhausted"),
                )
        elif self._frontier_exhausted and no_growth_stop:
            stop_reason = "retrieval_complete_no_growth"
            stop_recommended = True
            formal_stop = StopReason(
                "frontier_exhausted",
                basis=("frontier_empty", "no_evidence_growth"),
            )
        elif self._scope_exhausted and no_growth_stop:
            stop_reason = "retrieval_complete_no_growth"
            stop_recommended = True
            formal_stop = StopReason(
                "source_exhausted",
                scope={"source": str(source)} if source else {},
                basis=("scope_exhausted", "no_evidence_growth"),
            )
        elif no_growth_stop:
            stop_reason = "no_evidence_growth"
            stop_recommended = True
            formal_stop = StopReason(
                "no_new_evidence",
                scope={"source": str(source)} if source else {},
                basis=("no_evidence_growth",),
            )
        elif delta.grew:
            stop_reason = "evidence_grew"
            stop_recommended = False
        else:
            stop_reason = "continue_if_needed"
            stop_recommended = False

        seen_lines = sum(
            end - start + 1 for ranges in self._ranges.values() for start, end in ranges
        )
        return EvidenceReadiness(
            delta=delta,
            seen_evidence=len(self._seen_evidence_ids),
            seen_lines=seen_lines,
            source_complete=source_is_complete,
            frontier_exhausted=self._frontier_exhausted,
            scope_exhausted=self._scope_exhausted,
            retrieval_complete=retrieval_complete,
            consecutive_no_growth=self._no_growth,
            requirements_total=requirements_total,
            requirements_satisfied=requirements_satisfied,
            actionable_gaps=actionable_gaps,
            ready_for_reasoning=ready_for_reasoning,
            stop_recommended=stop_recommended,
            stop_reason=stop_reason,
            coverage_status=coverage_status,
            readiness=readiness,
            stop=formal_stop,
        )


__all__ = [
    "CoverageStatus",
    "EvidenceDelta",
    "EvidenceGap",
    "EvidenceProgressTracker",
    "EvidenceReadiness",
    "EvidenceRequirement",
    "ReadinessStatus",
    "RequirementStatus",
    "StopKind",
    "StopReason",
]
