"""TraceCite: an extensible evidence runtime for AI agents."""

from __future__ import annotations

__version__ = "0.1.0"

from .runtime import (
    AgentResult,
    EvidencePointer,
    RESULT_OUTCOMES,
    RESULT_SCHEMA_VERSION,
    SCENARIO_SCHEMA_VERSION,
    ScenarioDocument,
    ScenarioError,
    ScenarioProfile,
    ScenarioRuntime,
    expand,
    probe,
    run,
    search,
    verify,
)

__all__ = [
    "AgentResult",
    "EvidencePointer",
    "RESULT_OUTCOMES",
    "RESULT_SCHEMA_VERSION",
    "SCENARIO_SCHEMA_VERSION",
    "ScenarioDocument",
    "ScenarioError",
    "ScenarioProfile",
    "ScenarioRuntime",
    "probe",
    "search",
    "expand",
    "verify",
    "run",
]
