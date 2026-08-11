"""Generic investigation runtime and Agent-facing tool contracts."""

from .assertions import (
    AssertionContext,
    AssertionOutcome,
    AssertionPackage,
    AssertionSpecError,
    available_assertion_types,
    build_assertions,
    register_assertion_type,
)
from .reporting import (
    ReportArtifact,
    ReportContext,
    ReportOutputError,
    available_report_outputters,
    register_report_outputter,
    render_reports,
)
from .runtime import DEFAULT_RUNTIME, ScenarioProfile, ScenarioRuntime
from .schema import (
    AgentResult,
    EvidencePointer,
    RESULT_OUTCOMES,
    RESULT_SCHEMA_VERSION,
    SCENARIO_SCHEMA_VERSION,
    ScenarioDocument,
)
from .scenario import (
    ScenarioError,
    evaluate_behavior_scenario,
    explain_scenario,
    load_spec,
    run_scenario,
    validate_scenario_spec,
)
from .tools import expand, probe, run, search, verify

__all__ = [
    "AssertionContext",
    "AssertionOutcome",
    "AssertionPackage",
    "AssertionSpecError",
    "available_assertion_types",
    "build_assertions",
    "register_assertion_type",
    "ReportArtifact",
    "ReportContext",
    "ReportOutputError",
    "available_report_outputters",
    "register_report_outputter",
    "render_reports",
    "DEFAULT_RUNTIME",
    "ScenarioProfile",
    "ScenarioRuntime",
    "AgentResult",
    "EvidencePointer",
    "ScenarioDocument",
    "RESULT_OUTCOMES",
    "RESULT_SCHEMA_VERSION",
    "SCENARIO_SCHEMA_VERSION",
    "ScenarioError",
    "validate_scenario_spec",
    "load_spec",
    "run_scenario",
    "explain_scenario",
    "evaluate_behavior_scenario",
    "probe",
    "search",
    "expand",
    "verify",
    "run",
]
