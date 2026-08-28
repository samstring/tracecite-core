"""Deterministic adaptive routing for Agent-facing evidence retrieval.

Routing is intentionally about evidence transport cost/risk, not diagnosis.
The default policy starts with the cheapest safe path and only escalates:
DIRECT -> BOUNDED -> INVESTIGATE.

A small source is not identified by a magic MB threshold.  DIRECT is allowed
only when the fully line-addressable representation is estimated to fit inside
the configured evidence/context budget.  Investigation history can then force
escalation when cardinality, source fan-out, repeated evidence, or exploration
depth grows.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Sequence


class EvidenceRoute(str, Enum):
    DIRECT = "direct"
    BOUNDED = "bounded"
    INVESTIGATE = "investigate"


_ROUTING_MODES = frozenset({"adaptive", *(item.value for item in EvidenceRoute)})


@dataclass(frozen=True)
class EvidenceRoutingPolicy:
    """Policy for adaptive evidence transport.

    ``remaining_context_tokens`` is optional because Core cannot know every
    model host's live context budget.  When supplied, DIRECT uses only a small
    fraction of that remaining budget.  Otherwise ``fallback_direct_chars`` is
    a conservative evidence-output budget, not a source-size product limit.
    """

    mode: str = "adaptive"
    remaining_context_tokens: int | None = None
    direct_context_fraction: float = 0.12
    fallback_direct_chars: int = 32_768
    max_direct_chars: int = 96_000
    bounded_max_evidence: int = 64
    bounded_max_line_chars: int = 1_024
    bounded_match_records: int = 64
    investigate_match_records: int = 256
    investigate_after_executions: int = 4
    repeated_evidence_ratio: float = 0.50
    survey_max_templates: int = 16
    survey_samples_per_template: int = 1

    def __post_init__(self) -> None:
        mode = str(self.mode or "").strip().lower()
        if mode not in _ROUTING_MODES:
            raise ValueError("routing mode must be adaptive/direct/bounded/investigate")
        object.__setattr__(self, "mode", mode)
        if self.remaining_context_tokens is not None and (
            isinstance(self.remaining_context_tokens, bool)
            or not isinstance(self.remaining_context_tokens, int)
            or self.remaining_context_tokens < 1
        ):
            raise ValueError("remaining_context_tokens must be a positive integer")
        if not (0.0 < float(self.direct_context_fraction) <= 1.0):
            raise ValueError("direct_context_fraction must be in (0, 1]")
        for name in (
            "fallback_direct_chars",
            "max_direct_chars",
            "bounded_max_evidence",
            "bounded_max_line_chars",
            "bounded_match_records",
            "investigate_match_records",
            "investigate_after_executions",
            "survey_max_templates",
            "survey_samples_per_template",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if self.max_direct_chars < self.fallback_direct_chars:
            raise ValueError("max_direct_chars must be >= fallback_direct_chars")
        if self.investigate_match_records < self.bounded_match_records:
            raise ValueError("investigate_match_records must be >= bounded_match_records")
        if not (0.0 <= float(self.repeated_evidence_ratio) <= 1.0):
            raise ValueError("repeated_evidence_ratio must be in [0, 1]")

    @property
    def direct_char_budget(self) -> int:
        if self.remaining_context_tokens is None:
            return min(self.fallback_direct_chars, self.max_direct_chars)
        estimated = int(
            math.floor(
                self.remaining_context_tokens
                * 4
                * float(self.direct_context_fraction)
            )
        )
        return max(1, min(estimated, self.max_direct_chars))


@dataclass(frozen=True)
class RoutingDecision:
    route: EvidenceRoute
    reasons: tuple[str, ...] = ()
    source_bytes: int | None = None
    estimated_direct_chars: int | None = None
    direct_char_budget: int | None = None
    previous_executions: int = 0
    source_count: int = 0
    max_match_records: int = 0
    repeated_evidence_ratio: float = 0.0
    next_route: EvidenceRoute | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "mode": self.route.value,
            "reasons": list(self.reasons),
            "previous_executions": self.previous_executions,
            "source_count": self.source_count,
            "max_match_records": self.max_match_records,
            "repeated_evidence_ratio": round(self.repeated_evidence_ratio, 4),
        }
        if self.source_bytes is not None:
            payload["source_bytes"] = self.source_bytes
        if self.estimated_direct_chars is not None:
            payload["estimated_direct_chars"] = self.estimated_direct_chars
        if self.direct_char_budget is not None:
            payload["direct_char_budget"] = self.direct_char_budget
        if self.next_route is not None:
            payload["next_mode"] = self.next_route.value
        return payload


@dataclass(frozen=True)
class _History:
    executions: int = 0
    source_count: int = 0
    max_match_records: int = 0
    repeated_evidence_ratio: float = 0.0


def _history(executions: Sequence[Mapping[str, Any]]) -> _History:
    sources: set[str] = set()
    evidence_refs: list[str] = []
    max_match_records = 0
    for execution in executions:
        params = execution.get("parameters") or {}
        if isinstance(params, Mapping):
            for key in ("input", "source"):
                value = str(params.get(key) or "").strip()
                if value:
                    sources.add(value)
        for item in execution.get("evidence") or []:
            if not isinstance(item, Mapping):
                continue
            source = str(item.get("source_path") or "").strip()
            if source:
                sources.add(source)
        refs = execution.get("evidence_refs") or []
        if isinstance(refs, Sequence) and not isinstance(refs, (str, bytes)):
            evidence_refs.extend(str(item).strip() for item in refs if str(item).strip())
        coverage = execution.get("coverage") or {}
        if isinstance(coverage, Mapping):
            value = coverage.get("match_records")
            if isinstance(value, int) and not isinstance(value, bool):
                max_match_records = max(max_match_records, value)
    repeated = 0.0
    if evidence_refs:
        repeated = max(0.0, 1.0 - (len(set(evidence_refs)) / len(evidence_refs)))
    return _History(
        executions=len(executions),
        source_count=len(sources),
        max_match_records=max_match_records,
        repeated_evidence_ratio=repeated,
    )


def estimate_line_addressable_chars(path: Path, *, stop_after: int | None = None) -> tuple[int, int]:
    """Estimate chars for ``N: text`` rendering without decoding the source.

    The byte count is an upper bound for decoded UTF-8 character count.  The
    only extra cost is the deterministic line-number prefix, which can be
    counted exactly enough from newline cardinality.  ``stop_after`` lets the
    caller abort counting once DIRECT is already impossible.
    """

    size = path.stat().st_size
    if size == 0:
        return 0, 0
    newline_count = 0
    last_byte = b""
    scanned = 0
    with path.open("rb") as handle:
        while True:
            block = handle.read(64 * 1024)
            if not block:
                break
            scanned += len(block)
            newline_count += block.count(b"\n")
            last_byte = block[-1:]
            if stop_after is not None and scanned > stop_after:
                return size, size + stop_after + 1
    lines = newline_count + (0 if last_byte == b"\n" else 1)
    prefix_chars = lines * (len(str(max(1, lines))) + 2)
    return size, size + prefix_chars


def decide_route(
    *,
    target_kind: str,
    source: Path | None,
    policy: EvidenceRoutingPolicy,
    executions: Sequence[Mapping[str, Any]] = (),
) -> RoutingDecision:
    """Choose the current route from cheap metadata and persisted history."""

    hist = _history(executions)
    direct_budget = policy.direct_char_budget
    forced = policy.mode if policy.mode != "adaptive" else ""
    if forced:
        return RoutingDecision(
            route=EvidenceRoute(forced),
            reasons=("policy_override",),
            direct_char_budget=direct_budget,
            previous_executions=hist.executions,
            source_count=hist.source_count,
            max_match_records=hist.max_match_records,
            repeated_evidence_ratio=hist.repeated_evidence_ratio,
        )

    if target_kind == "provider":
        return RoutingDecision(
            route=EvidenceRoute.INVESTIGATE,
            reasons=("provider_identity_expansion",),
            direct_char_budget=direct_budget,
            previous_executions=hist.executions,
            source_count=hist.source_count,
            max_match_records=hist.max_match_records,
            repeated_evidence_ratio=hist.repeated_evidence_ratio,
        )
    if target_kind == "range":
        return RoutingDecision(
            route=EvidenceRoute.DIRECT,
            reasons=("explicit_bounded_range",),
            direct_char_budget=direct_budget,
            previous_executions=hist.executions,
            source_count=hist.source_count,
            max_match_records=hist.max_match_records,
            repeated_evidence_ratio=hist.repeated_evidence_ratio,
        )

    escalation: list[str] = []
    if hist.source_count > 1:
        escalation.append("multiple_sources")
    if hist.max_match_records >= policy.investigate_match_records:
        escalation.append("high_match_cardinality")
    if hist.executions >= policy.investigate_after_executions:
        escalation.append("exploration_depth")
    if (
        hist.executions >= 2
        and hist.repeated_evidence_ratio >= policy.repeated_evidence_ratio
    ):
        escalation.append("repeated_evidence")
    if escalation:
        return RoutingDecision(
            route=EvidenceRoute.INVESTIGATE,
            reasons=tuple(escalation),
            direct_char_budget=direct_budget,
            previous_executions=hist.executions,
            source_count=hist.source_count,
            max_match_records=hist.max_match_records,
            repeated_evidence_ratio=hist.repeated_evidence_ratio,
        )

    source_bytes: int | None = None
    direct_chars: int | None = None
    direct_safe = False
    if source is not None and source.is_file():
        try:
            source_bytes = source.stat().st_size
            # Do not count line prefixes for an obviously over-budget source.
            if source_bytes <= direct_budget:
                source_bytes, direct_chars = estimate_line_addressable_chars(
                    source,
                    stop_after=direct_budget,
                )
                direct_safe = direct_chars <= direct_budget
        except OSError:
            direct_safe = False

    # DIRECT is deliberately a first-step optimisation.  Once an investigation
    # has begun, subsequent retrievals become bounded even for a small file.
    if direct_safe and hist.executions == 0:
        return RoutingDecision(
            route=EvidenceRoute.DIRECT,
            reasons=("line_addressable_source_fits_budget",),
            source_bytes=source_bytes,
            estimated_direct_chars=direct_chars,
            direct_char_budget=direct_budget,
            previous_executions=hist.executions,
            source_count=hist.source_count,
            max_match_records=hist.max_match_records,
            repeated_evidence_ratio=hist.repeated_evidence_ratio,
        )

    reasons: list[str] = []
    if hist.max_match_records >= policy.bounded_match_records:
        reasons.append("match_cardinality_requires_bounds")
    if hist.executions:
        reasons.append("investigation_already_started")
    if source is None or not source.is_file():
        reasons.append("source_collection_or_provider")
    elif not direct_safe:
        reasons.append("direct_output_exceeds_budget")
    if not reasons:
        reasons.append("bounded_default")
    return RoutingDecision(
        route=EvidenceRoute.BOUNDED,
        reasons=tuple(reasons),
        source_bytes=source_bytes,
        estimated_direct_chars=direct_chars,
        direct_char_budget=direct_budget,
        previous_executions=hist.executions,
        source_count=hist.source_count,
        max_match_records=hist.max_match_records,
        repeated_evidence_ratio=hist.repeated_evidence_ratio,
    )


def refine_route_after_result(
    decision: RoutingDecision,
    result: Mapping[str, Any],
    *,
    policy: EvidenceRoutingPolicy,
) -> RoutingDecision:
    """Expose a monotonic next-route hint from actual result cardinality."""

    coverage = result.get("coverage") or {}
    if not isinstance(coverage, Mapping):
        return decision
    match_records = coverage.get("match_records")
    if not isinstance(match_records, int) or isinstance(match_records, bool):
        match_records = 0
    truncated = bool(coverage.get("evidence_truncated"))
    next_route: EvidenceRoute | None = None
    if match_records >= policy.investigate_match_records:
        next_route = EvidenceRoute.INVESTIGATE
    elif decision.route == EvidenceRoute.DIRECT and (
        truncated or match_records >= policy.bounded_match_records
    ):
        next_route = EvidenceRoute.BOUNDED
    elif decision.route == EvidenceRoute.BOUNDED and truncated:
        next_route = EvidenceRoute.INVESTIGATE
    if next_route is None or next_route == decision.route:
        return decision
    return RoutingDecision(
        route=decision.route,
        reasons=decision.reasons,
        source_bytes=decision.source_bytes,
        estimated_direct_chars=decision.estimated_direct_chars,
        direct_char_budget=decision.direct_char_budget,
        previous_executions=decision.previous_executions,
        source_count=decision.source_count,
        max_match_records=max(decision.max_match_records, match_records),
        repeated_evidence_ratio=decision.repeated_evidence_ratio,
        next_route=next_route,
    )


__all__ = [
    "EvidenceRoute",
    "EvidenceRoutingPolicy",
    "RoutingDecision",
    "decide_route",
    "estimate_line_addressable_chars",
    "refine_route_after_result",
]
