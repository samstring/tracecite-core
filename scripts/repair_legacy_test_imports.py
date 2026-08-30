from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
CANONICAL_TOP_LEVEL = {
    "AggregateOperation", "AggregateRequest", "EvidenceIdentity", "EvidenceRequest",
    "EvidenceRoute", "EvidenceRoutingPolicy", "EvidenceTraversal", "ProviderTarget",
    "QueryTarget", "RangeTarget", "RetrievalResult", "RetrievalSessionState",
    "RetrievalSessionStore", "SourceTarget", "SourceVersion", "TraversalLimits",
    "aggregate", "list_capabilities", "materialize", "replay", "retrieve", "traverse", "verify",
}


def rewrite(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"missing expected text in {path}: {old[:80]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def remove_line(path: str, line: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if line not in text:
        raise SystemExit(f"missing expected line in {path}: {line!r}")
    target.write_text(text.replace(line, "", 1), encoding="utf-8")


def migrate() -> None:
    rewrite(
        "tests/test_budget_cache.py",
        "from tracecite import (\n    BudgetExhausted,\n    BudgetPolicy,\n    InvestigationCacheStore,\n    InvestigationError,\n    InvestigationStore,\n)",
        "from tracecite.runtime import (\n    BudgetExhausted,\n    BudgetPolicy,\n    InvestigationError,\n    InvestigationStore,\n)\nfrom tracecite.runtime.investigation import InvestigationCacheStore",
    )
    rewrite(
        "tests/test_capabilities.py",
        "from tracecite import (\n    CapabilityError,\n    CapabilitySpec,\n    execute_capability,\n    get_capability,\n    list_capabilities,\n    register_capability,\n)",
        "from tracecite.runtime import (\n    CapabilityError,\n    CapabilitySpec,\n    execute_capability,\n    get_capability,\n    list_capabilities,\n    register_capability,\n)",
    )
    rewrite(
        "tests/test_investigation.py",
        "from tracecite import InvestigationError, InvestigationStore, search\nfrom tracecite.runtime import assess_test, tools",
        "from tracecite.runtime import InvestigationError, InvestigationStore, tools\nfrom tracecite.runtime.test_assessment import assess_test\nfrom tracecite.runtime.tools import search",
    )
    rewrite(
        "tests/test_investigation_compare.py",
        "from tracecite import (\n    BudgetPolicy,\n    InvestigationStore,\n    compare_investigations as public_compare_investigations,\n    timeline_investigation as public_timeline_investigation,\n)",
        "from tracecite.runtime import BudgetPolicy, InvestigationStore",
    )
    remove_line(
        "tests/test_investigation_compare.py",
        "    assert public_timeline_investigation(path)[\"kind\"] == \"timeline\"\n",
    )
    remove_line(
        "tests/test_investigation_compare.py",
        "    assert public_compare_investigations(path, path)[\"revision_delta\"] == 0\n",
    )
    rewrite(
        "tests/test_investigation_compare.py",
        "def test_public_exports_and_cli_routes_are_read_only(tmp_path: Path, capsys) -> None:",
        "def test_secondary_cli_routes_are_read_only(tmp_path: Path, capsys) -> None:",
    )
    rewrite(
        "tests/test_investigation_summary.py",
        "from tracecite.runtime import assess_test",
        "from tracecite.runtime.test_assessment import assess_test",
    )
    remove_line(
        "tests/test_investigation_summary.py",
        "from tracecite import summarize_investigation as public_summarize_investigation\n",
    )
    text = (ROOT / "tests/test_investigation_summary.py").read_text(encoding="utf-8")
    text = text.replace("public_summarize_investigation(", "summarize_investigation(")
    (ROOT / "tests/test_investigation_summary.py").write_text(text, encoding="utf-8")
    rewrite(
        "tests/test_knowledge_candidate_integration.py",
        "from tracecite import InvestigationError, InvestigationStore",
        "from tracecite.runtime import InvestigationError, InvestigationStore",
    )
    rewrite(
        "tests/test_knowledge_candidate_integration.py",
        "from tracecite.runtime import assess_test",
        "from tracecite.runtime.test_assessment import assess_test",
    )
    rewrite(
        "tests/test_runtime_schema_tools.py",
        "from tracecite import RESULT_SCHEMA_VERSION\nfrom tracecite.runtime import tools\nfrom tracecite.runtime.schema import AgentResult, ScenarioDocument",
        "from tracecite.runtime import tools\nfrom tracecite.runtime.schema import RESULT_SCHEMA_VERSION, AgentResult, ScenarioDocument",
    )
    rewrite(
        "tests/test_sample.py",
        "from tracecite import InvestigationStore, sample",
        "from tracecite.runtime import InvestigationStore\nfrom tracecite.runtime.tools import sample",
    )
    rewrite(
        "tests/test_survey.py",
        "from tracecite import survey",
        "from tracecite.runtime.tools import survey",
    )
    rewrite(
        "tests/test_evidence_primitives.py",
        '''def test_output_layout_is_public_from_tracecite_root() -> None:\n    import tracecite\n    from tracecite import DEFAULT_OUTPUT_ROOT, OutputLayout, load_output_config, write_output_config\n    from tracecite.output_layout import OutputLayout as ModuleOutputLayout\n\n    assert tracecite.OutputLayout is OutputLayout\n    assert ModuleOutputLayout is OutputLayout\n    assert DEFAULT_OUTPUT_ROOT == "~/Documents/TraceCite"\n    assert callable(load_output_config)\n    assert callable(write_output_config)\n''',
        '''def test_output_layout_remains_available_from_its_secondary_module() -> None:\n    from tracecite_core.output_layout import DEFAULT_OUTPUT_ROOT, OutputLayout as ModuleOutputLayout\n\n    assert ModuleOutputLayout is OutputLayout\n    assert DEFAULT_OUTPUT_ROOT == "~/Documents/TraceCite"\n    assert callable(load_output_config)\n    assert callable(write_output_config)\n''',
    )

    for obsolete in (
        "tests/test_evidence_investigation_loop_benchmark.py",
        "tests/test_evidence_orchestrator.py",
    ):
        path = ROOT / obsolete
        if path.exists():
            path.unlink()

    guard = TESTS / "test_public_surface_import_discipline.py"
    guard.write_text(
        '''from __future__ import annotations\n\nimport ast\nfrom pathlib import Path\n\nCANONICAL_TOP_LEVEL = ''' + repr(CANONICAL_TOP_LEVEL) + '''\n\n\ndef test_tests_do_not_reintroduce_removed_top_level_contracts() -> None:\n    root = Path(__file__).resolve().parent\n    violations = []\n    for path in sorted(root.glob("test_*.py")):\n        if path.name == Path(__file__).name:\n            continue\n        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))\n        for node in ast.walk(tree):\n            if isinstance(node, ast.ImportFrom) and node.module == "tracecite":\n                for alias in node.names:\n                    if alias.name not in CANONICAL_TOP_LEVEL:\n                        violations.append(f"{path.name}:{node.lineno}:{alias.name}")\n    assert violations == [], "removed top-level TraceCite contracts imported by tests: " + ", ".join(violations)\n''',
        encoding="utf-8",
    )


def check() -> None:
    violations: list[str] = []
    for path in sorted(TESTS.glob("test_*.py")):
        if path.name == "test_public_surface_import_discipline.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "tracecite":
                for alias in node.names:
                    if alias.name not in CANONICAL_TOP_LEVEL:
                        violations.append(f"{path.name}:{node.lineno}:{alias.name}")
    if violations:
        raise SystemExit("legacy top-level imports remain:\n" + "\n".join(violations))


if __name__ == "__main__":
    migrate()
    check()
