from __future__ import annotations

from types import SimpleNamespace

import pytest

from tracecite.extension import (
    EXTENSION_API_VERSION,
    ExtensionAPI,
    ExtensionError,
    available_runtimes,
    get_runtime,
    load_extensions,
    register_runtime,
)
from tracecite.runtime import ScenarioRuntime


def test_third_party_can_register_runtime_without_editing_tracecite() -> None:
    runtime = ScenarioRuntime()

    register_runtime("unit-domain", runtime)

    assert get_runtime("unit-domain") is runtime
    assert "unit-domain" in available_runtimes()
    with pytest.raises(ExtensionError, match="已注册"):
        register_runtime("unit-domain", ScenarioRuntime())


class _FakeEntryPoint:
    name = "synthetic-domain"
    value = "synthetic_extension:register"
    dist = SimpleNamespace(name="synthetic-tracecite", version="1.0")

    def __init__(self, plugin) -> None:
        self._plugin = plugin

    def load(self):
        return self._plugin


def test_extension_loading_is_explicit_versioned_and_idempotent(monkeypatch) -> None:
    runtime = ScenarioRuntime()
    calls: list[str] = []

    def plugin(api: ExtensionAPI) -> None:
        calls.append(api.version)
        api.register_runtime("synthetic-domain", runtime)

    plugin.TRACECITE_EXTENSION_API = EXTENSION_API_VERSION
    entry = _FakeEntryPoint(plugin)

    def fake_entry_points(**kwargs):
        if kwargs.get("group") == "tracecite.extensions":
            return [entry]
        return []

    monkeypatch.setattr(
        "tracecite_core.plugin_sdk.metadata.entry_points",
        fake_entry_points,
    )

    assert "synthetic-domain" not in available_runtimes()
    first = load_extensions()
    second = load_extensions()

    assert first[0]["status"] == "loaded"
    assert first[0]["api_version"] == EXTENSION_API_VERSION
    assert second[0]["status"] == "already_loaded"
    assert get_runtime("synthetic-domain") is runtime
    assert calls == [EXTENSION_API_VERSION]


def test_extension_api_rejects_wrong_runtime_type() -> None:
    with pytest.raises(ExtensionError, match="ScenarioRuntime"):
        ExtensionAPI().register_runtime("bad-runtime", object())  # type: ignore[arg-type]
