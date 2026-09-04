from pathlib import Path
import re


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"missing expected block: {label}")
    return text.replace(old, new, 1)


# 1) Public result contract: budget exhaustion is a first-class stop signal.
schema_path = Path("src/tracecite/runtime/schema.py")
schema = schema_path.read_text(encoding="utf-8")
schema = replace_once(
    schema,
    'RESULT_STATUSES = frozenset({"ok", "no_match", "partial", "error"})',
    'RESULT_STATUSES = frozenset({"ok", "no_match", "partial", "error", "budget_exhausted"})',
    label="result statuses",
)
schema = replace_once(
    schema,
    '    error: Optional[Dict[str, Any]] = None\n',
    '    error: Optional[Dict[str, Any]] = None\n    should_stop: bool = False\n',
    label="AgentResult should_stop field",
)
schema = replace_once(
    schema,
    '        if self.error:\n            payload["error"] = dict(self.error)\n        return payload',
    '        if self.error:\n            payload["error"] = dict(self.error)\n        if self.should_stop:\n            payload["should_stop"] = True\n        return payload',
    label="AgentResult should_stop output",
)
schema_path.write_text(schema, encoding="utf-8")


# 2) Replace the public BudgetPolicy with two user-facing knobs. Legacy keys are
# accepted only as migration input; old dimension-specific caps no longer enforce.
inv_path = Path("src/tracecite/runtime/investigation.py")
inv = inv_path.read_text(encoding="utf-8")
inv = inv.replace("BUDGET_POLICY_SCHEMA_VERSION = 1", "BUDGET_POLICY_SCHEMA_VERSION = 2", 1)
insert_after = 'BUDGET_RESERVATION_FIELDS = BUDGET_USAGE_FIELDS\n'
inv = replace_once(
    inv,
    insert_after,
    insert_after + 'DEFAULT_MAX_ROUNDS = 64\nDEFAULT_MAX_INPUT_PER_ROUND = 128_000\nLEGACY_BUDGET_LIMIT_FIELDS = BUDGET_LIMIT_FIELDS\n',
    label="budget defaults",
)

pattern = re.compile(r'@dataclass\(frozen=True\)\nclass BudgetPolicy:.*?\n\ndef _empty_budget_usage\(\)', re.S)
match = pattern.search(inv)
if not match:
    raise RuntimeError("BudgetPolicy block not found")
new_policy = '''@dataclass(frozen=True, init=False)
class BudgetPolicy:
    """Two-dimensional user budget for an Agent investigation.

    ``max_rounds`` bounds how many Runtime calls may be attempted.  A round is
    one linked Runtime operation. ``max_input_per_round`` bounds the serialized
    Agent-visible result for any one round. Defaults are intentionally generous
    but finite.

    Legacy v1 budget keys are accepted only to read existing callers/state.
    ``max_executions`` maps to ``max_rounds``; all other old per-dimension limits
    are ignored because they are no longer user budget concepts.
    """

    schema_version: int
    max_rounds: int
    max_input_per_round: int

    def __init__(
        self,
        schema_version: int = BUDGET_POLICY_SCHEMA_VERSION,
        max_rounds: Optional[int] = None,
        max_input_per_round: Optional[int] = None,
        **legacy: Any,
    ) -> None:
        if isinstance(schema_version, bool) or not isinstance(schema_version, int):
            raise InvestigationError("budget_policy.schema_version 必须是整数")
        if schema_version not in {1, BUDGET_POLICY_SCHEMA_VERSION}:
            raise InvestigationError(f"不支持 budget policy schema {schema_version!r}")
        unsupported = set(legacy) - set(LEGACY_BUDGET_LIMIT_FIELDS)
        if unsupported:
            raise InvestigationError(
                "budget_policy 含有不支持的字段: "
                + ", ".join(sorted(str(item) for item in unsupported))
            )
        if max_rounds is None and legacy.get("max_executions") not in {None, ""}:
            max_rounds = legacy.get("max_executions")
        rounds = DEFAULT_MAX_ROUNDS if max_rounds is None else max_rounds
        input_cap = (
            DEFAULT_MAX_INPUT_PER_ROUND
            if max_input_per_round is None
            else max_input_per_round
        )
        _positive_limit(rounds, field_name="budget_policy.max_rounds")
        _positive_limit(input_cap, field_name="budget_policy.max_input_per_round")
        object.__setattr__(self, "schema_version", BUDGET_POLICY_SCHEMA_VERSION)
        object.__setattr__(self, "max_rounds", int(rounds))
        object.__setattr__(self, "max_input_per_round", int(input_cap))

    @classmethod
    def from_mapping(cls, raw: Optional[Mapping[str, Any]]) -> "BudgetPolicy":
        if raw is None:
            return cls()
        if not isinstance(raw, Mapping):
            raise InvestigationError("budget_policy 必须是对象或 null")
        allowed = {
            "schema_version",
            "max_rounds",
            "max_input_per_round",
            *LEGACY_BUDGET_LIMIT_FIELDS,
        }
        unsupported = set(raw) - allowed
        if unsupported:
            raise InvestigationError(
                "budget_policy 含有不支持的字段: "
                + ", ".join(sorted(str(item) for item in unsupported))
            )
        kwargs = dict(raw)
        return cls(**kwargs)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": BUDGET_POLICY_SCHEMA_VERSION,
            "max_rounds": self.max_rounds,
            "max_input_per_round": self.max_input_per_round,
        }

    def remaining(self, usage: Mapping[str, Any]) -> Dict[str, int]:
        rounds_used = int(usage.get("executions") or 0)
        return {
            "rounds": max(0, self.max_rounds - rounds_used),
            "input_per_round": self.max_input_per_round,
        }


def _empty_budget_usage()'''
inv = inv[:match.start()] + new_policy + inv[match.end():]

# Replace reserve enforcement loop with max_rounds only.
old_reserve_loop = '''            violations: List[Dict[str, Any]] = []
            for limit_name, usage_name in zip(BUDGET_LIMIT_FIELDS, BUDGET_USAGE_FIELDS):
                limit = getattr(policy, limit_name)
                exhausted_elapsed = (
                    usage_name == "elapsed_seconds"
                    and float(limit or 0) <= float(usage[usage_name])
                    and float(requested["executions"]) > 0
                )
                if limit is not None and (
                    projected[usage_name] > float(limit) or exhausted_elapsed
                ):
                    violations.append(
                        {
                            "limit": limit_name,
                            "usage": usage[usage_name],
                            "requested": requested[usage_name],
                            "maximum": limit,
                            "remaining": policy.remaining(usage).get(usage_name),
                        }
                    )'''
new_reserve_loop = '''            violations: List[Dict[str, Any]] = []
            if projected["executions"] > float(policy.max_rounds):
                violations.append(
                    {
                        "limit": "max_rounds",
                        "usage": int(usage["executions"]),
                        "requested": int(requested["executions"]),
                        "maximum": policy.max_rounds,
                        "remaining": policy.remaining(usage)["rounds"],
                    }
                )'''
inv = replace_once(inv, old_reserve_loop, new_reserve_loop, label="reserve enforcement")

# Finalization accepts one non-persisted per-round input measurement and enforces it.
old_actual = '''        actual_values = self._budget_request(
            executions=int(actual.get("executions", 1)),
            searches=int(actual.get("searches", 0)),
            queries=int(actual.get("queries", 0)),
            recorded_evidence_pointers=int(actual.get("recorded_evidence_pointers", 0)),
            expand_requested_chars=int(actual.get("expand_requested_chars", 0)),
            expand_returned_chars=int(actual.get("expand_returned_chars", 0)),
            elapsed_seconds=float(actual.get("elapsed_seconds", 0.0)),
        )'''
new_actual = '''        input_returned_chars = int(actual.get("input_returned_chars", 0))
        if input_returned_chars < 0:
            raise InvestigationError("input_returned_chars 必须是非负整数")
        actual_values = self._budget_request(
            executions=int(actual.get("executions", 1)),
            searches=int(actual.get("searches", 0)),
            queries=int(actual.get("queries", 0)),
            recorded_evidence_pointers=int(actual.get("recorded_evidence_pointers", 0)),
            expand_requested_chars=int(actual.get("expand_requested_chars", 0)),
            expand_returned_chars=int(actual.get("expand_returned_chars", 0)),
            elapsed_seconds=float(actual.get("elapsed_seconds", 0.0)),
        )'''
inv = replace_once(inv, old_actual, new_actual, label="finalize input measurement")
old_finalize_loop = '''            violations: List[str] = []
            for limit_name, usage_name in zip(BUDGET_LIMIT_FIELDS, BUDGET_USAGE_FIELDS):
                limit = getattr(policy, limit_name)
                if limit is not None and float(usage[usage_name]) > float(limit):
                    violations.append(limit_name)
            if violations and state.status == "active":
                state.status = "completed"
                state.stop_reason = self._bounded_end_reason(
                    "执行后测量值超过调查预算: " + ", ".join(violations)
                )'''
new_finalize_loop = '''            violations: List[str] = []
            if int(usage["executions"]) > policy.max_rounds:
                violations.append("max_rounds")
            if input_returned_chars > policy.max_input_per_round:
                violations.append("max_input_per_round")
            if violations and state.status == "active":
                state.status = "completed"
                state.stop_reason = self._bounded_end_reason(
                    "执行后测量值超过调查预算: " + ", ".join(violations)
                )'''
inv = replace_once(inv, old_finalize_loop, new_finalize_loop, label="finalize enforcement")
inv_path.write_text(inv, encoding="utf-8")


# 3) Runtime projection: measure one round's complete Agent-visible result and
# replace oversized output with a deterministic stop signal. Never auto-retry.
acq_path = Path("src/tracecite/runtime/acquisition.py")
acq = acq_path.read_text(encoding="utf-8")
old_budget_error = '''def _budget_error(operation: str, exc: BudgetExhausted) -> Dict[str, Any]:
    payload = _error(operation, exc)
    payload["error"] = {
        "type": type(exc).__name__,
        "message": str(exc),
        "budget": dict(exc.details),
    }
    data = dict(payload.get("data") or {})
    data["budget"] = {
        "status": "exhausted",
        **dict(exc.details),
    }
    data["stop_reason"] = {"kind": "budget_exhausted", "detail": str(exc)}
    payload["data"] = data
    return payload'''
new_budget_error = '''def _budget_error(operation: str, exc: BudgetExhausted) -> Dict[str, Any]:
    details = dict(exc.details)
    return AgentResult(
        operation=operation,
        status="budget_exhausted",
        outcome="unknown",
        should_stop=True,
        error={
            "type": type(exc).__name__,
            "message": str(exc),
            "budget": details,
        },
        data={
            "budget": {"status": "exhausted", **details},
            "stop_reason": {"kind": "budget_exhausted", "detail": str(exc)},
        },
    ).to_dict()'''
acq = replace_once(acq, old_budget_error, new_budget_error, label="budget error envelope")

old_usage_tail = '''        "expand_returned_chars": len(str(text)) if operation == "expand" and text is not None else 0,
    }
    return usage'''
new_usage_tail = '''        "expand_returned_chars": len(str(text)) if operation == "expand" and text is not None else 0,
        "input_returned_chars": len(
            json.dumps(result, ensure_ascii=False, sort_keys=True, default=str)
        ),
    }
    return usage'''
acq = replace_once(acq, old_usage_tail, new_usage_tail, label="input chars measurement")

old_record = '''            if budget_status.get("violations"):
                data["stop_reason"] = budget_status.get("stop_reason")
            payload["data"] = data
        except InvestigationError as exc:
            payload = _error(operation, exc)'''
new_record = '''            if budget_status.get("violations"):
                detail = str((budget_status.get("stop_reason") or {}).get("detail") or "budget exhausted")
                return _budget_error(
                    operation,
                    BudgetExhausted(detail, details=budget_status),
                )
            payload["data"] = data
        except InvestigationError as exc:
            payload = _error(operation, exc)'''
acq = replace_once(acq, old_record, new_record, label="post-result budget stop")
acq_path.write_text(acq, encoding="utf-8")


# 4) Rewrite budget tests to the new public contract while keeping cache tests.
test_path = Path("tests/test_budget_cache.py")
test = test_path.read_text(encoding="utf-8")
start = test.index("def test_budget_policy_is_strict_and_optional")
end = test.index("def test_probe_cache_hit_records_fresh_execution_and_no_raw_body")
replacement = '''def test_budget_policy_exposes_only_rounds_and_input_size(tmp_path: Path) -> None:
    path, store = _state(
        tmp_path,
        BudgetPolicy(max_rounds=2, max_input_per_round=10_000),
    )
    status = store.budget_status()
    assert status["policy"] == {
        "schema_version": 2,
        "max_rounds": 2,
        "max_input_per_round": 10_000,
    }
    assert status["usage"]["executions"] == 0
    assert status["remaining"]["rounds"] == 2
    assert status["remaining"]["input_per_round"] == 10_000
    assert json.loads(path.read_text(encoding="utf-8"))["budget_policy"]["schema_version"] == 2
    with pytest.raises(Exception):
        BudgetPolicy(max_rounds=0)
    with pytest.raises(Exception):
        BudgetPolicy.from_mapping({"max_rounds": 1, "unexpected": 2})


def test_legacy_execution_budget_maps_to_rounds_and_other_legacy_caps_are_not_public() -> None:
    policy = BudgetPolicy(
        schema_version=1,
        max_executions=3,
        max_searches=1,
        max_queries=1,
        max_recorded_evidence_pointers=1,
        max_expand_requested_chars=10,
        max_expand_returned_chars=10,
        max_elapsed_seconds=1,
    )
    assert policy.max_rounds == 3
    assert set(policy.to_dict()) == {"schema_version", "max_rounds", "max_input_per_round"}


def test_round_budget_refusal_returns_terminal_stop_without_recording_execution(tmp_path: Path) -> None:
    _path, store = _state(tmp_path, BudgetPolicy(max_rounds=1))
    reservation = store.reserve_budget("probe")
    reservation.finalize({"executions": 1, "input_returned_chars": 100})
    with pytest.raises(BudgetExhausted) as caught:
        store.reserve_budget("probe")
    assert caught.value.details["violations"][0]["limit"] == "max_rounds"
    loaded = store.load()
    assert loaded.status == "completed"
    assert loaded.stop_reason["kind"] == "budget_exhausted"
    assert loaded.executions == []


def test_round_reservations_are_concurrency_safe(tmp_path: Path) -> None:
    _path, store = _state(tmp_path, BudgetPolicy(max_rounds=1))
    results: list[str] = []
    reservations = []
    lock = threading.Lock()

    def reserve() -> None:
        try:
            item = store.reserve_budget("probe")
            with lock:
                reservations.append(item)
                results.append("reserved")
        except BudgetExhausted:
            with lock:
                results.append("refused")

    threads = [threading.Thread(target=reserve) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(results) == ["refused", "reserved"]
    reservations[0].finalize({"executions": 1, "input_returned_chars": 10})
    assert store.budget_status()["usage"]["executions"] == 1


def test_runtime_round_exhaustion_returns_budget_exhausted_and_should_stop(tmp_path: Path) -> None:
    source = tmp_path / "source.log"
    source.write_text("one\\n", encoding="utf-8")
    state_path, _store = _state(tmp_path, BudgetPolicy(max_rounds=1))
    first = probe(source, investigation_path=state_path)
    assert first["status"] == "ok"
    refused = probe(source, investigation_path=state_path)
    assert refused["status"] == "budget_exhausted"
    assert refused["should_stop"] is True
    assert refused["data"]["stop_reason"]["kind"] == "budget_exhausted"


def test_runtime_input_budget_stops_oversized_round(tmp_path: Path) -> None:
    source = tmp_path / "source.log"
    source.write_text("x" * 4_000 + "\\n", encoding="utf-8")
    state_path, store = _state(
        tmp_path,
        BudgetPolicy(max_rounds=4, max_input_per_round=500),
    )
    result = expand(source, start_line=1, investigation_path=state_path)
    assert result["status"] == "budget_exhausted"
    assert result["should_stop"] is True
    assert result["data"]["stop_reason"]["kind"] == "budget_exhausted"
    assert store.load().status == "completed"


'''
test = test[:start] + replacement + test[end:]

# Old tests that asserted dimension-specific budget refusal now contradict the v2
# contract. Replace them with compatibility assertions that those legacy caps do
# not gate execution.
for name in [
    "test_search_pointer_budget_refuses_before_scan_when_cap_is_below_result_bound",
    "test_non_snapshot_raw_tools_do_not_reserve_immutable_pointer_budget",
    "test_run_reserves_worst_case_evidence_cap_before_extension",
    "test_elapsed_limit_at_boundary_refuses_next_execution",
]:
    marker = f"def {name}"
    if marker in test:
        s = test.index(marker)
        next_def = test.find("\ndef ", s + 4)
        next_param = test.find("\n@pytest", s + 4)
        candidates = [x for x in (next_def, next_param) if x != -1]
        e = min(candidates) if candidates else len(test)
        test = test[:s] + test[e + (1 if e < len(test) and test[e] == '\n' else 0):]

test += '''\n\ndef test_legacy_dimension_specific_limits_do_not_gate_runtime(tmp_path: Path) -> None:\n    source = tmp_path / "source.log"\n    source.write_text("target\\n", encoding="utf-8")\n    state_path, _store = _state(\n        tmp_path,\n        BudgetPolicy(\n            max_rounds=3,\n            max_searches=1,\n            max_recorded_evidence_pointers=1,\n            max_elapsed_seconds=0.001,\n        ),\n    )\n    assert search(source, "target", investigation_path=state_path)["status"] == "ok"\n    assert search(source, "target", investigation_path=state_path)["status"] == "ok"\n'''
test_path.write_text(test, encoding="utf-8")

print("budget model migration applied")
