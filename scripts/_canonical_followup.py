from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

runtime_init = ROOT / "src/tracecite/runtime/__init__.py"
text = runtime_init.read_text(encoding="utf-8")
anchor = '''from .capabilities import (\n    CapabilityError, CapabilitySpec, execute_capability, get_capability, list_capabilities, register_capability,\n)\n'''
secondary = anchor + '''# Optional Host/Agent work-state APIs remain explicit secondary surfaces.\n# They are not consulted by RetrievalSession novelty or Evidence routing.\nfrom .investigation import (\n    BudgetExhausted, BudgetPolicy, InvestigationError, InvestigationState, InvestigationStore,\n    create_investigation, load_investigation,\n)\n'''
if anchor not in text:
    raise SystemExit("runtime __init__ capability anchor missing")
text = text.replace(anchor, secondary, 1)
needle = '    "get_capability", "list_capabilities", "materialize", "pointer_source_key",\n'
replacement = '    "get_capability", "list_capabilities", "BudgetExhausted", "BudgetPolicy", "InvestigationError",\n    "InvestigationState", "InvestigationStore", "create_investigation", "load_investigation",\n    "materialize", "pointer_source_key",\n'
if needle not in text:
    raise SystemExit("runtime __all__ anchor missing")
text = text.replace(needle, replacement, 1)
runtime_init.write_text(text, encoding="utf-8")

# Tests use the new traversal contract and explicitly prove that audit history is
# not migrated back into canonical retrieval novelty.
path = ROOT / "tests/test_runtime_agent_api.py"
text = path.read_text(encoding="utf-8")
text = text.replace("    investigate,\n", "    traverse,\n")
text = text.replace("investigate(", "traverse(")
text = text.replace("result.investigation", "result.traversal")
text = text.replace(
    "def test_legacy_audit_progress_migrates_once_when_sidecar_is_missing(tmp_path) -> None:",
    "def test_audit_history_is_not_migrated_into_retrieval_novelty(tmp_path) -> None:",
)
text = text.replace(
    '    assert migrated.status == "no_new_evidence"\n    assert migrated.new_evidence == ()\n',
    '    assert migrated.status == "ok"\n    assert migrated.new_evidence\n',
)
path.write_text(text, encoding="utf-8")

routing_test = ROOT / "tests/test_evidence_routing.py"
text = routing_test.read_text(encoding="utf-8")
text = text.replace('["next_mode"] == "investigate"', '["next_mode"] == "focused"')
routing_test.write_text(text, encoding="utf-8")

# A session-scoped canonical retrieval must never share an InvestigationState
# path: this protects the single-owner invariant instead of migrating audit data
# into novelty state.
session_path = ROOT / "src/tracecite/runtime/session_retrieval.py"
text = session_path.read_text(encoding="utf-8")
anchor = '''    if not isinstance(session, RetrievalSessionStore):\n        raise TypeError("retrieve_with_session requires RetrievalSessionStore")\n'''
guard = anchor + '''    if request.investigation_path is not None:\n        raise ValueError("independent retrieval session cannot also use investigation_path")\n    if request.hypothesis_id is not None or request.test_id is not None:\n        raise ValueError("hypothesis_id/test_id require optional InvestigationState, not RetrievalSession")\n'''
if anchor not in text:
    raise SystemExit("session retrieval type-check anchor missing")
text = text.replace(anchor, guard, 1)
session_path.write_text(text, encoding="utf-8")

print("canonical follow-up applied")
