from __future__ import annotations

import re
from dataclasses import asdict, dataclass


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
