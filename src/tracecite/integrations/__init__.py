"""Adapters exposing TraceCite Runtime to external Agent hosts."""

from .agent_profile import (
    AgentCapabilities,
    AgentProfile,
    get_agent_profile,
    profile_names,
    select_agent_profile,
)
from .agent_projection import prefer_smaller_agent_view
from .context_engine import (
    CONTEXT_SCHEMA_VERSION,
    ContextEngine,
    ContextState,
    ContextStateStore,
    project_search_delta,
)

__all__ = [
    "AgentCapabilities",
    "AgentProfile",
    "CONTEXT_SCHEMA_VERSION",
    "ContextEngine",
    "ContextState",
    "ContextStateStore",
    "get_agent_profile",
    "prefer_smaller_agent_view",
    "profile_names",
    "project_search_delta",
    "select_agent_profile",
]
