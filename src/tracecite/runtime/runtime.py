"""Backward-compatible scenario runtime names.

Active scenario execution uses :mod:`tracecite.runtime.scenario_services`.
``ScenarioRuntime`` and ``DEFAULT_RUNTIME`` remain aliases for callers that
have not yet migrated; they are not the Extension v2 execution model.
"""

from __future__ import annotations

from .scenario_services import *  # noqa: F401,F403
from .scenario_services import DEFAULT_SCENARIO_SERVICES, ScenarioServices

ScenarioRuntime = ScenarioServices
DEFAULT_RUNTIME = DEFAULT_SCENARIO_SERVICES
