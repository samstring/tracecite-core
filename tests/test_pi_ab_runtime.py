from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "benchmarks" / "agent-investigation"
if str(BENCH) not in sys.path:
    sys.path.insert(0, str(BENCH))

from pi_ab_runtime import classify_arm_validity


def test_rate_limit_is_infrastructure_invalid() -> None:
    result = classify_arm_validity(1, '429 "Rate limit exceeded"')
    assert result.valid_for_comparison is False
    assert result.infrastructure_invalid is True
    assert result.failure_kind == "provider_rate_limited"


def test_insufficient_balance_is_infrastructure_invalid() -> None:
    result = classify_arm_validity(1, '402 "Insufficient balance"')
    assert result.valid_for_comparison is False
    assert result.infrastructure_invalid is True
    assert result.failure_kind == "provider_quota_exhausted"


def test_timeout_remains_a_behavioral_outcome() -> None:
    result = classify_arm_validity(124, "")
    assert result.valid_for_comparison is True
    assert result.infrastructure_invalid is False
    assert result.failure_kind == "agent_execution_failed"


def test_success_is_valid() -> None:
    result = classify_arm_validity(0, "")
    assert result.valid_for_comparison is True
    assert result.infrastructure_invalid is False
    assert result.failure_kind is None
