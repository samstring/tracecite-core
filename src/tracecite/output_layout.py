"""Public output-directory layout for TraceCite extensions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from tracecite_core import output_layout as _core

DEFAULT_OUTPUT_ROOT = _core.DEFAULT_OUTPUT_ROOT
USER_OUTPUT_CONFIG_PATH = _core.USER_OUTPUT_CONFIG_PATH
deep_merge = _core.deep_merge


def load_output_config(
    *,
    defaults: Optional[Dict[str, Any]] = None,
    config_path: Optional[Path] = None,
) -> Dict[str, Any]:
    return _core.load_output_config(
        defaults=defaults,
        config_path=config_path or USER_OUTPUT_CONFIG_PATH,
    )


def write_output_config(
    defaults: Dict[str, Any],
    *,
    config_path: Optional[Path] = None,
    overwrite: bool = False,
) -> Path:
    return _core.write_output_config(
        defaults,
        config_path=config_path or USER_OUTPUT_CONFIG_PATH,
        overwrite=overwrite,
    )


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
        return _core.OutputLayout(
            output_root=self.output_root,
            plugins=self.plugins,
        ).plugin_dir(plugin)

    def plugin_path(self, plugin: str, *parts: str) -> Path:
        return _core.OutputLayout(
            output_root=self.output_root,
            plugins=self.plugins,
        ).plugin_path(plugin, *parts)


__all__ = [
    "DEFAULT_OUTPUT_ROOT",
    "OutputLayout",
    "USER_OUTPUT_CONFIG_PATH",
    "deep_merge",
    "load_output_config",
    "write_output_config",
]
