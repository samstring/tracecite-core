"""Host integration seam for generic scenario orchestration.

The TraceCite Runtime owns orchestration. Domain extensions provide presets,
named formats, context files, and plugin metadata through this small adapter
instead of being imported by Runtime.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple


@dataclass(frozen=True)
class ScenarioProfile:
    """Generic project settings consumed by the scenario runner."""

    analysis: Mapping[str, Any] = field(default_factory=dict)
    formats: Mapping[str, Any] = field(default_factory=dict)
    filter_presets: Mapping[str, Tuple[str, str]] = field(default_factory=dict)

    def filter_preset_table(self) -> Dict[str, Tuple[str, str]]:
        return dict(self.filter_presets)


ProfileLoader = Callable[[Path, str], Any]
ScenarioPatternResolver = Callable[[str, str, Path, str, str], str]
ContextFilesProvider = Callable[[Path, str], Sequence[Tuple[str, Optional[Path]]]]
PluginMetadataProvider = Callable[[], List[Dict[str, Any]]]
RuntimeVersionsProvider = Callable[[], Mapping[str, str]]


def _default_profile_loader(start_dir: Path, platform: str) -> ScenarioProfile:
    del start_dir, platform
    return ScenarioProfile()


def _default_scenario_pattern_resolver(
    preset: str,
    scenario: str,
    start_dir: Path,
    base_pattern: str,
    platform: str,
) -> str:
    del preset, start_dir, base_pattern, platform
    raise ValueError(
        f"未配置领域 scenario pattern resolver，无法解析子场景 {scenario!r}"
    )


def _default_context_files(
    start_dir: Path, platform: str
) -> Sequence[Tuple[str, Optional[Path]]]:
    del start_dir, platform
    return ()


def _default_plugins() -> List[Dict[str, Any]]:
    return []


def _default_versions() -> Mapping[str, str]:
    return {}


@dataclass(frozen=True)
class ScenarioRuntime:
    """Dependency-injection boundary between Runtime and a domain extension."""

    load_profile: ProfileLoader = _default_profile_loader
    resolve_scenario_pattern: ScenarioPatternResolver = (
        _default_scenario_pattern_resolver
    )
    context_files: ContextFilesProvider = _default_context_files
    loaded_plugins: PluginMetadataProvider = _default_plugins
    runtime_versions: RuntimeVersionsProvider = _default_versions
    allow_live_source: bool = False
    allow_actions: bool = False


DEFAULT_RUNTIME = ScenarioRuntime()
