from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "benchmarks" / "agent-investigation" / "run_result.py"
SPEC = importlib.util.spec_from_file_location("tracecite_benchmark_run_result_chain", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _score():
    return {
        "passed": True,
        "legacy_passed": True,
        "support_aware_passed": True,
        "primary_evaluation": {},
        "quality": {},
        "context_cost": {},
    }


def _provider_error(event_id: str, parent_id: str | None = None) -> dict:
    event = {
        "id": event_id,
        "type": "message",
        "message": {
            "role": "assistant",
            "stopReason": "error",
            "rawStopReason": "429",
            "errorMessage": "HTTP 429 rate limited by provider",
            "content": [],
        },
    }
    if parent_id is not None:
        event["parentId"] = parent_id
    return event


def _success(event_id: str, parent_id: str) -> dict:
    return {
        "id": event_id,
        "parentId": parent_id,
        "type": "message",
        "message": {
            "role": "assistant",
            "stopReason": "stop",
            "content": [{"type": "text", "text": "retry eventually succeeded"}],
        },
    }


def test_chained_provider_errors_are_all_recovered_by_descendant_success() -> None:
    session = "\n".join(
        json.dumps(event)
        for event in (
            _provider_error("error-1"),
            _provider_error("error-2", "error-1"),
            _provider_error("error-3", "error-2"),
            _success("success", "error-3"),
        )
    )
    result = MODULE.build_run_result(_score(), exit_code=0, session_text=session)
    assert result["run_validity"]["valid_for_comparison"] is True
    assert result["run_validity"]["reason"] == "clean"
    assert result["run_validity"]["provider_incidents"] == {"provider_rate_limited": 3}
    assert result["run_validity"]["provider_recovered_incidents"] == {
        "provider_rate_limited": 3
    }


def test_chained_provider_errors_without_success_remain_invalid() -> None:
    session = "\n".join(
        json.dumps(event)
        for event in (
            _provider_error("error-1"),
            _provider_error("error-2", "error-1"),
        )
    )
    result = MODULE.build_run_result(_score(), exit_code=0, session_text=session)
    assert result["run_validity"]["valid_for_comparison"] is False
    assert result["run_validity"]["reason"] == "provider_rate_limited"
    assert result["run_validity"]["provider_incidents"] == {"provider_rate_limited": 2}
    assert result["run_validity"]["provider_recovered_incidents"] == {}


def test_success_on_unrelated_branch_does_not_recover_provider_error() -> None:
    session = "\n".join(
        json.dumps(event)
        for event in (
            _provider_error("error-1"),
            _success("other-success", "different-parent"),
        )
    )
    result = MODULE.build_run_result(_score(), exit_code=0, session_text=session)
    assert result["run_validity"]["valid_for_comparison"] is False
