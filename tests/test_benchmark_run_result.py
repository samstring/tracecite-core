from __future__ import annotations

import importlib.util
import json
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
        "primary_evaluation": {
            "root_cause_accurate": passed,
            "evidence_chain_complete_and_bounded": passed,
            "evidence_boundary_respected": passed,
        },
        "quality": {"support_level_accuracy": 1.0},
        "context_cost": {
            "tool_calls": 3,
            "model_calls": 2,
            "usage_source": "model_events",
            "reported_input_tokens": 100,
            "reported_cached_input_tokens": 300,
            "reported_output_tokens": 25,
        },
    }


def test_clean_run_is_valid_independently_of_task_result() -> None:
    result = MODULE.build_run_result(_score(True), exit_code=0)
    assert result["task_result"]["passed"] is True
    assert result["task_result"]["primary_evaluation"]["root_cause_accurate"] is True
    assert result["token_usage"] == {
        "fresh_input_tokens": 100,
        "cached_input_tokens": 300,
        "fresh_plus_cached_input_tokens": 400,
        "output_tokens": 25,
        "model_calls": 2,
        "usage_source": "model_events",
    }
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


def test_provider_error_in_session_metadata_is_detected() -> None:
    session = json.dumps(
        {
            "type": "message",
            "message": {
                "role": "assistant",
                "stopReason": "error",
                "rawStopReason": "429",
                "errorMessage": "HTTP 429 rate limited by provider",
                "content": [],
            },
        }
    )
    result = MODULE.build_run_result(_score(False), exit_code=0, session_text=session)
    assert result["run_validity"]["valid_for_comparison"] is False
    assert result["run_validity"]["reason"] == "provider_rate_limited"


def test_evidence_line_numbers_and_answer_text_do_not_contaminate_validity() -> None:
    session = "\n".join(
        (
            json.dumps(
                {
                    "type": "message",
                    "message": {
                        "role": "toolResult",
                        "content": [
                            {
                                "type": "text",
                                "text": "containerd.log:429: gateway timeout is task evidence",
                            }
                        ],
                    },
                }
            ),
            json.dumps(
                {
                    "type": "message",
                    "message": {
                        "role": "assistant",
                        "stopReason": "stop",
                        "content": [
                            {
                                "type": "text",
                                "text": "The decisive evidence is line 429; the task itself mentions timeout.",
                            }
                        ],
                    },
                }
            ),
        )
    )
    transcript = json.dumps(
        {
            "type": "final",
            "answer": "Cite line 429; the investigated system reported timeout and overload.",
        }
    )
    result = MODULE.build_run_result(
        _score(True),
        exit_code=0,
        session_text=session,
        transcript_text=transcript,
    )
    assert result["run_validity"] == {
        "valid_for_comparison": True,
        "reason": "clean",
        "exit_code": 0,
        "provider_contamination": None,
        "timeout": False,
    }


def test_timeout_is_separate_from_provider_failure() -> None:
    result = MODULE.build_run_result(_score(False), exit_code=124, stderr="command timed out")
    assert result["run_validity"]["valid_for_comparison"] is False
    assert result["run_validity"]["reason"] == "timeout"
    assert result["run_validity"]["provider_contamination"] is None


def test_trajectory_counts_canonical_tracecite_activity() -> None:
    events = [
        {
            "type": "tool",
            "name": "tracecite_retrieve",
            "output": '{"operation":"retrieve","status":"ok","evidence":[{"ref":"x:L1"}],"coverage":{"new_evidence":1}}',
            "activity": {"category": "tracecite_evidence"},
        },
        {"type": "tool", "name": "find", "output": "x", "activity": {"category": "native_search"}},
        {
            "type": "tool",
            "name": "tracecite_aggregate",
            "output": '{"operation":"aggregate","status":"ok","data":{"count":2},"coverage":{"complete":true}}',
            "activity": {"category": "tracecite_evidence"},
        },
        {
            "type": "tool",
            "name": "tracecite_retrieve",
            "output": '{"operation":"retrieve","status":"no_new_evidence","evidence":[],"coverage":{"new_evidence":0,"repeated_evidence":1}}',
            "activity": {"category": "tracecite_evidence"},
        },
        {"type": "final", "answer": "done"},
    ]
    summary = MODULE.trajectory_summary(events)
    assert summary["core_evidence_first_tool_index"] == 1
    assert summary["post_core_tool_calls"] == 3
    assert summary["native_search_calls"] == 1
    assert summary["tracecite_evidence_calls"] == 3
    assert summary["tracecite_low_novelty_calls"] == 1
    assert summary["tracecite_low_novelty_ratio"] == 0.3333


def test_legacy_tracecite_aliases_remain_classified() -> None:
    events = [
        {
            "type": "tool",
            "name": "tracecite_search",
            "output": '{"status":"ok","evidence":[{"ref":"x:L1"}],"coverage":{"new_evidence":1}}',
        },
        {"type": "final", "answer": "done"},
    ]
    summary = MODULE.trajectory_summary(events)
    assert summary["tracecite_evidence_calls"] == 1
    assert summary["core_evidence_first_tool_index"] == 1
