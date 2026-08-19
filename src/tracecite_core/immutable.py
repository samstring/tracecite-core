# -*- coding: utf-8 -*-
"""判定证据源是否已是稳定段，可跳过 copy2 snapshot。"""

from __future__ import annotations

from pathlib import Path


def is_stable_source(path: Path) -> bool:
    """archive / sealed / pulled 产物视为不可变证据。"""
    resolved = Path(path).expanduser().resolve()
    if ".archive" in resolved.parts:
        return True
    name = resolved.name
    return name.startswith(("sealed_", "pulled_"))


# ponytail: alias for mobile migration; remove when callers use is_stable_source
is_immutable_log_source = is_stable_source
