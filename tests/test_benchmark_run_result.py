from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "benchmarks" / "agent-investigation" / "run_result.py"
SPEC = importlib.util.spec_from_file_location("tracecite_benchmark_run_result", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _score(passed: bool = True):
    return {
        "passed": passed,
        "legacy_passed": False,
        "support_aware_passed": passed,
        "quality": {"support_level_accuracy": 1.0},
        "context_cost": {"tool_calls": 3},
    }


def test_clean_run_is_valid_independently_of_task_result() -> None:
    result = MODULE.build_run_result(_score(True), exit_code=0)
    assert result["task_result"]["passed"] is True
    assert result["run_validity"] == {
        "valid_for_comparison": True,
        "reason": "clean",
        "exit_code": 0,
        "provider_contamination": None,
        "timeout": False,
    }


def test_provider_contamination_is_not_product_loss() -> None:
    result = MODULE.build_run_result(
        _score(False),
        exit_code=1,
        stderr="HTTP 429 rate limited by provider",
    )
    assert result["task_result"]["passed"] is False
    assert result["run_validity"]["valid_for_comparison"] is False
    assert result["run_validity"]["reason"] == "provider_rate_limited"
    assert result["run_validity"]["provider_contamination"] == "provider_rate_limited"


def test_timeout_is_separate_from_provider_failure() -> None:
    result = MODULE.build_run_result(_score(False), exit_code=124, stderr="command timed out")
    assert result["run_validity"]["valid_for_comparison"] is False
    assert result["run_validity"]["reason"] == "timeout"
    assert result["run_validity"]["provider_contamination"] is None


def test_trajectory_counts_native_and_tracecite_activity() -> None:
    events = [
        {"type": "tool", "name": "tracecite_search", "output": '{"status":"ok","evidence":[{"ref":"x:L1"}],"coverage":{"new_evidence":1}}', "activity": {"category": "tracecite_evidence"}},
        {"type": "tool", "name": "grep", "output": "x", "activity": {"category": "native_search"}},
        {"type": "tool", "name": "bash", "output": "x", "activity": {"category": "opaque_shell"}},
        {"type": "tool", "name": "tracecite_search", "output": '{"status":"no_new_evidence","evidence":[],"coverage":{"new_evidence":0,"repeated_evidence":1}}', "activity": {"category": "tracecite_evidence"}},
        {"type": "final", "answer": "done"},
    ]
    summary = MODULE.trajectory_summary(events)
    assert summary["core_evidence_first_tool_index"] == 1
    assert summary["post_core_tool_calls"] == 3
    assert summary["native_search_calls"] == 1
    assert summary["opaque_shell_calls"] == 1
    assert summary["tracecite_low_novelty_ratio"] == 0.5
