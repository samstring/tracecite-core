from __future__ import annotations

"""Retired compatibility shim for the former custom free-shell benchmark.

Official agent comparisons use the real Pi A/B harness:

- ``pi-native``: Pi with its native read/bash/grep/find/ls tools.
- ``pi-tracecite``: the same Pi harness and native tools plus TraceCite.

The custom ``free_shell`` benchmark is intentionally non-runnable.  This module
remains only because legacy GMI host modules import it at module-import time.
Removing the file outright would break unrelated historical host imports while
providing no benchmark value.
"""

from pathlib import Path
from typing import Any, Mapping, Sequence

import openai_host as common


_RETIRED_MESSAGE = (
    "free_shell benchmark mode is retired; use the official Pi A/B harness "
    "(`pi-native` vs `pi-tracecite`) instead"
)


def tools(files: Sequence[Path]) -> list[dict[str, Any]]:
    del files
    raise RuntimeError(_RETIRED_MESSAGE)


class Runtime(common.ToolRuntime):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise RuntimeError(_RETIRED_MESSAGE)

    def call(self, name: str, args: Mapping[str, Any]) -> str:
        del name, args
        raise RuntimeError(_RETIRED_MESSAGE)
