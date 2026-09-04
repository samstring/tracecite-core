from pathlib import Path


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"missing expected block: {label}")
    return text.replace(old, new, 1)


routing_path = Path("src/tracecite/runtime/evidence_routing.py")
routing = routing_path.read_text(encoding="utf-8")

routing = replace_once(
    routing,
    "The default policy starts with the cheapest safe path and only escalates:\nDIRECT -> BOUNDED -> FOCUSED.\n",
    "The public disclosure model has only two modes:\nDIRECT -> PROGRESSIVE.\n\nPROGRESSIVE may internally tighten sampling or result caps as retrieval history\ngrows, but those are implementation details rather than public disclosure modes.\n",
    label="routing doc modes",
)
routing = replace_once(
    routing,
    'class EvidenceRoute(str, Enum):\n    DIRECT = "direct"\n    BOUNDED = "bounded"\n    FOCUSED = "focused"\n\n\n_ROUTING_MODES = frozenset({"adaptive", *(item.value for item in EvidenceRoute)})',
    'class EvidenceRoute(str, Enum):\n    DIRECT = "direct"\n    PROGRESSIVE = "progressive"\n\n\n_ROUTING_MODES = frozenset({"adaptive", *(item.value for item in EvidenceRoute)})\n_LEGACY_PROGRESSIVE_MODES = frozenset({"bounded", "focused"})',
    label="route enum",
)
routing = replace_once(
    routing,
    '        if mode not in _ROUTING_MODES:\n            raise ValueError("routing mode must be adaptive/direct/bounded/investigate")\n        object.__setattr__(self, "mode", mode)',
    '        if mode in _LEGACY_PROGRESSIVE_MODES:\n            mode = EvidenceRoute.PROGRESSIVE.value\n        if mode not in _ROUTING_MODES:\n            raise ValueError("routing mode must be adaptive/direct/progressive")\n        object.__setattr__(self, "mode", mode)',
    label="mode validation",
)
routing = replace_once(
    routing,
    '            route=EvidenceRoute.FOCUSED,\n            reasons=("provider_identity_expansion",),',
    '            route=EvidenceRoute.PROGRESSIVE,\n            reasons=("provider_identity_expansion",),',
    label="provider progressive",
)
routing = replace_once(
    routing,
    '    if escalation:\n        return RoutingDecision(\n            route=EvidenceRoute.FOCUSED,\n            reasons=tuple(escalation),\n            source_bytes=source_bytes,\n            estimated_direct_chars=direct_chars,\n            aggregate_direct_chars=aggregate_direct_chars,\n            direct_char_budget=direct_budget,\n            previous_executions=hist.executions,\n            source_count=hist.source_count,\n            max_match_records=hist.max_match_records,\n            repeated_evidence_ratio=hist.repeated_evidence_ratio,\n        )\n\n    reasons: list[str] = []',
    '    reasons: list[str] = list(escalation)',
    label="remove focused escalation",
)
routing = replace_once(
    routing,
    '        route=EvidenceRoute.BOUNDED,',
    '        route=EvidenceRoute.PROGRESSIVE,',
    label="progressive default route",
)
routing = replace_once(
    routing,
    '    if match_records >= policy.focused_match_records:\n        next_route = EvidenceRoute.FOCUSED\n    elif decision.route == EvidenceRoute.DIRECT and (\n        truncated or match_records >= policy.bounded_match_records\n    ):\n        next_route = EvidenceRoute.BOUNDED\n    elif decision.route == EvidenceRoute.BOUNDED and truncated:\n        next_route = EvidenceRoute.FOCUSED',
    '    if decision.route == EvidenceRoute.DIRECT and (\n        truncated or match_records >= policy.bounded_match_records\n    ):\n        next_route = EvidenceRoute.PROGRESSIVE',
    label="next progressive route",
)
routing_path.write_text(routing, encoding="utf-8")

contract_path = Path("src/tracecite/runtime/retrieve_contract.py")
contract = contract_path.read_text(encoding="utf-8")
contract = replace_once(
    contract,
    '1. adaptive DIRECT -> BOUNDED -> INVESTIGATE transport;',
    '1. adaptive DIRECT -> PROGRESSIVE transport;',
    label="contract doc modes",
)
contract = contract.replace("def _bounded_decision(", "def _progressive_decision(")
contract = contract.replace("EvidenceRoute.BOUNDED", "EvidenceRoute.PROGRESSIVE")
contract = contract.replace("_bounded_decision(", "_progressive_decision(")
contract = contract.replace("def _bounded_source(", "def _progressive_source(")
contract = contract.replace("_bounded_source(", "_progressive_source(")
contract = replace_once(
    contract,
    'def _bounded_query(\n    request: EvidenceRequest,\n    policy: EvidenceRoutingPolicy,\n    *,\n    route: EvidenceRoute,\n) -> EvidenceRequest:\n    assert isinstance(request.target, QueryTarget)\n    target = request.target\n    if route == EvidenceRoute.FOCUSED:\n        evidence_cap = policy.focused_max_evidence\n        line_cap = policy.focused_max_line_chars\n    else:\n        evidence_cap = policy.bounded_max_evidence\n        line_cap = policy.bounded_max_line_chars',
    'def _progressive_query(\n    request: EvidenceRequest,\n    policy: EvidenceRoutingPolicy,\n    *,\n    decision: RoutingDecision,\n) -> EvidenceRequest:\n    assert isinstance(request.target, QueryTarget)\n    target = request.target\n    deep_progressive = any(\n        reason in {"high_match_cardinality", "exploration_depth", "repeated_evidence", "multiple_sources"}\n        for reason in decision.reasons\n    )\n    if deep_progressive:\n        evidence_cap = policy.focused_max_evidence\n        line_cap = policy.focused_max_line_chars\n    else:\n        evidence_cap = policy.bounded_max_evidence\n        line_cap = policy.bounded_max_line_chars',
    label="progressive query strategy",
)
contract = contract.replace("_bounded_query(request, policy, route=decision.route)", "_progressive_query(request, policy, decision=decision)")
contract = replace_once(
    contract,
    '    if isinstance(request.target, SourceTarget):\n        if decision.route == EvidenceRoute.DIRECT:\n            return _direct_source(request, decision, policy)\n        if decision.route == EvidenceRoute.FOCUSED:\n            return _investigate_source(request, decision, policy)\n        return _progressive_source(request, decision)',
    '    if isinstance(request.target, SourceTarget):\n        if decision.route == EvidenceRoute.DIRECT:\n            return _direct_source(request, decision, policy)\n        deep_progressive = any(\n            reason in {"high_match_cardinality", "exploration_depth", "repeated_evidence", "multiple_sources"}\n            for reason in decision.reasons\n        )\n        if deep_progressive:\n            return _investigate_source(request, decision, policy)\n        return _progressive_source(request, decision)',
    label="source progressive internal strategy",
)
contract_path.write_text(contract, encoding="utf-8")

test_path = Path("tests/test_evidence_routing.py")
test = test_path.read_text(encoding="utf-8")
test = test.replace('== "bounded"', '== "progressive"')
test = test.replace('== "focused"', '== "progressive"')
test = test.replace('EvidenceRoute.FOCUSED.value', 'EvidenceRoute.PROGRESSIVE.value')
test = test.replace('["next_mode"] == "focused"', '["next_mode"] == "progressive"')
test = test.replace('test_after_direct_read_query_becomes_bounded_and_can_escalate', 'test_after_direct_read_query_becomes_progressive')
test = test.replace('test_deep_query_uses_tighter_investigate_transport_cap', 'test_deep_query_uses_tighter_internal_progressive_cap')
test = test.replace('test_large_first_source_uses_bounded_uniform_navigation_sample', 'test_large_first_source_uses_progressive_uniform_navigation_sample')
test = test.replace('test_deep_history_monotonically_escalates_source_inspection_to_investigate', 'test_deep_history_keeps_progressive_mode_with_internal_survey')
# Public output must never expose the retired disclosure names.
test += '''\n\ndef test_public_disclosure_modes_are_only_direct_and_progressive(tmp_path) -> None:\n    source = tmp_path / "routing.log"\n    source.write_text("ERROR one\\nERROR two\\n", encoding="utf-8")\n    state_path = tmp_path / "investigation.json"\n    InvestigationStore(state_path).create("routing contract")\n\n    first = retrieve(\n        EvidenceRequest(SourceTarget(source), investigation_path=state_path),\n        routing_policy=EvidenceRoutingPolicy(fallback_direct_chars=8_000, max_direct_chars=8_000),\n    ).to_dict()\n    second = retrieve(\n        EvidenceRequest(QueryTarget(source, "ERROR", snapshot=False), investigation_path=state_path),\n        routing_policy=EvidenceRoutingPolicy(fallback_direct_chars=8_000, max_direct_chars=8_000),\n    ).to_dict()\n\n    modes = {first["data"]["routing"]["mode"], second["data"]["routing"]["mode"]}\n    assert modes <= {"direct", "progressive"}\n    assert "bounded" not in modes\n    assert "focused" not in modes\n\n\ndef test_legacy_bounded_and_focused_policy_inputs_normalize_to_progressive() -> None:\n    assert EvidenceRoutingPolicy(mode="bounded").mode == "progressive"\n    assert EvidenceRoutingPolicy(mode="focused").mode == "progressive"\n'''
test_path.write_text(test, encoding="utf-8")

print("disclosure mode migration applied")
