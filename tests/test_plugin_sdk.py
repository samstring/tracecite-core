from __future__ import annotations

from pathlib import Path

import pytest

from tracecite_core import PluginAPI, build_segmenter, detect_segmenter_kind
from tracecite_core.plugin_sdk import load_entrypoint_plugins
from tracecite_core.segmenter import RawTextSegmenter


def test_public_plugin_api_registers_segmenter_format_and_detector(tmp_path: Path) -> None:
    api = PluginAPI()
    api.register_segmenter("unit-lines", RawTextSegmenter)
    api.register_format("unit-format", {"start": r"^UNIT "})
    api.register_detector(
        "unit-detector",
        lambda path, sample_lines=60: "unit-lines" if path.name == "unit.data" else None,
        priority=999,
    )

    assert isinstance(build_segmenter("unit-lines"), RawTextSegmenter)
    assert build_segmenter("unit-format").name == "format"
    sample = tmp_path / "unit.data"
    sample.write_text("anything\n", encoding="utf-8")
    assert detect_segmenter_kind(sample) == "unit-lines"


def test_plugin_registration_conflict_is_explicit() -> None:
    api = PluginAPI()
    api.register_segmenter("unit-conflict", RawTextSegmenter)
    with pytest.raises(ValueError, match="已注册"):
        api.register_segmenter("unit-conflict", lambda: RawTextSegmenter())


class _FakeEntryPoint:
    def __init__(self, name: str, plugin) -> None:
        self.name = name
        self.value = f"tests:{name}"
        self._plugin = plugin

    def load(self):
        return self._plugin


def test_entrypoint_loader_checks_version_and_is_idempotent(monkeypatch) -> None:
    calls = []

    def plugin(api) -> None:
        calls.append(api.version)
        api.register_segmenter("unit-entrypoint", RawTextSegmenter)

    plugin.TRACECITE_CORE_PLUGIN_API = "2"
    entry = _FakeEntryPoint("unit-entrypoint-plugin", plugin)
    monkeypatch.setattr(
        "tracecite_core.plugin_sdk.metadata.entry_points",
        lambda **kwargs: [entry],
    )

    first = load_entrypoint_plugins(group="tracecite_core.tests.plugins")
    second = load_entrypoint_plugins(group="tracecite_core.tests.plugins")

    assert first[0]["name"] == entry.name
    assert first[0]["status"] == "loaded"
    assert first[0]["api_version"] == "2"
    assert second[0]["status"] == "already_loaded"
    assert calls == ["2"]


def test_entrypoint_loader_rejects_api_mismatch(monkeypatch) -> None:
    def plugin(api) -> None:
        raise AssertionError("version gate should run before registration")

    plugin.TRACECITE_CORE_PLUGIN_API = "99"
    entry = _FakeEntryPoint("unit-version-mismatch", plugin)
    monkeypatch.setattr(
        "tracecite_core.plugin_sdk.metadata.entry_points",
        lambda **kwargs: [entry],
    )

    with pytest.raises(RuntimeError, match="需要插件 API 99，当前为 2"):
        load_entrypoint_plugins(group="tracecite_core.tests.version")

    result = load_entrypoint_plugins(group="tracecite_core.tests.version", strict=False)
    assert result[0]["name"] == entry.name
    assert result[0]["status"] == "failed"
    assert result[0]["error"] == "需要插件 API 99，当前为 2"


def test_entrypoint_loader_requires_explicit_api_declaration(monkeypatch) -> None:
    entry = _FakeEntryPoint("unit-missing-version", lambda api: None)
    monkeypatch.setattr(
        "tracecite_core.plugin_sdk.metadata.entry_points",
        lambda **kwargs: [entry],
    )

    with pytest.raises(RuntimeError, match="必须声明 TRACECITE_CORE_PLUGIN_API"):
        load_entrypoint_plugins(group="tracecite_core.tests.missing-version")
