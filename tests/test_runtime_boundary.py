from __future__ import annotations

import ast
from pathlib import Path

import tracecite.runtime as runtime


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


def test_unused_requirement_primitive_is_not_advertised_as_runtime_api() -> None:
    assert "EvidenceRequirement" not in runtime.__all__
    assert "RequirementStatus" not in runtime.__all__
    assert not hasattr(runtime, "EvidenceRequirement")
    assert not hasattr(runtime, "RequirementStatus")


def test_runtime_progress_contract_has_no_epistemic_stop_semantics() -> None:
    forbidden_exports = {
        "EvidenceReadiness",
        "ReadinessStatus",
        "StopKind",
        "StopReason",
    }
    assert forbidden_exports.isdisjoint(runtime.__all__)
    for name in forbidden_exports:
        assert not hasattr(runtime, name)

    runtime_dir = ROOT / "src" / "tracecite" / "runtime"
    for path in runtime_dir.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "ready_for_reasoning" not in source, path
        assert "stop_recommended" not in source, path
        assert "from .evidence_progress import EvidenceProgressTracker, StopReason" not in source, path
        assert "result.stop_reason" not in source, path

    progress_source = (runtime_dir / "evidence_progress.py").read_text(encoding="utf-8")
    assert '"no_new_evidence",' not in progress_source.split("AcquisitionEndKind", 1)[1].split("]", 1)[0]
