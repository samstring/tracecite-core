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

# Tests must use the new traversal name. InvestigationStore remains valid only
# as optional audit/work state, not as Evidence memory.
for relative in ("tests/test_runtime_agent_api.py",):
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    text = text.replace("    investigate,\n", "    traverse,\n")
    text = text.replace("investigate(", "traverse(")
    path.write_text(text, encoding="utf-8")

print("canonical follow-up applied")
