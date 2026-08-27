from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_runtime_depends_on_core_but_never_domains() -> None:
    package = ROOT / "src" / "tracecite" / "runtime"
    core_import_seen = False
    for path in package.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith(("tracecite_mobile", "tracecite_ci"))
                    core_import_seen = core_import_seen or alias.name.startswith("tracecite_core")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert not module.startswith(("tracecite_mobile", "tracecite_ci"))
                core_import_seen = core_import_seen or module.startswith("tracecite_core")
    assert core_import_seen


def test_main_distribution_has_no_runtime_dependencies() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'name = "tracecite"' in pyproject
    assert "dependencies = []" in pyproject


def test_unpublished_agent_compatibility_package_is_absent() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "tracecite-agent =" not in pyproject
    assert not (ROOT / "src" / "tracecite_agent").exists()
