from __future__ import annotations

import importlib.util
from pathlib import Path


RUNNER = (
    Path(__file__).resolve().parents[1]
    / "benchmarks"
    / "agent-investigation"
    / "run_host.py"
)


def _load_runner():
    spec = importlib.util.spec_from_file_location("tracecite_benchmark_run_host", RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_agent_benchmark_exposes_six_comparable_modes() -> None:
    runner = _load_runner()
    assert runner.MODES == (
        "shell_rg",
        "free_shell",
        "tracecite",
        "tracecite_context",
        "tracecite_intelligence",
        "tracecite_investigate",
    )
    assert runner.STATEFUL_MODES == frozenset(
        {"tracecite_context", "tracecite_intelligence", "tracecite_investigate"}
    )
