from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class ArmValidity:
    valid_for_comparison: bool
    infrastructure_invalid: bool
    failure_kind: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


_PROVIDER_FAILURES: tuple[tuple[str, tuple[re.Pattern[str], ...]], ...] = (
    (
        "provider_rate_limited",
        (
            re.compile(r"\b429\b", re.IGNORECASE),
            re.compile(r"rate\s*limit(?:ed)?", re.IGNORECASE),
        ),
    ),
    (
        "provider_quota_exhausted",
        (
            re.compile(r"\b402\b", re.IGNORECASE),
            re.compile(r"insufficient\s+balance", re.IGNORECASE),
            re.compile(r"quota\s+(?:exhausted|exceeded)", re.IGNORECASE),
        ),
    ),
    (
        "provider_unavailable",
        (
            re.compile(r"\b50[234]\b", re.IGNORECASE),
            re.compile(r"service\s+unavailable", re.IGNORECASE),
            re.compile(r"bad\s+gateway", re.IGNORECASE),
            re.compile(r"gateway\s+timeout", re.IGNORECASE),
        ),
    ),
)


def classify_arm_validity(exit_code: int | None, stderr: str) -> ArmValidity:
    """Classify whether a Pi arm is valid evidence for an A/B comparison.

    Provider capacity/quota failures are infrastructure-invalid and must never
    be scored as model/Agent failures. Other non-zero exits remain behavioral
    outcomes (for example an Agent that exhausts the benchmark timeout).
    """

    code = exit_code if isinstance(exit_code, int) else None
    text = str(stderr or "")

    if code == 0:
        return ArmValidity(True, False, None)

    for failure_kind, patterns in _PROVIDER_FAILURES:
        if any(pattern.search(text) for pattern in patterns):
            return ArmValidity(False, True, failure_kind)

    return ArmValidity(True, False, "agent_execution_failed")


def classify_answer_success(
    score: Mapping[str, Any],
    gold: Mapping[str, Any],
    answer: str,
) -> bool:
    """Return the benchmark's primary semantic answer-success verdict.

    This intentionally answers a narrower question than ``score['passed']``:
    did the Agent produce a non-empty answer that reaches the required root-
    cause dimensions without making disallowed/contradictory claims?

    Citation accuracy, evidence-support binding, and marker visibility remain
    valuable diagnostics, but they do not decide this primary A/B outcome.
    Keeping the two concepts separate prevents a transport/provenance adapter
    difference from being mislabeled as an incorrect answer.
    """

    if not str(answer or "").strip():
        return False

    quality = score.get("quality")
    if not isinstance(quality, Mapping):
        return False
    thresholds = gold.get("root_cause_thresholds")
    if not isinstance(thresholds, Mapping):
        thresholds = {}

    try:
        dimension_recall = float(quality.get("dimension_recall", 0.0))
        min_dimensions = float(thresholds.get("dimension_recall", 0.75))
        unsupported_hits = int(quality.get("unsupported_claim_hits", 0))
        contradiction_hits = int(quality.get("contradiction_hits", 0))
        max_unsupported = int(thresholds.get("max_unsupported_claim_hits", 0))
        max_contradictions = int(thresholds.get("max_contradiction_hits", 0))
    except (TypeError, ValueError):
        return False

    return all(
        (
            dimension_recall >= min_dimensions,
            unsupported_hits <= max_unsupported,
            contradiction_hits <= max_contradictions,
        )
    )
