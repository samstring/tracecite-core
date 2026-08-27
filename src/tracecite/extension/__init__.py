"""Versioned extension contract for third-party TraceCite capabilities.

Extensions contribute capability registrations and domain semantics. Runtime
continues to own execution, evidence schemas, verification, budgets, and safety
gates. Entry-point loading is explicit; importing :mod:`tracecite` never runs
third-party registration code.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from tracecite_core.plugin_sdk import PluginAPI, load_entrypoint_plugins, loaded_plugins

from tracecite.runtime.assertions import register_assertion_type
from tracecite.runtime.capabilities import (
    CapabilityExecutor,
    CapabilitySpec,
    register_capability,
)
from tracecite.runtime.reporting import register_report_outputter
from tracecite.runtime.runtime import DEFAULT_RUNTIME, ScenarioRuntime


EXTENSION_API_VERSION = "1"
_RUNTIMES: Dict[str, ScenarioRuntime] = {"default": DEFAULT_RUNTIME}


class ExtensionError(RuntimeError):
    """An extension registration or lookup failed."""


def register_runtime(
    name: str,
    runtime: ScenarioRuntime,
    *,
    replace: bool = False,
) -> None:
    """Register a named domain runtime without changing TraceCite source."""
    key = str(name).strip().lower()
    if not key:
        raise ExtensionError("runtime 名不能为空")
    if not isinstance(runtime, ScenarioRuntime):
        raise ExtensionError("runtime 必须是 ScenarioRuntime")
    current = _RUNTIMES.get(key)
    if current is not None and current is not runtime and not replace:
        raise ExtensionError(f"runtime {key!r} 已注册")
    _RUNTIMES[key] = runtime


def get_runtime(name: str = "default") -> ScenarioRuntime:
    key = str(name).strip().lower() or "default"
    try:
        return _RUNTIMES[key]
    except KeyError as exc:
        known = ", ".join(available_runtimes())
        raise ExtensionError(f"未知 runtime {key!r}（可用: {known}）") from exc


def available_runtimes() -> List[str]:
    return sorted(_RUNTIMES)


@dataclass(frozen=True)
class ExtensionAPI(PluginAPI):
    """Stable registration surface passed to installed domain extensions."""

    version: str = EXTENSION_API_VERSION

    def register_assertion_type(
        self, name: str, evaluator: Any, *, replace: bool = False
    ) -> None:
        register_assertion_type(name, evaluator, replace=replace)

    def register_report_outputter(
        self, name: str, outputter: Any, *, replace: bool = False
    ) -> None:
        register_report_outputter(name, outputter, replace=replace)

    def register_runtime(
        self, name: str, runtime: ScenarioRuntime, *, replace: bool = False
    ) -> None:
        register_runtime(name, runtime, replace=replace)

    def register_capability(
        self,
        spec: CapabilitySpec,
        executor: CapabilityExecutor,
        *,
        replace: bool = False,
    ) -> None:
        """Expose a domain capability through the Runtime-owned registry."""
        register_capability(spec, executor, replace=replace)


def load_extensions(*, strict: bool = True) -> List[Dict[str, Optional[str]]]:
    """Explicitly discover installed Core and Runtime extensions."""
    return [
        *load_entrypoint_plugins(group="tracecite.core.plugins", strict=strict),
        *load_entrypoint_plugins(
            group="tracecite.extensions",
            strict=strict,
            api=ExtensionAPI(),
            version_attribute="TRACECITE_EXTENSION_API",
        ),
    ]


__all__ = [
    "EXTENSION_API_VERSION",
    "ExtensionAPI",
    "ExtensionError",
    "register_runtime",
    "get_runtime",
    "available_runtimes",
    "load_extensions",
    "loaded_plugins",
]
