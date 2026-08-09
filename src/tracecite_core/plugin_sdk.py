"""tracecite_core 公共插件 SDK。

插件只依赖这里的公开 API，不接触 ``_BUILDERS`` 等内部注册表。第三方包可暴露
``tracecite.core.plugins`` entry point，值为接收 ``PluginAPI`` 的可调用对象。
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import metadata
from typing import Any, Dict, List, Optional, Set, Tuple

from .preprocess import register_preprocessor_action
from .events import register_event_transformer
from .source import register_source_provider
from .segmenter import (
    register_format,
    register_segmenter,
    register_segmenter_detector,
)

PLUGIN_API_VERSION = "2"
_LOADED_ENTRYPOINTS: Set[Tuple[str, str, str]] = set()
_PLUGIN_RESULTS: Dict[Tuple[str, str, str], Dict[str, Optional[str]]] = {}


@dataclass(frozen=True)
class PluginAPI:
    """传给外部插件的稳定注册表面。"""

    version: str = PLUGIN_API_VERSION

    def register_segmenter(
        self,
        name: str,
        factory: Any,
        *,
        aliases: Tuple[str, ...] = (),
        replace: bool = False,
    ) -> None:
        register_segmenter(name, factory, aliases=aliases, replace=replace)

    def register_format(
        self,
        name: str,
        definition: Dict[str, Any],
        *,
        replace: bool = False,
    ) -> None:
        register_format(name, definition, replace=replace)

    def register_detector(
        self,
        name: str,
        detector,
        *,
        priority: int = 0,
        replace: bool = False,
    ) -> None:
        register_segmenter_detector(
            name, detector, priority=priority, replace=replace
        )

    def register_preprocessor(
        self,
        name: str,
        handler,
        *,
        replace: bool = False,
    ) -> None:
        register_preprocessor_action(name, handler, replace=replace)

    def register_source_provider(
        self,
        name: str,
        provider,
        *,
        aliases: Tuple[str, ...] = (),
        replace: bool = False,
    ) -> None:
        register_source_provider(
            name, provider, aliases=aliases, replace=replace
        )

    def register_event_transformer(
        self,
        name: str,
        transformer,
        *,
        replace: bool = False,
    ) -> None:
        register_event_transformer(name, transformer, replace=replace)


def load_entrypoint_plugins(
    *,
    group: str = "tracecite.core.plugins",
    strict: bool = True,
    api: Optional[PluginAPI] = None,
    force: bool = False,
    version_attribute: str = "TRACECITE_CORE_PLUGIN_API",
) -> List[Dict[str, Optional[str]]]:
    """加载已安装插件，返回结构化结果。

    entry point 可以是 ``register(api)`` 函数，或具有同名方法的对象。
    ``strict=False`` 时单个插件失败不会阻断其余插件加载。
    """
    try:
        selected = metadata.entry_points(group=group)
    except TypeError:  # Python 3.9 旧接口
        selected = metadata.entry_points().get(group, ())

    resolved_api = api or PluginAPI()
    results: List[Dict[str, Optional[str]]] = []
    for entry in selected:
        identity = (group, entry.name, entry.value)
        if identity in _LOADED_ENTRYPOINTS and not force:
            cached = dict(_PLUGIN_RESULTS[identity])
            cached["status"] = "already_loaded"
            results.append(cached)
            continue
        distribution = getattr(entry, "dist", None)
        base_result: Dict[str, Optional[str]] = {
            "group": group,
            "name": entry.name,
            "value": entry.value,
            "distribution": getattr(distribution, "name", None),
            "distribution_version": getattr(distribution, "version", None),
            "api_version": None,
            "status": None,
            "error": None,
        }
        try:
            plugin = entry.load()
            declared_api = getattr(plugin, version_attribute, None)
            if declared_api is None:
                raise RuntimeError(f"插件必须声明 {version_attribute}")
            required_api = str(declared_api)
            base_result["api_version"] = required_api
            if required_api != resolved_api.version:
                raise RuntimeError(
                    f"需要插件 API {required_api}，当前为 {resolved_api.version}"
                )
            register = getattr(plugin, "register", plugin)
            if not callable(register):
                raise TypeError("插件入口必须可调用或提供 register(api)")
            register(resolved_api)
            _LOADED_ENTRYPOINTS.add(identity)
            base_result["status"] = "loaded"
            _PLUGIN_RESULTS[identity] = dict(base_result)
            results.append(base_result)
        except Exception as exc:
            if strict:
                raise RuntimeError(f"加载 tracecite_core 插件 {entry.name!r} 失败: {exc}") from exc
            base_result["status"] = "failed"
            base_result["error"] = str(exc)
            _PLUGIN_RESULTS[identity] = dict(base_result)
            results.append(base_result)
    return results


def loaded_plugins() -> List[Dict[str, Optional[str]]]:
    """返回本进程已发现插件的稳定元数据快照。"""
    return [dict(_PLUGIN_RESULTS[key]) for key in sorted(_PLUGIN_RESULTS)]
