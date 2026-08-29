from __future__ import annotations

import importlib.util
import json
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "benchmarks"
    / "agent-investigation"
    / "aggregate_runnable_pairs.py"
)


def _aggregate():
    spec = importlib.util.spec_from_file_location("tracecite_runnable_aggregate", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.aggregate


def _write_outcome(
    root: Path,
    *,
    case_id: str,
    mode: str,
    passed: bool | None,
    quality: float | None,
    status: str = "ok",
) -> None:
    path = root / case_id / mode / "outcome.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "case_id": case_id,
                "mode": mode,
                "scorer": "legacy",
                "run_status": status,
                "host_failure_reason": None,
                "passed": passed,
                "primary_quality_name": "concept_recall",
                "primary_quality": quality,
                "provider_retries": 0,
                "context_cost": {
                    "reported_input_tokens": 100,
                    "tool_output_chars": 50,
                    "cumulative_attempted_context_chars": 200,
                    "peak_attempted_context_chars": 100,
                },
            }
        ),
        encoding="utf-8",
    )


def test_no_harm_gate_flags_baseline_pass_tracecite_fail(tmp_path: Path) -> None:
    _write_outcome(tmp_path, case_id="regression", mode="free_shell", passed=True, quality=1.0)
    _write_outcome(tmp_path, case_id="regression", mode="tracecite", passed=False, quality=0.5)

    result = _aggregate()(tmp_path)

    assert result["no_harm_passed"] is False
    assert result["no_harm_regression_count"] == 1
    assert result["no_harm_regressions"][0]["case_id"] == "regression"


def test_no_harm_gate_allows_tracecite_pass_and_tracks_smaller_quality_drop(tmp_path: Path) -> None:
    _write_outcome(tmp_path, case_id="pass", mode="free_shell", passed=True, quality=1.0)
    _write_outcome(tmp_path, case_id="pass", mode="tracecite", passed=True, quality=0.75)

    result = _aggregate()(tmp_path)

    assert result["no_harm_passed"] is True
    assert result["no_harm_regression_count"] == 0
    assert result["quality_degradations"] == [
        {
            "case_id": "pass",
            "primary_quality_name": "concept_recall",
            "free_shell_primary_quality": 1.0,
            "tracecite_primary_quality": 0.75,
        }
    ]
