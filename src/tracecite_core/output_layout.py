# -*- coding: utf-8 -*-
"""用户级 output_root 与插件目录解析（不含领域默认树）。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

USER_OUTPUT_CONFIG_PATH = Path.home() / ".tracecite" / "output.json"

DEFAULT_OUTPUT_ROOT = "~/Documents/TraceCite"


def deep_merge(base: Dict[str, Any], override: Mapping[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_output_config(
    *,
    defaults: Optional[Dict[str, Any]] = None,
    config_path: Optional[Path] = None,
) -> Dict[str, Any]:
    base = dict(defaults or {"output_root": DEFAULT_OUTPUT_ROOT, "plugins": {}})
    path = Path(config_path or USER_OUTPUT_CONFIG_PATH)
    if not path.is_file():
        return base
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raw = {}
    if isinstance(raw, dict):
        return deep_merge(base, raw)
    return base


def write_output_config(
    defaults: Dict[str, Any],
    *,
    config_path: Optional[Path] = None,
    overwrite: bool = False,
) -> Path:
    path = Path(config_path or USER_OUTPUT_CONFIG_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        return path
    path.write_text(
        json.dumps(defaults, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


@dataclass(frozen=True)
class OutputLayout:
    output_root: Path
    plugins: Dict[str, Any]

    @classmethod
    def load(
        cls,
        *,
        defaults: Optional[Dict[str, Any]] = None,
        config_path: Optional[Path] = None,
    ) -> "OutputLayout":
        config = load_output_config(defaults=defaults, config_path=config_path)
        root = Path(str(config.get("output_root", DEFAULT_OUTPUT_ROOT))).expanduser().resolve()
        plugins = dict(config.get("plugins") or {})
        return cls(output_root=root, plugins=plugins)

    def plugin_dir(self, plugin: str) -> Path:
        entry = self.plugins.get(plugin) or {}
        rel = str(entry.get("dir") or plugin)
        return self.output_root / rel

    def plugin_path(self, plugin: str, *parts: str) -> Path:
        return self.plugin_dir(plugin).joinpath(*parts)
