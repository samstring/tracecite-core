from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "src/tracecite/runtime"


def main() -> None:
    runtime_path = RUNTIME / "runtime.py"
    services_path = RUNTIME / "scenario_services.py"
    original = runtime_path.read_text(encoding="utf-8")
    if "class ScenarioRuntime:" not in original or "DEFAULT_RUNTIME = ScenarioRuntime()" not in original:
        raise SystemExit("expected ScenarioRuntime implementation not found")

    services = original.replace(
        '"""Host integration seam for generic scenario orchestration.',
        '"""Internal execution services for generic scenario orchestration.',
        1,
    )
    services = services.replace(
        "class ScenarioRuntime:\n    \"\"\"Dependency-injection boundary between Runtime and a domain extension.\"\"\"",
        "class ScenarioServices:\n    \"\"\"Internal execution services assembled from domain ScenarioCapability.\"\"\"",
        1,
    )
    services = services.replace(
        "DEFAULT_RUNTIME = ScenarioRuntime()",
        "DEFAULT_SCENARIO_SERVICES = ScenarioServices()",
        1,
    )
    services_path.write_text(services, encoding="utf-8")

    runtime_path.write_text(
        '''"""Backward-compatible scenario runtime names.\n\nActive scenario execution uses :mod:`tracecite.runtime.scenario_services`.\n``ScenarioRuntime`` and ``DEFAULT_RUNTIME`` remain aliases for callers that\nhave not yet migrated; they are not the Extension v2 execution model.\n"""\n\nfrom __future__ import annotations\n\nfrom .scenario_services import *  # noqa: F401,F403\nfrom .scenario_services import DEFAULT_SCENARIO_SERVICES, ScenarioServices\n\nScenarioRuntime = ScenarioServices\nDEFAULT_RUNTIME = DEFAULT_SCENARIO_SERVICES\n''',
        encoding="utf-8",
    )

    # Runtime internals use the current service model, never compatibility names.
    for path in sorted(RUNTIME.glob("*.py")):
        if path.name in {"runtime.py", "scenario_services.py"}:
            continue
        text = path.read_text(encoding="utf-8")
        original_text = text
        text = text.replace("from .runtime import", "from .scenario_services import")
        text = text.replace("DEFAULT_RUNTIME", "DEFAULT_SCENARIO_SERVICES")
        text = text.replace("ScenarioRuntime", "ScenarioServices")
        if text != original_text:
            path.write_text(text, encoding="utf-8")

    extension_path = ROOT / "src/tracecite/extension/__init__.py"
    extension = extension_path.read_text(encoding="utf-8")
    extension = extension.replace(
        "from tracecite.runtime.runtime import DEFAULT_RUNTIME, ScenarioRuntime",
        "from tracecite.runtime.scenario_services import DEFAULT_SCENARIO_SERVICES, ScenarioServices",
        1,
    )
    block_start = extension.index("_EXTENSIONS: Dict[str, TraceCiteExtension]")
    block_end = extension.index("\ndef _install_extension", block_start)
    new_block = '''_EXTENSIONS: Dict[str, TraceCiteExtension] = {}\n_SCENARIO_SERVICES: Dict[str, ScenarioServices] = {\n    "default": DEFAULT_SCENARIO_SERVICES\n}\n_LOADED_DOMAIN_ENTRYPOINTS: Set[Tuple[str, str]] = set()\n_DOMAIN_RESULTS: Dict[Tuple[str, str], Dict[str, Any]] = {}\n\n\ndef _register_scenario_services(name: str, services: ScenarioServices) -> None:\n    key = str(name).strip().lower()\n    if not key:\n        raise ExtensionError("scenario services 名不能为空")\n    if not isinstance(services, ScenarioServices):\n        raise ExtensionError("scenario services 必须是 ScenarioServices")\n    current = _SCENARIO_SERVICES.get(key)\n    if current is not None and current is not services:\n        raise ExtensionError(f"scenario services {key!r} 已注册")\n    _SCENARIO_SERVICES[key] = services\n\n\ndef get_scenario_services(name: str = "default") -> ScenarioServices:\n    """Return the internal execution services assembled from ScenarioCapability."""\n\n    key = str(name).strip().lower() or "default"\n    try:\n        return _SCENARIO_SERVICES[key]\n    except KeyError as exc:\n        known = ", ".join(available_scenario_services())\n        raise ExtensionError(f"未知 scenario services {key!r}（可用: {known}）") from exc\n\n\ndef available_scenario_services() -> List[str]:\n    """Return installed scenario service adapters."""\n\n    return sorted(_SCENARIO_SERVICES)\n\n\ndef get_runtime(name: str = "default") -> ScenarioServices:\n    """Compatibility alias for :func:`get_scenario_services`."""\n\n    return get_scenario_services(name)\n\n\ndef available_runtimes() -> List[str]:\n    """Compatibility alias for :func:`available_scenario_services`."""\n\n    return available_scenario_services()\n\n\ndef _scenario_services(capability: ScenarioCapability) -> ScenarioServices:\n    kwargs: Dict[str, Any] = {\n        "allow_live_source": bool(capability.allow_live_source),\n        "allow_actions": bool(capability.allow_actions),\n    }\n    for field_name in (\n        "load_profile",\n        "resolve_scenario_pattern",\n        "context_files",\n        "loaded_plugins",\n        "runtime_versions",\n    ):\n        value = getattr(capability, field_name)\n        if value is not None:\n            kwargs[field_name] = value\n    return ScenarioServices(**kwargs)\n\n'''
    extension = extension[:block_start] + new_block + extension[block_end:]
    extension = extension.replace(
        "_register_runtime(capability.name, _scenario_runtime(capability))",
        "_register_scenario_services(capability.name, _scenario_services(capability))",
        1,
    )
    extension = extension.replace(
        '    "get_runtime",\n    "available_runtimes",',
        '    "get_scenario_services",\n    "available_scenario_services",\n    "get_runtime",\n    "available_runtimes",',
        1,
    )
    extension_path.write_text(extension, encoding="utf-8")

    # Production CLI uses current names; old extension helpers remain compatibility only.
    cli_path = ROOT / "src/tracecite/integrations/cli.py"
    cli = cli_path.read_text(encoding="utf-8")
    cli = cli.replace(
        "from tracecite.extension import available_runtimes, get_runtime, load_extensions",
        "from tracecite.extension import (\n    available_scenario_services,\n    get_scenario_services,\n    load_extensions,\n)",
        1,
    )
    cli = cli.replace("available_runtimes()", "available_scenario_services()")
    cli = cli.replace("get_runtime(", "get_scenario_services(")
    cli_path.write_text(cli, encoding="utf-8")

    # Guard the implementation direction in tests.
    boundary = ROOT / "tests/test_scenario_services_migration.py"
    boundary.write_text(
        '''from pathlib import Path\n\nfrom tracecite.extension import (\n    available_runtimes,\n    available_scenario_services,\n    get_runtime,\n    get_scenario_services,\n)\nfrom tracecite.runtime.runtime import DEFAULT_RUNTIME, ScenarioRuntime\nfrom tracecite.runtime.scenario_services import (\n    DEFAULT_SCENARIO_SERVICES,\n    ScenarioServices,\n)\n\n\nROOT = Path(__file__).resolve().parents[1]\n\n\ndef test_scenario_runtime_names_are_compatibility_aliases() -> None:\n    assert ScenarioRuntime is ScenarioServices\n    assert DEFAULT_RUNTIME is DEFAULT_SCENARIO_SERVICES\n\n\ndef test_extension_current_api_returns_scenario_services() -> None:\n    assert get_scenario_services() is DEFAULT_SCENARIO_SERVICES\n    assert get_runtime() is DEFAULT_SCENARIO_SERVICES\n    assert available_scenario_services() == available_runtimes()\n\n\ndef test_runtime_execution_chain_does_not_use_scenario_runtime_compatibility() -> None:\n    offenders: list[str] = []\n    runtime_dir = ROOT / "src" / "tracecite" / "runtime"\n    for path in sorted(runtime_dir.glob("*.py")):\n        if path.name == "runtime.py":\n            continue\n        text = path.read_text(encoding="utf-8")\n        if "ScenarioRuntime" in text or "DEFAULT_RUNTIME" in text or "from .runtime import" in text:\n            offenders.append(path.name)\n    assert offenders == []\n\n\ndef test_extension_installs_scenario_capability_without_scenario_runtime() -> None:\n    text = (ROOT / "src" / "tracecite" / "extension" / "__init__.py").read_text(encoding="utf-8")\n    assert "_SCENARIO_SERVICES" in text\n    assert "_scenario_services" in text\n    assert "_RUNTIMES" not in text\n    assert "_scenario_runtime" not in text\n    assert "ScenarioRuntime" not in text\n\n\ndef test_product_cli_uses_current_scenario_service_names() -> None:\n    text = (ROOT / "src" / "tracecite" / "integrations" / "cli.py").read_text(encoding="utf-8")\n    assert "get_scenario_services" in text\n    assert "available_scenario_services" in text\n    assert "get_runtime" not in text\n    assert "available_runtimes" not in text\n''',
        encoding="utf-8",
    )

    # Living architecture docs record that the transition adapter is closed.
    en = ROOT / "docs/architecture.md"
    en_text = en.read_text(encoding="utf-8")
    en_marker = "| Extension Protocol / domain capability contracts | Implemented | Public extension layer |\n"
    en_row = "| ScenarioCapability execution services | Implemented | Active chain uses internal `ScenarioServices`; `ScenarioRuntime` is compatibility-only |\n"
    if en_marker not in en_text:
        raise SystemExit("architecture.md extension status marker not found")
    if en_row not in en_text:
        en_text = en_text.replace(en_marker, en_marker + en_row, 1)
    en.write_text(en_text, encoding="utf-8")

    zh = ROOT / "docs/architecture.zh-CN.md"
    zh_text = zh.read_text(encoding="utf-8")
    zh_marker = "| Extension Protocol / Domain Capability Contract | 已实现 | Public extension layer |\n"
    zh_row = "| ScenarioCapability execution services | 已实现 | 当前执行链使用内部 `ScenarioServices`；`ScenarioRuntime` 仅为 compatibility alias |\n"
    if zh_marker not in zh_text:
        raise SystemExit("architecture.zh-CN.md extension status marker not found")
    if zh_row not in zh_text:
        zh_text = zh_text.replace(zh_marker, zh_marker + zh_row, 1)
    zh.write_text(zh_text, encoding="utf-8")

    contract = ROOT / "docs/extension-contract.md"
    contract_text = contract.read_text(encoding="utf-8")
    contract_marker = "- Scenario Capability：领域 profile / preset / scenario resolver；\n"
    contract_note = contract_marker + "\n`ScenarioCapability` 在 Runtime 内部被适配为 `ScenarioServices`；Extension 不依赖该内部类型。历史 `ScenarioRuntime` 名称仅保留兼容别名，不再位于 Extension 执行链。\n"
    if contract_marker not in contract_text:
        raise SystemExit("extension-contract Scenario Capability marker not found")
    if "历史 `ScenarioRuntime` 名称仅保留兼容别名" not in contract_text:
        contract_text = contract_text.replace(contract_marker, contract_note, 1)
    contract.write_text(contract_text, encoding="utf-8")


if __name__ == "__main__":
    main()
