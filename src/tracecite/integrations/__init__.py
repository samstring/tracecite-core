"""Adapters exposing TraceCite Runtime to external Agent hosts."""

from .agent_projection import prefer_smaller_agent_view
from .context_engine import (
    CONTEXT_SCHEMA_VERSION,
    ContextEngine,
    ContextState,
    ContextStateStore,
    project_search_delta,
)

__all__ = [
    "CONTEXT_SCHEMA_VERSION",
    "ContextEngine",
    "ContextState",
    "ContextStateStore",
    "prefer_smaller_agent_view",
    "project_search_delta",
]
