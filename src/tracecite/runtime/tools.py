"""Backward-compatible ``runtime.tools`` surface over canonical acquisition.

Runtime internals must depend on :mod:`tracecite.runtime.acquisition`; this
module remains only for legacy callers and integrations while preserving the
existing Python surface.
"""

from __future__ import annotations

from . import acquisition as _acquisition
from .acquisition import *  # noqa: F401,F403


def __getattr__(name: str):
    return getattr(_acquisition, name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(_acquisition)))
