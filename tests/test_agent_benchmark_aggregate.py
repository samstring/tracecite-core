from __future__ import annotations

import importlib.util
import json
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "benchmarks"
    / "agent-investigation"
    / "aggregate_scores.py"
)


def _load_aggregate():
    spec = importlib.util.spec_from_file_location("tracecite_benchmark_aggregate", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.aggregate


def test_aggregate_preserves_provider_usage_dimensions(tmp_path: Path) -> None:
    aggregate = _load_aggregate()
    paths: list[Path] = []
    for index, values in enumerate(
        [
            (1000, 100, 20, 300),
            (1200, 120, 30, 500),
            (1400, 140, 40, 700),
        ]
    ):
        input_tokens, output_tokens, reasoning_tokens, cached_tokens = values
        path = tmp_path / f"score-{index}.json"
        path.write_text(
            json.dumps(
                {
                    "case_id": "case",
                    "model": "provider/model",
                    "mode": "tracecite_context",
                    "passed": True,
                    "context_cost": {
                        "tool_calls": 2,
                        "model_calls": 3,
                        "tool_output_chars": 100,
                        "exact_duplicate_tool_output_chars": 10,
                        "estimated_tool_output_tokens_chars_div_4": 25,
                        "usage_source": "model_events",
                        "reported_input_tokens": input_tokens,
                        "reported_output_tokens": output_tokens,
                        "reported_reasoning_tokens": reasoning_tokens,
                        "reported_cached_input_tokens": cached_tokens,
                        "reported_cache_read_input_tokens": None,
                        "reported_cache_creation_input_tokens": None,
                    },
                }
            ),
            encoding="utf-8",
        )
        paths.append(path)

    result = aggregate(paths)
    row = result["groups"][0]
    assert row["runs"] == 3
    assert row["pass_rate"] == 1.0
    assert row["median_model_calls"] == 3.0
    assert row["median_reported_input_tokens"] == 1200.0
    assert row["median_reported_output_tokens"] == 120.0
    assert row["median_reported_reasoning_tokens"] == 30.0
    assert row["median_reported_cached_input_tokens"] == 500.0
    assert row["usage_sources"] == ["model_events"]
    assert row["provider_usage_runs"] == 3
    assert row["complete_io_usage_runs"] == 3
