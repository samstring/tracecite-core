from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def replace_in(path: Path, replacements: list[tuple[str, str]]) -> None:
    text = path.read_text(encoding="utf-8")
    original = text
    for old, new in replacements:
        text = text.replace(old, new)
    if text != original:
        path.write_text(text, encoding="utf-8")


# 1. Investigation-looking mechanical traversal names become traversal names.
frontier = ROOT / "src/tracecite/runtime/frontier.py"
traversal_frontier = ROOT / "src/tracecite/runtime/traversal_frontier.py"
if frontier.exists():
    frontier.replace(traversal_frontier)
orchestrator = ROOT / "src/tracecite/runtime/orchestrator.py"
traversal = ROOT / "src/tracecite/runtime/traversal.py"
if orchestrator.exists():
    orchestrator.replace(traversal)

replacements = [
    ("from .frontier import", "from .traversal_frontier import"),
    ("from .orchestrator import", "from .traversal import"),
    ("tracecite.runtime.frontier", "tracecite.runtime.traversal_frontier"),
    ("tracecite.runtime.orchestrator", "tracecite.runtime.traversal"),
    ("ExplorationPolicy", "TraversalLimits"),
    ("ExplorationStats", "TraversalStats"),
    ("ExpansionFrontier", "TraversalFrontier"),
    ("FrontierItem", "TraversalItem"),
    ("budget_stop_reason", "bounded_end_reason"),
    ("EvidenceInvestigation", "EvidenceTraversal"),
    ("ExplorationStep", "TraversalStep"),
    ("investigate_evidence", "traverse_evidence"),
    ("CanonicalInvestigationResult", "CanonicalTraversalResult"),
]
for base in (ROOT / "src", ROOT / "tests", ROOT / "benchmarks/agent-investigation"):
    if not base.exists():
        continue
    for path in base.rglob("*"):
        if path.suffix not in {".py", ".ts", ".md"} or not path.is_file():
            continue
        replace_in(path, replacements)

# Rewrite traversal/frontier documentation so a mechanical queue is not described
# as replacing Agent investigation decisions.
if traversal_frontier.exists():
    text = traversal_frontier.read_text(encoding="utf-8")
    text = re.sub(
        r'^""".*?"""',
        '"""Bounded deterministic frontier for caller-scoped Evidence traversal.\n\nThe caller selects traversal seeds and scope. This queue only executes that\nmechanical traversal under hard limits; it never chooses what the Agent should\ninvestigate next.\n"""',
        text,
        count=1,
        flags=re.S,
    )
    traversal_frontier.write_text(text, encoding="utf-8")
if traversal.exists():
    text = traversal.read_text(encoding="utf-8")
    text = re.sub(
        r'^""".*?"""',
        '"""Bounded deterministic traversal over caller-selected Evidence seeds.\n\nTraversal follows stable identities/entities inside the scope supplied by the\ncaller. It is not an Agent, planner, root-cause engine, or next-step selector.\n"""',
        text,
        count=1,
        flags=re.S,
    )
    traversal.write_text(text, encoding="utf-8")

# 2. Transport routing must not use "investigate" as a mode name.
routing = ROOT / "src/tracecite/runtime/evidence_routing.py"
replace_in(
    routing,
    [
        ('INVESTIGATE = "investigate"', 'FOCUSED = "focused"'),
        ("EvidenceRoute.INVESTIGATE", "EvidenceRoute.FOCUSED"),
        ("investigate_max_evidence", "focused_max_evidence"),
        ("investigate_max_line_chars", "focused_max_line_chars"),
        ("investigate_match_records", "focused_match_records"),
        ("investigate_after_executions", "focused_after_executions"),
        ("INVESTIGATE transport", "FOCUSED transport"),
        ("DIRECT -> BOUNDED -> INVESTIGATE", "DIRECT -> BOUNDED -> FOCUSED"),
    ],
)
for base in (ROOT / "src", ROOT / "tests", ROOT / "benchmarks/agent-investigation"):
    if not base.exists():
        continue
    for path in base.rglob("*"):
        if path.suffix not in {".py", ".ts", ".md"} or not path.is_file():
            continue
        replace_in(
            path,
            [
                ("EvidenceRoute.INVESTIGATE", "EvidenceRoute.FOCUSED"),
                ("investigate_max_evidence", "focused_max_evidence"),
                ("investigate_max_line_chars", "focused_max_line_chars"),
                ("investigate_match_records", "focused_match_records"),
                ("investigate_after_executions", "focused_after_executions"),
            ],
        )

# 3. Public agent_api exposes traversal, not investigation.
agent_api = ROOT / "src/tracecite/runtime/agent_api.py"
text = agent_api.read_text(encoding="utf-8")
text = text.replace("def investigate(\n", "def traverse(\n")
text = text.replace('"investigate",\n', '"traverse",\n')
text = text.replace("investigation = traverse_evidence", "traversal = traverse_evidence")
text = text.replace("investigation.graph", "traversal.graph")
text = text.replace("investigation.stop_reason", "traversal.stop_reason")
text = text.replace("investigation.coverage", "traversal.coverage")
text = text.replace("investigation=investigation", "traversal=traversal")
text = text.replace("    investigation: EvidenceTraversal\n", "    traversal: EvidenceTraversal\n")
text = text.replace("payload = self.investigation.to_dict()", "payload = self.traversal.to_dict()")
agent_api.write_text(text, encoding="utf-8")

# 4. Retrieval novelty is no longer migrated from InvestigationState audit.
text = agent_api.read_text(encoding="utf-8")
start = text.find("def _legacy_progress_from_audit(")
end = text.find("\ndef _persist_observation(", start)
if start >= 0 and end > start:
    replacement = '''def _restore_progress(investigation_path: Union[str, Path, None]) -> EvidenceProgressTracker:\n    """Restore only canonical RetrievalSession state.\n\n    InvestigationState audit executions are never replayed into retrieval\n    novelty. If a caller explicitly supplies an investigation path, it gets a\n    dedicated RetrievalSession namespace and starts empty unless that canonical\n    session already exists.\n    """\n\n    if investigation_path is None:\n        return EvidenceProgressTracker()\n    store = RetrievalSessionStore.for_investigation(investigation_path)\n    tracker = _restore_from_session(store.load())\n    return _bind_progress_store(tracker, store)\n\n'''
    text = text[:start] + replacement + text[end + 1 :]
agent_api.write_text(text, encoding="utf-8")

# 5. Remove the no-longer-valid session guard against optional audit metadata.
# Canonical session memory never reads hypotheses/findings; these fields, if a
# compatibility caller still constructs them, are ignored by session retrieval.
session_retrieval = ROOT / "src/tracecite/runtime/session_retrieval.py"
text = session_retrieval.read_text(encoding="utf-8")
text = text.replace(
    '''    if request.investigation_path is not None:\n        raise ValueError("independent retrieval session cannot also use investigation_path")\n    if request.hypothesis_id is not None or request.test_id is not None:\n        raise ValueError("hypothesis_id/test_id require InvestigationState")\n''',
    "",
)
session_retrieval.write_text(text, encoding="utf-8")

# 6. Rewrite runtime public exports around the canonical Evidence contract while
# retaining non-Evidence subsystems only as explicitly named secondary APIs.
runtime_init = ROOT / "src/tracecite/runtime/__init__.py"
runtime_init.write_text('''"""TraceCite Evidence Runtime public contract."""\n\nfrom .agent_api import (\n    EvidenceRequest, ProviderTarget, QueryTarget, RangeTarget, RetrievalResult,\n    RetrieveTarget, SourceTarget, CanonicalTraversalResult, traverse,\n)\nfrom .evidence_api import (\n    AggregateOperation, AggregateRequest, aggregate, materialize, replay, retrieve, verify,\n)\nfrom .evidence_identity import (\n    EvidenceIdentity, SourceVersion, SourceVersionKind, file_source_version, pointer_source_key,\n)\nfrom .evidence_progress import (\n    AcquisitionEndKind, AcquisitionEndReason, CoverageStatus, EvidenceDelta, EvidenceGap,\n    EvidenceProgress, EvidenceProgressTracker,\n)\nfrom .evidence_routing import (\n    EvidenceRoute, EvidenceRoutingPolicy, RoutingDecision, decide_route,\n    estimate_line_addressable_chars, refine_route_after_result,\n)\nfrom .retrieval_session import (\n    RetrievalOperation, RetrievalSessionState, RetrievalSessionStore,\n)\nfrom .traversal import EvidenceTraversal, TraversalStep, traverse_evidence\nfrom .traversal_frontier import TraversalFrontier, TraversalItem, TraversalLimits, TraversalStats\nfrom .capabilities import (\n    CapabilityError, CapabilitySpec, execute_capability, get_capability, list_capabilities, register_capability,\n)\n\n__all__ = [\n    "AcquisitionEndKind", "AcquisitionEndReason", "AggregateOperation", "AggregateRequest",\n    "CanonicalTraversalResult", "CapabilityError", "CapabilitySpec", "CoverageStatus",\n    "EvidenceDelta", "EvidenceGap", "EvidenceIdentity", "EvidenceProgress",\n    "EvidenceProgressTracker", "EvidenceRequest", "EvidenceRoute", "EvidenceRoutingPolicy",\n    "EvidenceTraversal", "ProviderTarget", "QueryTarget", "RangeTarget", "RetrievalOperation",\n    "RetrievalResult", "RetrievalSessionState", "RetrievalSessionStore", "RetrieveTarget",\n    "RoutingDecision", "SourceTarget", "SourceVersion", "SourceVersionKind", "TraversalFrontier",\n    "TraversalItem", "TraversalLimits", "TraversalStats", "TraversalStep", "aggregate",\n    "decide_route", "estimate_line_addressable_chars", "execute_capability", "file_source_version",\n    "get_capability", "list_capabilities", "materialize", "pointer_source_key",\n    "refine_route_after_result", "register_capability", "replay", "retrieve", "traverse",\n    "traverse_evidence", "verify",\n]\n''', encoding="utf-8")

# 7. Top-level package exposes the canonical Evidence contract, not the old
# investigation/workflow tool soup.
top = ROOT / "src/tracecite/__init__.py"
top.write_text('''"""TraceCite: provenance-aware, session-aware Evidence Runtime for Agents."""\n\nfrom __future__ import annotations\n\n__version__ = "0.1.0"\n\nfrom .runtime import (\n    AggregateOperation, AggregateRequest, EvidenceIdentity, EvidenceRequest, EvidenceRoute,\n    EvidenceRoutingPolicy, EvidenceTraversal, ProviderTarget, QueryTarget, RangeTarget,\n    RetrievalResult, RetrievalSessionState, RetrievalSessionStore, SourceTarget, SourceVersion,\n    TraversalLimits, aggregate, list_capabilities, materialize, replay, retrieve, traverse, verify,\n)\n\n__all__ = [\n    "AggregateOperation", "AggregateRequest", "EvidenceIdentity", "EvidenceRequest",\n    "EvidenceRoute", "EvidenceRoutingPolicy", "EvidenceTraversal", "ProviderTarget",\n    "QueryTarget", "RangeTarget", "RetrievalResult", "RetrievalSessionState",\n    "RetrievalSessionStore", "SourceTarget", "SourceVersion", "TraversalLimits",\n    "aggregate", "list_capabilities", "materialize", "replay", "retrieve", "traverse", "verify",\n]\n''', encoding="utf-8")

# 8. Remove old names from module __all__ after mechanical rename.
for path in (traversal_frontier, traversal, agent_api):
    if path.exists():
        text = path.read_text(encoding="utf-8")
        text = text.replace('"investigate",', '"traverse",')
        path.write_text(text, encoding="utf-8")

print("canonical evidence/traversal contract refactor applied")
