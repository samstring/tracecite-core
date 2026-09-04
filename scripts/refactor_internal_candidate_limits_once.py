from __future__ import annotations

import re
from pathlib import Path


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"missing expected block: {label}")
    return text.replace(old, new, 1)


def replace_regex(text: str, pattern: str, replacement: str, *, label: str) -> str:
    resolved, count = re.subn(pattern, replacement, text, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError(f"missing expected regex block: {label}")
    return resolved


# ---------------------------------------------------------------------------
# 1. Canonical QueryTarget carries query semantics only. Result-page limits are
#    Runtime transport details, not user-facing investigation budgets.
# ---------------------------------------------------------------------------
agent_path = Path("src/tracecite/runtime/agent_api.py")
agent = agent_path.read_text(encoding="utf-8")
agent = replace_once(
    agent,
    '''    fold: bool = False\n    max_evidence: int | None = None\n    max_line_chars: int | None = None\n''',
    '''    fold: bool = False\n''',
    label="QueryTarget public limit fields",
)
agent = replace_once(
    agent,
    'def retrieve(request: EvidenceRequest) -> RetrievalResult:\n    """Execute one canonical evidence acquisition request."""',
    '''def retrieve(\n    request: EvidenceRequest,\n    *,\n    _max_candidates: int | None = None,\n    _max_line_chars: int | None = None,\n) -> RetrievalResult:\n    """Execute one canonical evidence acquisition request.\n\n    Underscored limits are Runtime transport details used only by the adaptive\n    PROGRESSIVE contract. They are deliberately absent from ``QueryTarget``.\n    """''',
    label="agent retrieve internal limits",
)
agent = replace_once(
    agent,
    '''            fold=target.fold,\n            max_evidence=target.max_evidence,\n            max_line_chars=target.max_line_chars,\n            investigation_path=request.investigation_path,''',
    '''            fold=target.fold,\n            max_candidates=_max_candidates,\n            max_line_chars=_max_line_chars,\n            investigation_path=request.investigation_path,''',
    label="agent acquisition call",
)
agent_path.write_text(agent, encoding="utf-8")


# ---------------------------------------------------------------------------
# 2. Acquisition names the internal page bound for what it is: candidates.
#    Legacy runtime.tools.search keeps max_evidence only as a compatibility
#    alias, outside the canonical implementation.
# ---------------------------------------------------------------------------
acq_path = Path("src/tracecite/runtime/acquisition.py")
acq = acq_path.read_text(encoding="utf-8")
acq = replace_once(
    acq,
    '''    fold: bool = False,\n    max_evidence: Optional[int] = None,\n    max_line_chars: Optional[int] = None,''',
    '''    fold: bool = False,\n    max_candidates: Optional[int] = None,\n    max_line_chars: Optional[int] = None,''',
    label="acquisition search signature",
)
acq = replace_once(
    acq,
    '''        "fold": fold,\n        "max_evidence": max_evidence,\n        "max_line_chars": max_line_chars,\n    }\n    evidence_limit = (\n        MAX_RESULT_EVIDENCE\n        if max_evidence is None\n        else min(MAX_RESULT_EVIDENCE, max(1, int(max_evidence)))\n    )''',
    '''        "fold": fold,\n        "max_candidates": max_candidates,\n        "max_line_chars": max_line_chars,\n    }\n    candidate_limit = (\n        MAX_RESULT_EVIDENCE\n        if max_candidates is None\n        else min(MAX_RESULT_EVIDENCE, max(1, int(max_candidates)))\n    )''',
    label="candidate limit calculation",
)
acq = acq.replace('"recorded_evidence_pointers": evidence_limit,', '"recorded_evidence_pointers": candidate_limit,')
acq = acq.replace('if len(evidence) >= evidence_limit:', 'if len(evidence) >= candidate_limit:')
acq_path.write_text(acq, encoding="utf-8")


tools_path = Path("src/tracecite/runtime/tools.py")
tools = tools_path.read_text(encoding="utf-8")
insert = '''\n\ndef search(*args, max_evidence=None, max_candidates=None, **kwargs):\n    """Legacy search adapter.\n\n    ``max_evidence`` is accepted only for compatibility and is translated to\n    the canonical internal ``max_candidates`` page bound. New Runtime code must\n    call :mod:`tracecite.runtime.acquisition` and use ``max_candidates``.\n    """\n\n    if max_evidence is not None and max_candidates is not None:\n        raise TypeError("use either legacy max_evidence or max_candidates, not both")\n    if max_candidates is None:\n        max_candidates = max_evidence\n    return _acquisition.search(*args, max_candidates=max_candidates, **kwargs)\n'''
if 'def search(*args, max_evidence=None, max_candidates=None, **kwargs):' not in tools:
    tools = tools.rstrip() + insert + "\n"
tools_path.write_text(tools, encoding="utf-8")


# ---------------------------------------------------------------------------
# 3. The routing policy has no BOUNDED/FOCUSED vocabulary anymore. These are
#    two internal PROGRESSIVE intensities, expressed as candidate/line limits.
# ---------------------------------------------------------------------------
renames = {
    "bounded_max_evidence": "progressive_max_candidates",
    "focused_max_evidence": "deep_progressive_max_candidates",
    "bounded_max_line_chars": "progressive_max_line_chars",
    "focused_max_line_chars": "deep_progressive_max_line_chars",
    "bounded_match_records": "progressive_match_records",
    "focused_match_records": "deep_progressive_match_records",
    "focused_after_executions": "deep_progressive_after_executions",
}
for path in [Path("src/tracecite/runtime/evidence_routing.py"), Path("tests/test_evidence_routing.py")]:
    text = path.read_text(encoding="utf-8")
    for old, new in renames.items():
        text = text.replace(old, new)
    text = text.replace("ordinary bounded\n    search", "ordinary progressive\n    search")
    text = text.replace("bounded_default", "progressive_default")
    text = text.replace("match_cardinality_requires_bounds", "match_cardinality_requires_progressive")
    path.write_text(text, encoding="utf-8")

routing_path = Path("src/tracecite/runtime/evidence_routing.py")
routing = routing_path.read_text(encoding="utf-8")
routing = replace_once(
    routing,
    '''        if self.deep_progressive_max_candidates > self.progressive_max_candidates:\n            raise ValueError("deep_progressive_max_candidates must be <= progressive_max_candidates")\n        if self.deep_progressive_max_line_chars > self.progressive_max_line_chars:\n            raise ValueError("deep_progressive_max_line_chars must be <= progressive_max_line_chars")\n        if self.deep_progressive_match_records < self.progressive_match_records:\n            raise ValueError("deep_progressive_match_records must be >= progressive_match_records")''',
    '''        if self.deep_progressive_max_candidates > self.progressive_max_candidates:\n            raise ValueError("deep_progressive_max_candidates must be <= progressive_max_candidates")\n        if self.deep_progressive_max_line_chars > self.progressive_max_line_chars:\n            raise ValueError("deep_progressive_max_line_chars must be <= progressive_max_line_chars")\n        if self.deep_progressive_match_records < self.progressive_match_records:\n            raise ValueError("deep_progressive_match_records must be >= progressive_match_records")''',
    label="progressive validation present",
)
routing_path.write_text(routing, encoding="utf-8")


# ---------------------------------------------------------------------------
# 4. retrieve_contract computes private transport limits rather than rebuilding
#    a public QueryTarget with page-size knobs.
# ---------------------------------------------------------------------------
contract_path = Path("src/tracecite/runtime/retrieve_contract.py")
contract = contract_path.read_text(encoding="utf-8")
for old, new in renames.items():
    contract = contract.replace(old, new)
contract = contract.replace("_BOUNDED_SOURCE_SAMPLE_RECORDS", "_PROGRESSIVE_SOURCE_SAMPLE_RECORDS")
contract = contract.replace("_BOUNDED_SOURCE_SAMPLE_CHARS", "_PROGRESSIVE_SOURCE_SAMPLE_CHARS")
contract = contract.replace("bounded source inspection", "progressive source inspection")

contract = replace_regex(
    contract,
    r'def _progressive_query\(\n    request: EvidenceRequest,\n    policy: EvidenceRoutingPolicy,\n    \*,\n    decision: RoutingDecision,\n\) -> EvidenceRequest:\n.*?\n\n\ndef _attach_search_fidelity',
    '''def _progressive_query_limits(\n    request: EvidenceRequest,\n    policy: EvidenceRoutingPolicy,\n    *,\n    decision: RoutingDecision,\n) -> tuple[int, int]:\n    """Return private candidate/body limits for one PROGRESSIVE query."""\n\n    assert isinstance(request.target, QueryTarget)\n    deep_progressive = any(\n        reason in {"high_match_cardinality", "exploration_depth", "repeated_evidence", "multiple_sources"}\n        for reason in decision.reasons\n    )\n    if deep_progressive:\n        return (\n            policy.deep_progressive_max_candidates,\n            policy.deep_progressive_max_line_chars,\n        )\n    return (policy.progressive_max_candidates, policy.progressive_max_line_chars)\n\n\ndef _attach_search_fidelity''',
    label="progressive query request rewrite",
)
contract = replace_once(
    contract,
    '''    routed_request = request\n    if isinstance(request.target, QueryTarget):\n        routed_request = _progressive_query(request, policy, decision=decision)\n    result = _correct_range_novelty(_retrieve(routed_request), routed_request)''',
    '''    routed_request = request\n    query_limits: tuple[int, int] | None = None\n    if isinstance(request.target, QueryTarget):\n        query_limits = _progressive_query_limits(request, policy, decision=decision)\n    result = _correct_range_novelty(\n        _retrieve(\n            routed_request,\n            _max_candidates=query_limits[0] if query_limits is not None else None,\n            _max_line_chars=query_limits[1] if query_limits is not None else None,\n        ),\n        routed_request,\n    )''',
    label="private progressive limits dispatch",
)
contract_path.write_text(contract, encoding="utf-8")


# ---------------------------------------------------------------------------
# 5. Pi transport no longer presents max_evidence as an Agent-visible knob.
#    Runtime determines candidate-page size under PROGRESSIVE disclosure.
# ---------------------------------------------------------------------------
bridge_path = Path("benchmarks/agent-investigation/pi_tracecite_bridge.py")
bridge = bridge_path.read_text(encoding="utf-8")
bridge = replace_once(
    bridge,
    '''            regex=bool(args.regex),\n            snapshot=True,\n            max_evidence=args.max_evidence,\n        )''',
    '''            regex=bool(args.regex),\n            snapshot=True,\n        )''',
    label="Pi bridge QueryTarget limit",
)
bridge = bridge.replace('    retrieve_parser.add_argument("--max-evidence", type=int, default=20)\n', '')
bridge_path.write_text(bridge, encoding="utf-8")

ext_path = Path("benchmarks/agent-investigation/pi_tracecite_extension_impl.ts")
ext = ext_path.read_text(encoding="utf-8")
ext = ext.replace('      max_evidence: Type.Optional(Type.Integer({ minimum: 1, maximum: 50 })),\n', '', 1)
ext = replace_once(
    ext,
    '      const args = ["retrieve", p.file, "--max-evidence", String(p.max_evidence ?? 20)];',
    '      const args = ["retrieve", p.file];',
    label="Pi canonical retrieve args",
)
# Remove the compatibility search exposure too; it is a naming alias, not a
# second budget/configuration surface.
ext = ext.replace('      max_evidence: Type.Optional(Type.Integer({ minimum: 1, maximum: 50 })),\n', '', 1)
ext = replace_once(
    ext,
    '      const args = ["retrieve", p.file, "--query", p.query, "--max-evidence", String(p.max_evidence ?? 20)];',
    '      const args = ["retrieve", p.file, "--query", p.query];',
    label="Pi compatibility search args",
)
ext_path.write_text(ext, encoding="utf-8")


# ---------------------------------------------------------------------------
# 6. Contract tests: QueryTarget must not regain transport-budget fields; legacy
#    tools adapter continues to accept max_evidence during compatibility window.
# ---------------------------------------------------------------------------
agent_test_path = Path("tests/test_runtime_agent_api.py")
agent_test = agent_test_path.read_text(encoding="utf-8")
marker = 'def test_mutable_source_version_is_not_immutable() -> None:\n'
addition = '''def test_query_target_contains_query_semantics_not_result_budget_knobs() -> None:\n    assert "max_evidence" not in QueryTarget.__dataclass_fields__\n    assert "max_line_chars" not in QueryTarget.__dataclass_fields__\n\n\n'''
if addition not in agent_test:
    if marker not in agent_test:
        raise RuntimeError("runtime agent test insertion marker missing")
    agent_test = agent_test.replace(marker, addition + marker, 1)
agent_test_path.write_text(agent_test, encoding="utf-8")

routing_test_path = Path("tests/test_evidence_routing.py")
routing_test = routing_test_path.read_text(encoding="utf-8")
routing_test = routing_test.replace(
    "test_investigate_transport_must_not_be_wider_than_bounded_transport",
    "test_deep_progressive_transport_must_not_be_wider_than_progressive_transport",
)
routing_test_path.write_text(routing_test, encoding="utf-8")

boundary_path = Path("tests/test_runtime_acquisition_boundary.py")
boundary = boundary_path.read_text(encoding="utf-8")
legacy_test = '''\n\ndef test_legacy_tools_max_evidence_maps_to_internal_candidate_limit(tmp_path) -> None:\n    source = tmp_path / "compat.log"\n    source.write_text("hit one\\nhit two\\nhit three\\n", encoding="utf-8")\n    from tracecite.runtime import tools\n\n    result = tools.search(source, "hit", snapshot=False, max_evidence=1)\n    assert result["coverage"]["match_records"] == 3\n    assert result["coverage"]["evidence_returned"] == 1\n\n'''
if legacy_test not in boundary:
    boundary = boundary.rstrip() + legacy_test
boundary_path.write_text(boundary, encoding="utf-8")

print("internal candidate limit migration applied")
