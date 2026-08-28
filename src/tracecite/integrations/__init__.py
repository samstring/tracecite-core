"""Adapters exposing TraceCite Runtime to external Agent hosts."""

from .agent_profile import (
    AgentCapabilities,
    AgentProfile,
    get_agent_profile,
    profile_names,
    select_agent_profile,
)
from .agent_projection import (
    Projection,
    ProjectionProfile,
    prefer_smaller_agent_view,
    project,
)
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
    "Projection",
    "ProjectionProfile",
    "get_agent_profile",
    "prefer_smaller_agent_view",
    "profile_names",
    "project",
    "project_search_delta",
    "select_agent_profile",
]
