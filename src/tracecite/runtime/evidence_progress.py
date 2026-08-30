"""Mechanical evidence-acquisition progress for Agent-facing Runtime results.

This module owns only facts that can be derived from retrieval state: novelty,
covered ranges, explicit source/scope/frontier exhaustion, caller-supplied
requirement bookkeeping, and evidence gaps.  It deliberately does not decide
whether evidence is sufficient for a task, whether reasoning is ready, or
whether an Agent should stop investigating.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Literal, Mapping, Sequence


RequirementStatus = Literal["pending", "satisfied", "unknown", "blocked"]
CoverageStatus = Literal["unknown", "partial", "complete", "stale"]
AcquisitionEndKind = Literal[
    "source_exhausted",
    "frontier_exhausted",
    "budget_exhausted",
    "provider_unavailable",
    "source_changed",
]


@dataclass(frozen=True)
class AcquisitionEndReason:
    """Mechanical reason a bounded evidence-acquisition operation ended.

    This is not an investigation stop recommendation.  It describes only the
    acquisition scope represented by ``kind``/``scope``/``basis``.
    """

    kind: AcquisitionEndKind
    scope: Mapping[str, object] = field(default_factory=dict)
    basis: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in {
            "source_exhausted",
            "frontier_exhausted",
            "budget_exhausted",
            "provider_unavailable",
            "source_changed",
        }:
            raise ValueError(f"unsupported acquisition end kind: {self.kind!r}")
        if not isinstance(self.scope, Mapping):
            raise ValueError("acquisition end scope must be a mapping")
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
    """One caller-supplied evidence requirement.

    Requirement state is stored mechanically.  TraceCite does not infer that a
    set of satisfied requirements makes an investigation or answer complete.
    """

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
    """Novel evidence exposed by one retrieval/materialization operation."""

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
class EvidenceProgress:
    """Explainable mechanical acquisition progress.

    The projection intentionally has no readiness/sufficiency/stop fields.
    ``acquisition_end_reason`` is present only for an explicit bounded
    acquisition end such as a frontier or source scope being exhausted.
    """

    delta: EvidenceDelta
    seen_evidence: int
    seen_lines: int
    source_complete: bool
    frontier_exhausted: bool
    scope_exhausted: bool
    consecutive_no_growth: int
    requirements_total: int
    requirements_satisfied: int
    actionable_gaps: int
    coverage_status: CoverageStatus = "unknown"
    acquisition_end_reason: AcquisitionEndReason | None = None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "delta": self.delta.to_dict(),
            "seen_evidence": self.seen_evidence,
            "seen_lines": self.seen_lines,
            "coverage_status": self.coverage_status,
            "source_complete": self.source_complete,
            "frontier_exhausted": self.frontier_exhausted,
            "scope_exhausted": self.scope_exhausted,
            "consecutive_no_growth": self.consecutive_no_growth,
            "requirements": {
                "total": self.requirements_total,
                "satisfied": self.requirements_satisfied,
            },
            "actionable_gaps": self.actionable_gaps,
        }
        if self.acquisition_end_reason is not None:
            payload["acquisition_end_reason"] = self.acquisition_end_reason.to_dict()
        return payload


@dataclass
class EvidenceProgressTracker:
    """Track mechanical novelty, covered ranges, and explicit exhaustion facts."""

    requirements: Sequence[EvidenceRequirement] = ()
    _seen_evidence_ids: set[str] = field(default_factory=set, init=False, repr=False)
    _ranges: dict[str, list[tuple[int, int]]] = field(default_factory=dict, init=False, repr=False)
    _source_complete: set[str] = field(default_factory=set, init=False, repr=False)
    _frontier_exhausted: bool = field(default=False, init=False, repr=False)
    _scope_exhausted: bool = field(default=False, init=False, repr=False)
    _no_growth: int = field(default=0, init=False, repr=False)
    _gaps: dict[str, EvidenceGap] = field(default_factory=dict, init=False, repr=False)
    _requirements: dict[str, EvidenceRequirement] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
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
    ) -> EvidenceProgress:
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

    def snapshot(
        self,
        *,
        delta: EvidenceDelta | None = None,
        source: str | None = None,
    ) -> EvidenceProgress:
        delta = delta or EvidenceDelta()
        source_is_complete = bool(source and str(source) in self._source_complete)
        requirements_total = len(self._requirements)
        requirements_satisfied = sum(
            1 for item in self._requirements.values() if item.status == "satisfied"
        )
        actionable_gaps = sum(1 for item in self._gaps.values() if item.actionable)

        if source_is_complete:
            coverage_status: CoverageStatus = "complete"
        elif self._ranges or self._seen_evidence_ids:
            coverage_status = "partial"
        else:
            coverage_status = "unknown"

        acquisition_end_reason: AcquisitionEndReason | None = None
        if self._frontier_exhausted:
            acquisition_end_reason = AcquisitionEndReason(
                "frontier_exhausted",
                basis=("mechanical_frontier_empty",),
            )
        elif self._scope_exhausted:
            acquisition_end_reason = AcquisitionEndReason(
                "source_exhausted",
                scope={"source": str(source)} if source else {},
                basis=("scope_exhausted",),
            )

        seen_lines = sum(
            end - start + 1 for ranges in self._ranges.values() for start, end in ranges
        )
        return EvidenceProgress(
            delta=delta,
            seen_evidence=len(self._seen_evidence_ids),
            seen_lines=seen_lines,
            source_complete=source_is_complete,
            frontier_exhausted=self._frontier_exhausted,
            scope_exhausted=self._scope_exhausted,
            consecutive_no_growth=self._no_growth,
            requirements_total=requirements_total,
            requirements_satisfied=requirements_satisfied,
            actionable_gaps=actionable_gaps,
            coverage_status=coverage_status,
            acquisition_end_reason=acquisition_end_reason,
        )


__all__ = [
    "AcquisitionEndKind",
    "AcquisitionEndReason",
    "CoverageStatus",
    "EvidenceDelta",
    "EvidenceGap",
    "EvidenceProgress",
    "EvidenceProgressTracker",
    "EvidenceRequirement",
    "RequirementStatus",
]
