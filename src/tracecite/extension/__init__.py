"""TraceCite Extension Protocol v2.

Domain extensions are declarative objects.  They no longer receive a mutable
``ExtensionAPI`` and therefore do not depend on the Runtime's current registry
methods.  This module owns the adapter from stable public capability contracts
to today's internal registries.
"""

from __future__ import annotations

from importlib import metadata
from typing import Any, Dict, List, Optional, Set, Tuple

from tracecite_core.plugin_sdk import PluginAPI, load_entrypoint_plugins, loaded_plugins

from tracecite.runtime.assertions import register_assertion_type
from tracecite.runtime.capabilities import register_capability
from tracecite.runtime.reporting import register_report_outputter
from tracecite.runtime.runtime import DEFAULT_RUNTIME, ScenarioRuntime

from .contracts import (
    CAPABILITY_PROTOCOL_VERSIONS,
    EXTENSION_PROTOCOL_VERSION,
    AgentCapability,
    AssertionCapability,
    CapabilityResult,
    ContractError,
    CorePluginCapability,
    Coverage,
    DomainEvent,
    EvidenceRef,
    ExtensionManifest,
    ReportCapability,
    ScenarioCapability,
    SourceChunk,
    SourceCursor,
    SourceDescriptor,
    TraceCiteExtension,
)


class ExtensionError(RuntimeError):
    """Extension discovery, validation, or installation failed."""


_EXTENSIONS: Dict[str, TraceCiteExtension] = {}
_RUNTIMES: Dict[str, ScenarioRuntime] = {"default": DEFAULT_RUNTIME}
_LOADED_DOMAIN_ENTRYPOINTS: Set[Tuple[str, str]] = set()
_DOMAIN_RESULTS: Dict[Tuple[str, str], Dict[str, Any]] = {}


def _register_runtime(name: str, runtime: ScenarioRuntime) -> None:
    key = str(name).strip().lower()
    if not key:
        raise ExtensionError("runtime 名不能为空")
    if not isinstance(runtime, ScenarioRuntime):
        raise ExtensionError("runtime 必须是 ScenarioRuntime")
    current = _RUNTIMES.get(key)
    if current is not None and current is not runtime:
        raise ExtensionError(f"runtime {key!r} 已注册")
    _RUNTIMES[key] = runtime


def get_runtime(name: str = "default") -> ScenarioRuntime:
    """Host integration helper; ScenarioRuntime is not an extension v2 contract."""

    key = str(name).strip().lower() or "default"
    try:
        return _RUNTIMES[key]
    except KeyError as exc:
        known = ", ".join(available_runtimes())
        raise ExtensionError(f"未知 runtime {key!r}（可用: {known}）") from exc


def available_runtimes() -> List[str]:
    """Return internal scenario adapters made available by installed extensions."""

    return sorted(_RUNTIMES)


def _scenario_runtime(capability: ScenarioCapability) -> ScenarioRuntime:
    kwargs: Dict[str, Any] = {
        "allow_live_source": bool(capability.allow_live_source),
        "allow_actions": bool(capability.allow_actions),
    }
    for field_name in (
        "load_profile",
        "resolve_scenario_pattern",
        "context_files",
        "loaded_plugins",
        "runtime_versions",
    ):
        value = getattr(capability, field_name)
        if value is not None:
            kwargs[field_name] = value
    return ScenarioRuntime(**kwargs)


def _install_extension(extension: TraceCiteExtension) -> None:
    """Translate stable v2 declarations into current internal registries."""

    for capability in extension.capabilities:
        if isinstance(capability, CorePluginCapability):
            capability.register(PluginAPI())
        elif isinstance(capability, AgentCapability):
            register_capability(capability.spec, capability.executor)
        elif isinstance(capability, AssertionCapability):
            register_assertion_type(capability.name, capability.evaluator)
        elif isinstance(capability, ReportCapability):
            register_report_outputter(capability.name, capability.outputter)
        elif isinstance(capability, ScenarioCapability):
            _register_runtime(capability.name, _scenario_runtime(capability))
        else:  # pragma: no cover - TraceCiteExtension validation prevents this.
            raise ExtensionError(f"未知 extension capability: {type(capability).__name__}")


def register_extension(extension: TraceCiteExtension) -> TraceCiteExtension:
    """Install one validated declarative extension exactly once per process."""

    if not isinstance(extension, TraceCiteExtension):
        raise ExtensionError("extension 必须是 TraceCiteExtension")
    key = extension.manifest.id
    current = _EXTENSIONS.get(key)
    if current is not None:
        if current == extension:
            return current
        raise ExtensionError(f"extension {key!r} 已注册")
    try:
        _install_extension(extension)
    except Exception as exc:
        raise ExtensionError(f"安装 extension {key!r} 失败: {exc}") from exc
    _EXTENSIONS[key] = extension
    return extension


def get_extension(extension_id: str) -> TraceCiteExtension:
    key = str(extension_id or "").strip().lower()
    try:
        return _EXTENSIONS[key]
    except KeyError as exc:
        raise ExtensionError(f"未知 extension {key!r}") from exc


def list_extensions() -> List[Dict[str, Any]]:
    """Return stable installed-extension metadata without implementation objects."""

    result: List[Dict[str, Any]] = []
    for key in sorted(_EXTENSIONS):
        extension = _EXTENSIONS[key]
        result.append(
            {
                "id": extension.manifest.id,
                "version": extension.manifest.version,
                "domain": extension.manifest.domain,
                "protocol_version": extension.manifest.protocol_version,
                "description": extension.manifest.description,
                "capabilities": list(extension.capability_summary()),
            }
        )
    return result


def _resolve_extension(value: Any) -> TraceCiteExtension:
    candidate = value
    if not isinstance(candidate, TraceCiteExtension):
        exported = getattr(candidate, "EXTENSION", None)
        if exported is None:
            exported = getattr(candidate, "extension", None)
        if exported is not None:
            candidate = exported
    if callable(candidate) and not isinstance(candidate, TraceCiteExtension):
        candidate = candidate()
    if not isinstance(candidate, TraceCiteExtension):
        raise ExtensionError(
            "tracecite.extensions 入口必须返回 TraceCiteExtension，"
            "或导出 EXTENSION / extension()"
        )
    return candidate


def _entry_points(group: str):
    try:
        return metadata.entry_points(group=group)
    except TypeError:  # pragma: no cover - old importlib.metadata compatibility.
        return metadata.entry_points().get(group, ())


def _load_domain_extensions(*, strict: bool, force: bool) -> List[Dict[str, Any]]:
    group = "tracecite.extensions"
    results: List[Dict[str, Any]] = []
    for entry in _entry_points(group):
        identity = (entry.name, entry.value)
        if identity in _LOADED_DOMAIN_ENTRYPOINTS and not force:
            cached = dict(_DOMAIN_RESULTS[identity])
            cached["status"] = "already_loaded"
            results.append(cached)
            continue
        distribution = getattr(entry, "dist", None)
        item: Dict[str, Any] = {
            "group": group,
            "name": entry.name,
            "value": entry.value,
            "distribution": getattr(distribution, "name", None),
            "distribution_version": getattr(distribution, "version", None),
            "protocol_version": None,
            "extension_id": None,
            "capabilities": [],
            "status": None,
            "error": None,
        }
        try:
            extension = _resolve_extension(entry.load())
            item["protocol_version"] = extension.manifest.protocol_version
            item["extension_id"] = extension.manifest.id
            item["capabilities"] = list(extension.capability_summary())
            register_extension(extension)
            _LOADED_DOMAIN_ENTRYPOINTS.add(identity)
            item["status"] = "loaded"
            _DOMAIN_RESULTS[identity] = dict(item)
            results.append(item)
        except Exception as exc:
            if strict:
                raise ExtensionError(f"加载 TraceCite extension {entry.name!r} 失败: {exc}") from exc
            item["status"] = "failed"
            item["error"] = str(exc)
            _DOMAIN_RESULTS[identity] = dict(item)
            results.append(item)
    return results


def load_extensions(*, strict: bool = True, force: bool = False) -> List[Dict[str, Any]]:
    """Explicitly discover low-level Core plugins and declarative domain extensions."""

    return [
        *load_entrypoint_plugins(
            group="tracecite.core.plugins",
            strict=strict,
            force=force,
        ),
        *_load_domain_extensions(strict=strict, force=force),
    ]


def loaded_extensions() -> List[Dict[str, Any]]:
    return [dict(_DOMAIN_RESULTS[key]) for key in sorted(_DOMAIN_RESULTS)]


__all__ = [
    "EXTENSION_PROTOCOL_VERSION",
    "CAPABILITY_PROTOCOL_VERSIONS",
    "ContractError",
    "ExtensionError",
    "ExtensionManifest",
    "TraceCiteExtension",
    "CorePluginCapability",
    "AgentCapability",
    "AssertionCapability",
    "ReportCapability",
    "ScenarioCapability",
    "EvidenceRef",
    "Coverage",
    "DomainEvent",
    "SourceDescriptor",
    "SourceCursor",
    "SourceChunk",
    "CapabilityResult",
    "register_extension",
    "get_extension",
    "list_extensions",
    "load_extensions",
    "loaded_extensions",
    "loaded_plugins",
    "get_runtime",
    "available_runtimes",
]
