from pathlib import Path

from tracecite.extension import (
    available_runtimes,
    available_scenario_services,
    get_runtime,
    get_scenario_services,
)
from tracecite.runtime.runtime import DEFAULT_RUNTIME, ScenarioRuntime
from tracecite.runtime.scenario_services import (
    DEFAULT_SCENARIO_SERVICES,
    ScenarioServices,
)


ROOT = Path(__file__).resolve().parents[1]


def test_scenario_runtime_names_are_compatibility_aliases() -> None:
    assert ScenarioRuntime is ScenarioServices
    assert DEFAULT_RUNTIME is DEFAULT_SCENARIO_SERVICES


def test_extension_current_api_returns_scenario_services() -> None:
    assert get_scenario_services() is DEFAULT_SCENARIO_SERVICES
    assert get_runtime() is DEFAULT_SCENARIO_SERVICES
    assert available_scenario_services() == available_runtimes()


def test_runtime_execution_chain_does_not_use_scenario_runtime_compatibility() -> None:
    offenders: list[str] = []
    runtime_dir = ROOT / "src" / "tracecite" / "runtime"
    for path in sorted(runtime_dir.glob("*.py")):
        if path.name == "runtime.py":
            continue
        text = path.read_text(encoding="utf-8")
        if "ScenarioRuntime" in text or "DEFAULT_RUNTIME" in text or "from .runtime import" in text:
            offenders.append(path.name)
    assert offenders == []


def test_extension_installs_scenario_capability_without_scenario_runtime() -> None:
    text = (ROOT / "src" / "tracecite" / "extension" / "__init__.py").read_text(encoding="utf-8")
    assert "_SCENARIO_SERVICES" in text
    assert "_scenario_services" in text
    assert "_RUNTIMES" not in text
    assert "_scenario_runtime" not in text
    assert "ScenarioRuntime" not in text


def test_product_cli_uses_current_scenario_service_names() -> None:
    text = (ROOT / "src" / "tracecite" / "integrations" / "cli.py").read_text(encoding="utf-8")
    assert "get_scenario_services" in text
    assert "available_scenario_services" in text
    assert "get_runtime" not in text
    assert "available_runtimes" not in text
