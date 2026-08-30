"""Host-owned observation of complete Agent tool activity.

This module intentionally lives outside ``tracecite.runtime``.  Core can only
observe TraceCite Evidence operations; an Agent Host is the only layer capable
of seeing TraceCite calls together with shell/read/search/browser calls.
Activity is telemetry, never evidence sufficiency or stop advice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping


ToolCategory = Literal[
    "tracecite_evidence",
    "native_search",
    "native_read",
    "native_other",
    "other",
]


@dataclass(frozen=True)
class ToolActivityEvent:
    tool: str
    category: ToolCategory
    duration_ms: int = 0
    status: str = "ok"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        tool = str(self.tool or "").strip()
        if not tool:
            raise ValueError("tool activity requires a tool name")
        if self.category not in {
            "tracecite_evidence",
            "native_search",
            "native_read",
            "native_other",
            "other",
        }:
            raise ValueError("unsupported tool activity category")
        if isinstance(self.duration_ms, bool) or not isinstance(self.duration_ms, int) or self.duration_ms < 0:
            raise ValueError("duration_ms must be a non-negative integer")
        object.__setattr__(self, "tool", tool)
        object.__setattr__(self, "status", str(self.status or "unknown")[:64])
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass
class ToolActivityLedger:
    """Bounded Host telemetry for one Agent trajectory."""

    max_events: int = 512
    _events: list[ToolActivityEvent] = field(default_factory=list, init=False, repr=False)

    def __post_init__(self) -> None:
        if isinstance(self.max_events, bool) or not isinstance(self.max_events, int) or self.max_events < 1:
            raise ValueError("max_events must be a positive integer")

    def record(self, event: ToolActivityEvent) -> None:
        if not isinstance(event, ToolActivityEvent):
            raise TypeError("record requires ToolActivityEvent")
        self._events.append(event)
        if len(self._events) > self.max_events:
            del self._events[: len(self._events) - self.max_events]

    @property
    def events(self) -> tuple[ToolActivityEvent, ...]:
        return tuple(self._events)

    def summary(self) -> dict[str, Any]:
        categories: dict[str, int] = {}
        tools: dict[str, int] = {}
        duration_ms = 0
        for event in self._events:
            categories[event.category] = categories.get(event.category, 0) + 1
            tools[event.tool] = tools.get(event.tool, 0) + 1
            duration_ms += event.duration_ms
        return {
            "total_tool_calls": len(self._events),
            "categories": dict(sorted(categories.items())),
            "tools": dict(sorted(tools.items())),
            "observed_duration_ms": duration_ms,
        }

    def checkpoint_view(self) -> dict[str, Any]:
        """Return facts a Host may show when it chooses to request reflection.

        This method does not decide when to show a checkpoint and deliberately
        emits no ``should_stop``, sufficiency, confidence, or next-step field.
        """

        return {"tool_activity": self.summary()}


__all__ = ["ToolActivityEvent", "ToolActivityLedger", "ToolCategory"]
