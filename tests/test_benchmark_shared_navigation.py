from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOST_PATH = ROOT / "benchmarks" / "agent-investigation" / "gmi_host.py"


def _system_prompt_source() -> str:
    # Read the shared host source instead of importing it; importing the benchmark
    # host requires benchmark-only sibling modules that are not package imports.
    return HOST_PATH.read_text(encoding="utf-8")


def test_shared_benchmark_guidance_prefers_search_over_linear_range_walk() -> None:
    source = _system_prompt_source()
    assert "For large evidence files, prefer targeted semantic or text search" in source
    assert "not to\nscan the source linearly" in source
    assert "SYSTEM_PROMPT" in source
