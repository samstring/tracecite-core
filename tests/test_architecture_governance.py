from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).parents[1]
CHECKER_PATH = ROOT / "scripts" / "check_architecture.py"
SPEC = importlib.util.spec_from_file_location("tracecite_architecture_checker", CHECKER_PATH)
assert SPEC is not None and SPEC.loader is not None
checker = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = checker
SPEC.loader.exec_module(checker)


def test_repository_architecture_governance_is_clean() -> None:
    assert checker.run_checks(ROOT) == []


def test_markdown_link_fixture_reports_missing_target_and_fragment(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    target = docs / "target.md"
    target.write_text("# Existing heading\n", encoding="utf-8")
    source = docs / "source.md"
    source.write_text(
        "[missing](missing.md)\n[missing anchor](target.md#absent)\n[ok](target.md#existing-heading)\n",
        encoding="utf-8",
    )

    findings = checker.check_markdown_links(tmp_path)

    messages = [finding.message for finding in findings]
    assert any("target does not exist" in message for message in messages)
    assert any("fragment does not exist" in message for message in messages)
    assert not any("existing-heading" in message for message in messages)


def test_markdown_reference_fixture_reports_missing_definition(tmp_path: Path) -> None:
    document = tmp_path / "document.md"
    document.write_text("[missing][unknown]\n[ok][target]\n\n[target]: child.md\n", encoding="utf-8")
    (tmp_path / "child.md").write_text("child\n", encoding="utf-8")

    findings = checker.check_markdown_links(tmp_path)

    assert any("reference link definition does not exist" in finding.message for finding in findings)
    assert not any("child.md" in finding.message for finding in findings)


def test_implementation_status_fixture_allows_translated_capabilities(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    english = """# Architecture\n\n## Implementation status\n\n| Capability | Status |\n|---|---|\n| Source mechanics | Implemented |\n| Future adapter | Pending |\n"""
    chinese = """# 架构\n\n## 当前实现与目标差距\n\n| 能力 | 状态 |\n|---|---|\n| 来源机制 | 已实现 |\n| 未来适配器 | 待执行 |\n"""
    (docs / "architecture.md").write_text(english, encoding="utf-8")
    (docs / "architecture.zh-CN.md").write_text(chinese, encoding="utf-8")

    assert checker.check_implementation_status(tmp_path) == []


def test_implementation_status_fixture_reports_shape_and_category_mismatch(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "architecture.md").write_text(
        "## Implementation status\n\n| Capability | Status |\n|---|---|\n| One | Implemented |\n| Two | Pending |\n",
        encoding="utf-8",
    )
    (docs / "architecture.zh-CN.md").write_text(
        "## 当前实现与目标差距\n\n| 能力 | 状态 |\n|---|---|\n| 一个 | 已实现 |\n| 两个 | 已实现 |\n| 三个 | 待执行 |\n",
        encoding="utf-8",
    )

    findings = checker.check_implementation_status(tmp_path)

    messages = [finding.message for finding in findings]
    assert any("different capability-row counts" in message for message in messages)
    assert any("category differs" in message for message in messages)


def test_adr_fixture_reports_filename_status_and_required_sections(tmp_path: Path) -> None:
    adr_dir = tmp_path / "docs" / "adr"
    adr_dir.mkdir(parents=True)
    (adr_dir / "bad-name.md").write_text(
        "# Decision\n\n- Status: unknown\n\n## Context\n",
        encoding="utf-8",
    )

    findings = checker.check_adrs(tmp_path)

    messages = [finding.message for finding in findings]
    assert any("filename must match" in message for message in messages)
    assert any("unknown ADR status" in message for message in messages)
    assert any("section is missing" in message for message in messages)


def test_dependency_fixture_reports_core_and_runtime_domain_imports(tmp_path: Path) -> None:
    core = tmp_path / "src" / "tracecite_core"
    runtime = tmp_path / "src" / "tracecite" / "runtime"
    domain = tmp_path / "src" / "acme_domain"
    core.mkdir(parents=True)
    runtime.mkdir(parents=True)
    domain.mkdir(parents=True)
    (core / "bad.py").write_text("import tracecite.runtime\n", encoding="utf-8")
    (runtime / "bad.py").write_text("import acme_domain\n", encoding="utf-8")
    (domain / "__init__.py").write_text("\n", encoding="utf-8")

    findings = checker.check_dependency_direction(tmp_path)

    messages = [finding.message for finding in findings]
    assert any("Core must not import" in message for message in messages)
    assert any("Runtime must not import concrete domain" in message for message in messages)


def test_dependency_fixture_rejects_domain_nested_under_tracecite(tmp_path: Path) -> None:
    runtime = tmp_path / "src" / "tracecite" / "runtime"
    mobile = tmp_path / "src" / "tracecite" / "mobile"
    runtime.mkdir(parents=True)
    mobile.mkdir(parents=True)
    (runtime / "bad.py").write_text("import tracecite.mobile\n", encoding="utf-8")
    (mobile / "__init__.py").write_text("\n", encoding="utf-8")

    findings = checker.check_dependency_direction(tmp_path)

    assert any("tracecite.mobile" in finding.message for finding in findings)


def test_cli_returns_nonzero_for_failing_fixture(tmp_path: Path, capsys) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "broken.md").write_text("[missing](no-such-file.md)\n", encoding="utf-8")

    assert checker.main(["--root", str(tmp_path)]) == 1
    output = capsys.readouterr()
    assert "architecture governance failed" in output.err
    assert "target does not exist" in output.out
