from __future__ import annotations

from types import SimpleNamespace

import pytest

from tracecite.extension import (
    EXTENSION_PROTOCOL_VERSION,
    AgentCapability,
    ExtensionError,
    ExtensionManifest,
    ScenarioCapability,
    TraceCiteExtension,
    available_runtimes,
    get_extension,
    get_runtime,
    list_extensions,
    load_extensions,
    register_extension,
)
from tracecite.runtime import CapabilitySpec, execute_capability


def test_declarative_extension_installs_scenario_adapter() -> None:
    extension = TraceCiteExtension(
        manifest=ExtensionManifest(
            id="unit-domain",
            version="1.0.0",
            domain="unit",
        ),
        capabilities=(ScenarioCapability(name="unit-domain"),),
    )

    register_extension(extension)

    assert get_extension("unit-domain") is extension
    assert "unit-domain" in available_runtimes()
    assert get_runtime("unit-domain") is not None
    metadata = {item["id"]: item for item in list_extensions()}
    assert metadata["unit-domain"]["protocol_version"] == EXTENSION_PROTOCOL_VERSION
    assert metadata["unit-domain"]["capabilities"] == [
        {"kind": "runtime.scenario", "name": "unit-domain", "version": 1}
    ]


def test_declarative_extension_can_publish_agent_capability() -> None:
    spec = CapabilitySpec(
        name="unit.echo.run",
        kind="query",
        description="Return one deterministic test payload.",
        input_schema={"type": "object"},
    )

    register_extension(
        TraceCiteExtension(
            manifest=ExtensionManifest(
                id="unit-agent-capability",
                version="1.0.0",
                domain="unit",
            ),
            capabilities=(AgentCapability(spec=spec, executor=lambda args: {"args": args}),),
        )
    )

    assert execute_capability("unit.echo.run", {"value": 3}) == {
        "args": {"value": 3}
    }


class _FakeEntryPoint:
    name = "synthetic-domain-v2"
    value = "synthetic_extension:extension"
    dist = SimpleNamespace(name="synthetic-tracecite", version="2.0")

    def __init__(self, extension: TraceCiteExtension) -> None:
        self._extension = extension

    def load(self):
        return lambda: self._extension


def test_extension_loading_is_explicit_versioned_and_idempotent(monkeypatch) -> None:
    extension = TraceCiteExtension(
        manifest=ExtensionManifest(
            id="synthetic-domain-v2",
            version="2.0.0",
            domain="synthetic",
        ),
        capabilities=(ScenarioCapability(name="synthetic-domain-v2"),),
    )
    entry = _FakeEntryPoint(extension)

    def extension_entry_points(**kwargs):
        if kwargs.get("group") == "tracecite.extensions":
            return [entry]
        return []

    def core_entry_points(**kwargs):
        return []

    monkeypatch.setattr("tracecite.extension.metadata.entry_points", extension_entry_points)
    monkeypatch.setattr(
        "tracecite_core.plugin_sdk.metadata.entry_points",
        core_entry_points,
    )

    assert "synthetic-domain-v2" not in available_runtimes()
    first = load_extensions()
    second = load_extensions()

    assert first[0]["status"] == "loaded"
    assert first[0]["protocol_version"] == EXTENSION_PROTOCOL_VERSION
    assert first[0]["extension_id"] == "synthetic-domain-v2"
    assert second[0]["status"] == "already_loaded"
    assert "synthetic-domain-v2" in available_runtimes()


def test_extension_id_collision_fails_without_replace_semantics() -> None:
    first = TraceCiteExtension(
        manifest=ExtensionManifest(
            id="unit-collision",
            version="1",
            domain="unit",
        )
    )
    second = TraceCiteExtension(
        manifest=ExtensionManifest(
            id="unit-collision",
            version="2",
            domain="unit",
        )
    )
    register_extension(first)
    with pytest.raises(ExtensionError, match="已注册"):
        register_extension(second)
