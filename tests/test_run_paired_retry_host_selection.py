from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "benchmarks" / "agent-investigation"
if str(BENCH) not in sys.path:
    sys.path.insert(0, str(BENCH))

import run_paired_retry as runner


def test_default_host_remains_canonical() -> None:
    resolved = runner._resolve_host_script(ROOT, None)
    assert resolved == (ROOT / runner.DEFAULT_HOST_SCRIPT).resolve()
    assert resolved.name == "gmi_canonical_host.py"


def test_explicit_relative_host_is_resolved_from_repo_root(tmp_path: Path) -> None:
    relative = Path("benchmarks") / "custom_host.py"
    target = tmp_path / relative
    target.parent.mkdir(parents=True)
    target.write_text("print('host')\n", encoding="utf-8")

    assert runner._resolve_host_script(tmp_path, relative) == target.resolve()


def test_missing_explicit_host_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="benchmark host script not found"):
        runner._resolve_host_script(tmp_path, Path("missing_host.py"))
