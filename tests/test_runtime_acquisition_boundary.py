from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "src" / "tracecite" / "runtime"


def test_canonical_runtime_does_not_depend_on_compatibility_tools() -> None:
    offenders: list[str] = []
    for path in sorted(RUNTIME.glob("*.py")):
        if path.name == "tools.py":
            continue
        text = path.read_text(encoding="utf-8")
        if "from . import tools" in text or "from .tools import" in text or "tracecite.runtime.tools" in text:
            offenders.append(path.name)
    assert offenders == []


def test_tools_module_is_only_a_compatibility_surface() -> None:
    text = (RUNTIME / "tools.py").read_text(encoding="utf-8")
    assert "Backward-compatible ``runtime.tools`` surface" in text
    assert "from .acquisition import *" in text
    assert "def search(" not in text
    assert "def expand(" not in text


def test_acquisition_module_owns_search_implementation() -> None:
    text = (RUNTIME / "acquisition.py").read_text(encoding="utf-8")
    assert "Canonical deterministic acquisition implementation" in text
    assert "def search(" in text
    assert "def probe(" in text
    assert "def expand(" in text
