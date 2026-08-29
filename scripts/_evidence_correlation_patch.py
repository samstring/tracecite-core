from pathlib import Path

p = Path("src/tracecite/runtime/retrieval_guidance.py")
s = p.read_text()
old = '''        "identifier_only_correlation_safe": False,
        "required_correlation_components": ["scoped_entity", identifier_key],
        "negative_evidence_note": (
'''
new = '''        "identifier_only_correlation_safe": False,
        "required_correlation_components": ["scoped_entity", identifier_key],
        "unsafe_correlation_key": [identifier_key],
        "minimum_safe_correlation_key": ["scoped_entity", identifier_key],
        "scope_fanout_observed": sibling_count > 1,
        "negative_evidence_note": (
'''
if old not in s:
    raise SystemExit("retrieval contract anchor not found")
s = s.replace(old, new, 1)
p.write_text(s)

p = Path("benchmarks/agent-investigation/gmi_canonical_host.py")
s = p.read_text()
s = s.replace(
    '_NAVIGATION_PROMPT_MARKER = "TRACECITE_COVERAGE_REQUIRED"\n',
    '_NAVIGATION_PROMPT_MARKER = "TRACECITE_COVERAGE_REQUIRED"\n'
    '_CONSTRAINT_PROMPT_MARKER = "TRACECITE_CONSTRAINT_REQUIRED"\n',
    1,
)
s = s.replace(
    '_PROMPTED_ACTIONS: set[tuple[str, str, str]] = set()\n',
    '_PROMPTED_ACTIONS: set[tuple[str, str, str]] = set()\n'
    '_PROMPTED_CONSTRAINTS: set[tuple[str, str, str]] = set()\n',
    1,
)
s = s.replace(
    '        if _ACTION_PROMPT_MARKER in content or _NAVIGATION_PROMPT_MARKER in content:\n',
    '        if (\n'
    '            _ACTION_PROMPT_MARKER in content\n'
    '            or _NAVIGATION_PROMPT_MARKER in content\n'
    '            or _CONSTRAINT_PROMPT_MARKER in content\n'
    '        ):\n',
    1,
)

anchor = '''def _tool_call_signature(call: Mapping[str, Any]) -> tuple[str, str, str] | None:
'''
insert = r'''def _integrity_constraint_from_tool_output(output: Any) -> dict[str, Any] | None:
    """Return one completed Runtime-owned correlation-safety invariant.

    This is evidence integrity only. It never says a collision happened and
    never chooses a root-cause hypothesis.
    """

    payload = _tool_output_payload(output)
    if payload is None:
        return None
    data = payload.get("data") or {}
    if not isinstance(data, Mapping):
        return None
    if isinstance(data.get("actionable_retrieval"), Mapping):
        return None
    for raw in data.get("correlation_constraints") or []:
        if not isinstance(raw, Mapping):
            continue
        if str(raw.get("kind") or "") != "scoped_local_identifier":
            continue
        if raw.get("identifier_only_correlation_safe") is not False:
            continue
        identifier_key = str(raw.get("identifier_key") or "").strip()
        identifier_value = str(raw.get("identifier_value") or "").strip()
        if not identifier_key or not identifier_value:
            continue
        sibling_count = int(raw.get("sibling_entity_count_observed") or 0)
        if sibling_count < 2:
            continue
        required = [
            str(item).strip()
            for item in raw.get("minimum_safe_correlation_key")
            or raw.get("required_correlation_components")
            or []
            if str(item).strip()
        ]
        entities = [
            str(item).strip()
            for item in raw.get("scoped_entities") or []
            if str(item).strip()
        ]
        return {
            "source": str((data.get("evidence_source") or {}).get("path") or "").strip(),
            "identifier_key": identifier_key,
            "identifier_value": identifier_value,
            "source_uniqueness": str(raw.get("source_uniqueness") or "unverified"),
            "required_correlation_components": required,
            "scoped_entities": entities,
            "sibling_entity_count_observed": sibling_count,
        }
    return None


def _constraint_signature(constraint: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(constraint.get("source") or "").strip(),
        str(constraint.get("identifier_key") or "").strip(),
        str(constraint.get("identifier_value") or "").strip(),
    )


def _constraint_prompt(constraint: Mapping[str, Any]) -> str:
    signature = "|".join(_constraint_signature(constraint))
    required = ", ".join(constraint.get("required_correlation_components") or [])
    observed = ", ".join(constraint.get("scoped_entities") or [])
    sibling_count = int(constraint.get("sibling_entity_count_observed") or 0)
    uniqueness = str(constraint.get("source_uniqueness") or "unverified")
    return (
        f"{_CONSTRAINT_PROMPT_MARKER} {signature}\n"
        "The canonical Runtime has completed its deterministic identity-evidence ladder and reports "
        "a correlation-safety constraint. This does NOT identify a root cause. Before concluding, "
        "explicitly test your causal hypothesis against this invariant: "
        f"{constraint['identifier_key']}={constraint['identifier_value']!r} is not safe as an "
        f"identifier-only correlation key (source uniqueness={uniqueness}); the minimum safe "
        f"correlation key is [{required}]. The source also contains {sibling_count} sibling scoped "
        f"entities in the same family"
        + (f", including [{observed}]" if observed else "")
        + ". Do not assume global identifier uniqueness. If your hypothesis involves lookup, routing, "
        "ownership, or correlation, distinguish identifier-only behavior from scope-preserving behavior "
        "and label any causal step as inference unless directly observed."
    )


def _pending_constraint_review(
    messages: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    pending: dict[str, Any] | None = None
    for message in messages:
        if str(message.get("role") or "") != "tool":
            continue
        constraint = _integrity_constraint_from_tool_output(message.get("content") or "")
        if constraint is not None:
            pending = constraint
    if pending is None:
        return None
    signature = _constraint_signature(pending)
    marker = f"{_CONSTRAINT_PROMPT_MARKER} {'|'.join(signature)}"
    if signature in _PROMPTED_CONSTRAINTS:
        return None
    if any(
        str(item.get("role") or "") == "user"
        and marker in str(item.get("content") or "")
        for item in messages
    ):
        return None
    return pending


def _apply_constraint_policy(
    payload: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    request = dict(payload)
    raw_messages = payload.get("messages") or []
    if not isinstance(raw_messages, list) or not payload.get("tools"):
        return request, None
    messages = [dict(item) for item in raw_messages if isinstance(item, Mapping)]
    if len(messages) != len(raw_messages):
        return request, None
    constraint = _pending_constraint_review(messages)
    if constraint is None:
        return request, None

    signature = _constraint_signature(constraint)
    _PROMPTED_CONSTRAINTS.add(signature)
    messages.append({"role": "user", "content": _constraint_prompt(constraint)})
    request["messages"] = messages
    return request, {
        "type": "protocol",
        "event": "require_correlation_constraint_review",
        "source": constraint.get("source") or "",
        "identifier_key": constraint["identifier_key"],
        "identifier_value": constraint["identifier_value"],
        "source_uniqueness": constraint.get("source_uniqueness") or "unverified",
        "required_correlation_components": constraint.get("required_correlation_components") or [],
        "sibling_entity_count_observed": constraint.get("sibling_entity_count_observed") or 0,
    }


'''
if anchor not in s:
    raise SystemExit("host signature anchor not found")
s = s.replace(anchor, insert + anchor, 1)

old = '''    request_payload, action_event = _apply_action_policy(payload)
    if action_event is None:
        request_payload, stop_event = _apply_stop_policy(request_payload)
    else:
        # Give a newly surfaced Runtime-owned mechanical action one model turn
        # before applying the exploration safety cap. If the model ignores the
        # one-time prompt, the normal cap applies on the following request.
        stop_event = None
    if transcript_value:
        transcript = Path(transcript_value)
        if action_event is not None:
            common._append_event(transcript, action_event)
        if stop_event is not None:
            common._append_event(transcript, stop_event)
'''
new = '''    request_payload, action_event = _apply_action_policy(payload)
    constraint_event = None
    if action_event is None:
        request_payload, constraint_event = _apply_constraint_policy(request_payload)
    if action_event is None and constraint_event is None:
        request_payload, stop_event = _apply_stop_policy(request_payload)
    else:
        # Give a newly surfaced Runtime-owned mechanical action/constraint one
        # model turn before applying the exploration safety cap. If the model
        # ignores the one-time prompt, the normal cap applies next request.
        stop_event = None
    if transcript_value:
        transcript = Path(transcript_value)
        if action_event is not None:
            common._append_event(transcript, action_event)
        if constraint_event is not None:
            common._append_event(transcript, constraint_event)
        if stop_event is not None:
            common._append_event(transcript, stop_event)
'''
if old not in s:
    raise SystemExit("post chat anchor not found")
s = s.replace(old, new, 1)
p.write_text(s)

p = Path("tests/test_retrieval_guidance.py")
s = p.read_text()
old = '''    assert contract["required_correlation_components"] == ["scoped_entity", "resourceID"]
    assert "does not prove" in contract["negative_evidence_note"]
'''
new = '''    assert contract["required_correlation_components"] == ["scoped_entity", "resourceID"]
    assert contract["unsafe_correlation_key"] == ["resourceID"]
    assert contract["minimum_safe_correlation_key"] == ["scoped_entity", "resourceID"]
    assert contract["scope_fanout_observed"] is True
    assert "does not prove" in contract["negative_evidence_note"]
'''
if old not in s:
    raise SystemExit("retrieval test anchor not found")
s = s.replace(old, new, 1)
p.write_text(s)

p = Path("tests/test_gmi_canonical_host.py")
s = p.read_text()
marker = "def test_completed_identity_constraint_requires_one_review_turn"
if marker not in s:
    s += r'''


def test_completed_identity_constraint_requires_one_review_turn(tmp_path: Path) -> None:
    output = _run_host_script(
        tmp_path,
        "host._PROMPTED_CONSTRAINTS.clear()\n"
        "constraint = {'kind':'scoped_local_identifier','identifier_key':'resourceID','identifier_value':'local-device','source_uniqueness':'unverified','identifier_only_correlation_safe':False,'required_correlation_components':['scoped_entity','resourceID'],'minimum_safe_correlation_key':['scoped_entity','resourceID'],'scoped_entities':['vendor.example/device-run-3083'],'sibling_entity_count_observed':5}\n"
        "tool_payload = {'status':'ok','data':{'evidence_source':{'path':'/tmp/inputs/runtime.log'},'correlation_constraints':[constraint]},'missing_evidence':[{'kind':'scope_uniqueness_unverified','actionable':False}]}\n"
        "messages = [{'role':'user','content':'Why did the update target the wrong object?'},{'role':'assistant','content':'','tool_calls':[{'id':'1'}]},{'role':'tool','content':json.dumps(tool_payload)}]\n"
        "request, event = host._apply_constraint_policy({'messages':messages,'tools':[{'type':'function'}],'tool_choice':'auto'})\n"
        "assert event is not None and event['event'] == 'require_correlation_constraint_review'\n"
        "prompt = request['messages'][-1]['content']\n"
        "assert 'TRACECITE_CONSTRAINT_REQUIRED' in prompt\n"
        "assert 'minimum safe correlation key is [scoped_entity, resourceID]' in prompt\n"
        "assert 'does NOT identify a root cause' in prompt\n"
        "second, second_event = host._apply_constraint_policy({'messages':messages,'tools':[{'type':'function'}],'tool_choice':'auto'})\n"
        "assert second_event is None\n"
        "print('ok')\n",
    )
    assert output.strip() == "ok"


def test_constraint_review_waits_until_runtime_action_is_closed(tmp_path: Path) -> None:
    output = _run_host_script(
        tmp_path,
        "host._PROMPTED_CONSTRAINTS.clear()\n"
        "constraint = {'kind':'scoped_local_identifier','identifier_key':'resourceID','identifier_value':'local-device','source_uniqueness':'unverified','identifier_only_correlation_safe':False,'required_correlation_components':['scoped_entity','resourceID'],'sibling_entity_count_observed':5}\n"
        "tool_payload = {'status':'ok','data':{'actionable_retrieval':{'operation':'search','source':'runtime.log','query':'local-device'},'correlation_constraints':[constraint]}}\n"
        "assert host._integrity_constraint_from_tool_output(json.dumps(tool_payload)) is None\n"
        "print('ok')\n",
    )
    assert output.strip() == "ok"
'''
p.write_text(s)
