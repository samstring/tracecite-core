from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


BENCH_DIR = Path(__file__).resolve().parents[1] / "benchmarks" / "agent-investigation"
MODULE = BENCH_DIR / "free_shell.py"


def _load_free_shell():
    sys.path.insert(0, str(BENCH_DIR))
    try:
        spec = importlib.util.spec_from_file_location("tracecite_benchmark_free_shell", MODULE)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(BENCH_DIR))


def test_free_shell_allows_normal_read_only_analysis_args() -> None:
    module = _load_free_shell()
    argv = [module._validate_arg(value) for value in ["-n", "request_id", "network.json"]]
    module._validate_program_args("rg", argv)


def test_free_shell_rejects_paths_outside_workspace() -> None:
    module = _load_free_shell()
    with pytest.raises(ValueError):
        module._validate_arg("/etc/passwd")
    with pytest.raises(ValueError):
        module._validate_arg("../../etc/passwd")
    with pytest.raises(ValueError):
        module._validate_arg("--ignore-file=/etc/passwd")


def test_free_shell_rejects_non_string_tool_arguments(tmp_path: Path) -> None:
    module = _load_free_shell()
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "crash.json").write_text("{}\n", encoding="utf-8")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    runtime = module.Runtime(
        mode="free_shell",
        input_root=inputs,
        scratch=scratch,
        context_id="",
    )
    with pytest.raises(ValueError, match="must be a string"):
        runtime._shell_exec({"program": "rg", "args": ["crash", ["crash.json"]]})


@pytest.mark.parametrize(
    ("program", "argv"),
    [
        ("rg", ["--pre=sh -c id", "."]),
        ("find", [".", "-exec", "curl", "example.com", ";"]),
        ("find", [".", "-delete"]),
        ("sort", ["--compress-program=curl", "crash.json"]),
        ("sort", ["-o", "out.txt", "crash.json"]),
        ("tail", ["-f", "crash.json"]),
        ("jq", ["-L/tmp", ".", "crash.json"]),
    ],
)
def test_free_shell_rejects_execution_write_or_escape_flags(program: str, argv: list[str]) -> None:
    module = _load_free_shell()
    checked = [module._validate_arg(value) for value in argv]
    with pytest.raises(ValueError):
        module._validate_program_args(program, checked)
