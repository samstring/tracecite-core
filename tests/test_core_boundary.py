from __future__ import annotations

import ast
import subprocess
from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_core_has_no_application_or_device_format_dependency() -> None:
    package = ROOT / "src" / "tracecite_core"
    upper_layers = (
        "tracecite.runtime",
        "tracecite.extension",
        "tracecite.integrations",
        "tracecite_agent",
        "tracecite_mobile",
        "tracecite_ci",
        "tracecite_" + "liz" + "hi",
    )
    for path in package.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(
                    alias.name != "tracecite"
                    and not alias.name.startswith(upper_layers)
                    for alias in node.names
                )
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert module != "tracecite"
                assert not module.startswith(upper_layers)
            if isinstance(node, ast.ClassDef):
                assert node.name != "DeviceLogSegmenter"
    assert not (package / "processor.py").exists()


def test_core_declares_no_runtime_dependencies() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'name = "tracecite"' in pyproject
    assert "dependencies = []" in pyproject


def test_main_layers_do_not_import_domain_extensions() -> None:
    forbidden = ("tracecite_mobile", "tracecite_ci")
    for package in (
        ROOT / "src" / "tracecite_core",
        ROOT / "src" / "tracecite" / "runtime",
        ROOT / "src" / "tracecite" / "extension",
        ROOT / "src" / "tracecite" / "integrations",
    ):
        for path in package.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    assert all(not alias.name.startswith(forbidden) for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    assert not (node.module or "").startswith(forbidden)


def test_core_gitignore_covers_local_graph_cache_and_evidence() -> None:
    rules = {
        line.strip()
        for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert {
        ".code-review-graph/",
        ".device-debug/",
        ".workbuddy/",
        ".env",
        ".env.*",
        "!.env.example",
        "*.pem",
        "*.key",
        "*.p12",
        "*.mobileprovision",
        "__pycache__/",
        ".pytest_cache/",
        ".coverage",
        "htmlcov/",
        "/.tracecite/",
        ".filtered/",
        "*.records.jsonl",
        "*.hits.jsonl",
        "filter_history.jsonl.lock",
        ".DS_Store",
        "*.ips",
        "*.crash",
        "*.xcresult",
        "*.xcarchive",
        "*.dSYM/",
        "*.sqlite",
        "*.db",
    } <= rules


def test_core_gitignore_semantics_keep_environment_template(tmp_path: Path) -> None:
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    (tmp_path / ".gitignore").write_text(gitignore, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)

    generated = (
        ".env",
        ".env.local",
        "signing.pem",
        "signing.key",
        "profile.p12",
        "Demo.mobileprovision",
        "incident.ips",
        "incident.crash",
        "Demo.xcresult/Info.plist",
        "Demo.xcarchive/Info.plist",
        "Demo.dSYM/Contents/Info.plist",
        "cache.sqlite",
        "state.db",
        ".device-debug/state.json",
        ".workbuddy/session.json",
    )
    for relative in generated:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("generated\n", encoding="utf-8")
        ignored = subprocess.run(
            ["git", "check-ignore", "--quiet", "--", relative],
            cwd=tmp_path,
            check=False,
        )
        assert ignored.returncode == 0, relative

    template = tmp_path / ".env.example"
    template.write_text("TRACECITE_SETTING=example\n", encoding="utf-8")
    visible = subprocess.run(
        ["git", "check-ignore", "--quiet", "--", ".env.example"],
        cwd=tmp_path,
        check=False,
    )
    assert visible.returncode == 1
