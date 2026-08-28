from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


BENCH_DIR = Path(__file__).resolve().parents[1] / "benchmarks" / "agent-investigation"
RUNNER = BENCH_DIR / "run_host.py"
RAW_HOST_V2 = BENCH_DIR / "gmi_raw_host_v2.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location("tracecite_benchmark_run_host", RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_raw_host_v2():
    sys.path.insert(0, str(BENCH_DIR))
    try:
        spec = importlib.util.spec_from_file_location("tracecite_benchmark_gmi_raw_host_v2", RAW_HOST_V2)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(BENCH_DIR))


def _restore_raw_host_globals(module) -> None:
    module.base.BenchmarkToolRuntime = module.InspectFirstRuntime.__mro__[1]
    module.base._post_chat = module._ORIGINAL_POST_CHAT
    module.common._tools_for_mode = module._ORIGINAL_TOOLS_FOR_MODE


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


def test_complete_inspection_blocks_redundant_searches() -> None:
    module = _load_raw_host_v2()
    try:
        runtime = object.__new__(module.InspectFirstRuntime)
        runtime._fully_inspected = {"evidence.txt": (37, 37)}

        output = runtime._tracecite_search(
            {"file": "evidence.txt", "query": "different synonym", "regex": False}
        )

        assert output.startswith("NO_NEW_EVIDENCE:")
        assert "37/37 evidence records returned" in output
        assert "reason from them" in output
    finally:
        _restore_raw_host_globals(module)


def test_complete_coverage_marker_is_detected() -> None:
    module = _load_raw_host_v2()
    try:
        match = module._COVERAGE_RE.search(
            "@COV evidence_available=37 evidence_returned=37 "
            "evidence_truncated=False match_lines=37"
        )
        assert match is not None
        assert match.groups() == ("37", "37", "False")
    finally:
        _restore_raw_host_globals(module)
