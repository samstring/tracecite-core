"""Host integration seam for generic scenario orchestration.

The TraceCite Runtime owns orchestration. Domain extensions provide presets,
named formats, context files, and plugin metadata through this small adapter
instead of being imported by Runtime.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple


PROVENANCE_TEXT_MAX_CHARS = 256


def _bounded_provenance_text(value: Any, *, field: str) -> Tuple[str, bool]:
    """Convert extension metadata to a small JSON-safe scalar."""
    text = "" if value is None else str(value)
    if len(text) <= PROVENANCE_TEXT_MAX_CHARS:
        return text, False
    return text[:PROVENANCE_TEXT_MAX_CHARS], True


@dataclass(frozen=True)
class ScenarioProfile:
    """Generic project settings consumed by the scenario runner."""

    analysis: Mapping[str, Any] = field(default_factory=dict)
    formats: Mapping[str, Any] = field(default_factory=dict)
    filter_presets: Mapping[str, Any] = field(default_factory=dict)

    def filter_preset_table(self) -> Dict[str, Tuple[str, str]]:
        """Return the historical ``name -> (pattern, tag)`` compatibility table."""
        out: Dict[str, Tuple[str, str]] = {}
        for name, raw in self.filter_presets.items():
            key = str(name)
            if isinstance(raw, Mapping):
                pattern = str(raw.get("pattern") or "")
                tag = str(raw.get("tag") or key)
            elif isinstance(raw, (tuple, list)) and len(raw) >= 2:
                pattern, tag = str(raw[0] or ""), str(raw[1] or key)
            else:
                pattern = str(getattr(raw, "pattern", "") or "")
                tag = str(getattr(raw, "tag", "") or key)
            out[key] = (pattern, tag)
        return out

    def filter_preset_metadata(self, name: str) -> Dict[str, Any]:
        """Return bounded preset provenance without changing the v1 table API.

        Extension profiles may expose ``version``, ``source`` and ``sha256``
        on either mapping or object values.  Missing version metadata is
        explicitly represented as ``unknown``; Runtime never invents a version.
        """
        key = str(name)
        raw = self.filter_presets.get(key)
        _pattern, tag = self.filter_preset_table().get(key, ("", key))
        metadata: Dict[str, Any] = {
            "name": key,
            "tag": tag,
            "version": "unknown",
        }
        if raw is not None:
            if isinstance(raw, Mapping):
                getter = raw.get
            else:
                getter = lambda field, default=None: getattr(raw, field, default)
            for field in (
                "version",
                "source",
                "source_path",
                "sha256",
                "hash",
                "content_hash",
            ):
                value = getter(field)
                if value is not None and str(value).strip():
                    target = (
                        "sha256"
                        if field in {"hash", "content_hash"}
                        else "source"
                        if field == "source_path"
                        else field
                    )
                    metadata[target] = str(value)
        source_path = getattr(self, "source_path", None)
        if "source" not in metadata and source_path:
            metadata["source"] = str(source_path)
        bounded: Dict[str, Any] = {}
        for field in ("name", "tag", "version", "source", "sha256"):
            value = metadata.get(field)
            if value is None:
                continue
            text, truncated = _bounded_provenance_text(value, field=field)
            bounded[field] = text
            if truncated:
                bounded[f"{field}_truncated"] = True
        bounded.setdefault("name", key[:PROVENANCE_TEXT_MAX_CHARS])
        if not str(bounded.get("version") or "").strip():
            bounded["version"] = "unknown"
        return bounded


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
