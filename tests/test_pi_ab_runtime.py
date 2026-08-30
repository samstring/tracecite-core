from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "benchmarks" / "agent-investigation"
if str(BENCH) not in sys.path:
    sys.path.insert(0, str(BENCH))

from pi_ab_runtime import classify_answer_success, classify_arm_validity


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


def _gold() -> dict[str, object]:
    return {
        "root_cause_thresholds": {
            "dimension_recall": 0.75,
            "citation_accuracy": 1.0,
            "supported_dimension_recall": 1.0,
            "max_unsupported_claim_hits": 0,
            "max_contradiction_hits": 0,
        }
    }


def test_answer_success_is_not_blocked_by_citation_transport_diagnostics() -> None:
    score = {
        "passed": False,
        "quality": {
            "dimension_recall": 1.0,
            "supported_dimension_recall": 0.0,
            "citation": {"accuracy": 0.0},
            "unsupported_claim_hits": 0,
            "contradiction_hits": 0,
        },
    }

    assert classify_answer_success(score, _gold(), "Correct root-cause answer") is True


def test_answer_success_still_rejects_wrong_or_disallowed_answer() -> None:
    too_shallow = {
        "quality": {
            "dimension_recall": 0.5,
            "unsupported_claim_hits": 0,
            "contradiction_hits": 0,
        }
    }
    unsupported = {
        "quality": {
            "dimension_recall": 1.0,
            "unsupported_claim_hits": 1,
            "contradiction_hits": 0,
        }
    }

    assert classify_answer_success(too_shallow, _gold(), "Partial answer") is False
    assert classify_answer_success(unsupported, _gold(), "Confident but unsupported answer") is False
    assert classify_answer_success({"quality": {"dimension_recall": 1.0}}, _gold(), "") is False
