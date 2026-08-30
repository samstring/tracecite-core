"""Evidence-aware evaluation primitives used by TraceCite benchmarks.

Evaluation is intentionally outside the Evidence Runtime.  It grades an Agent's
answer against benchmark truth, including whether direct evidence, qualified
inference, and evidence boundaries are represented correctly. Provider failures
are recorded independently from task quality so infrastructure contamination
does not become a product loss.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping


SupportLevel = Literal["supported", "inference_supported", "unsupported_from_log"]


@dataclass(frozen=True)
class DimensionTruth:
    id: str
    support_level: SupportLevel
    known_external_truth: str = ""

    def __post_init__(self) -> None:
        identifier = str(self.id or "").strip()
        if not identifier:
            raise ValueError("dimension truth requires id")
        if self.support_level not in {
            "supported",
            "inference_supported",
            "unsupported_from_log",
        }:
            raise ValueError("unsupported support level")
        object.__setattr__(self, "id", identifier)
        object.__setattr__(self, "known_external_truth", str(self.known_external_truth or ""))


@dataclass(frozen=True)
class TaskResult:
    completed: bool
    passed: bool
    metrics: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "completed", bool(self.completed))
        object.__setattr__(self, "passed", bool(self.passed))
        object.__setattr__(self, "metrics", dict(self.metrics))


@dataclass(frozen=True)
class RunValidity:
    provider_clean: bool
    valid_for_product_comparison: bool
    invalid_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        reasons = tuple(dict.fromkeys(str(item).strip() for item in self.invalid_reasons if str(item).strip()))
        object.__setattr__(self, "provider_clean", bool(self.provider_clean))
        object.__setattr__(self, "valid_for_product_comparison", bool(self.valid_for_product_comparison))
        object.__setattr__(self, "invalid_reasons", reasons)

    @classmethod
    def from_provider_signals(cls, text: str) -> "RunValidity":
        lowered = str(text or "").lower()
        signals = {
            "provider_rate_limit": ("429", "rate limit"),
            "provider_quota": ("402", "quota"),
            "provider_unavailable": ("overloaded", "service temporarily unavailable", "503", "502", "504"),
        }
        reasons = [name for name, needles in signals.items() if any(needle in lowered for needle in needles)]
        clean = not reasons
        return cls(
            provider_clean=clean,
            valid_for_product_comparison=clean,
            invalid_reasons=tuple(reasons),
        )


@dataclass(frozen=True)
class EvaluationResult:
    task_result: TaskResult
    run_validity: RunValidity

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_result": {
                "completed": self.task_result.completed,
                "passed": self.task_result.passed,
                "metrics": dict(self.task_result.metrics),
            },
            "run_validity": {
                "provider_clean": self.run_validity.provider_clean,
                "valid_for_product_comparison": self.run_validity.valid_for_product_comparison,
                "invalid_reasons": list(self.run_validity.invalid_reasons),
            },
        }


__all__ = [
    "DimensionTruth",
    "EvaluationResult",
    "RunValidity",
    "SupportLevel",
    "TaskResult",
]
