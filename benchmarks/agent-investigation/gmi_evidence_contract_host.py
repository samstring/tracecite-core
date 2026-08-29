from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

import gmi_canonical_host as canonical
import gmi_host as base
import openai_host as common
from tracecite.runtime import (
    EvidenceRequest,
    InvestigationStore,
    QueryTarget,
    RangeTarget,
    SourceTarget,
    assess_test,
    latest_test_assessments,
    retrieve,
)


_CLOSURE_TOOL_NAMES = frozenset(
    {
        "tracecite_hypothesis",
        "tracecite_test",
        "tracecite_assess_test",
        "tracecite_finding",
        "tracecite_state",
    }
)
_EPISTEMIC_CLOSURE_PROMPT = (
    "Mechanical evidence acquisition has reached its configured limit, but the investigation "
    "does not yet contain a Finding. Do not retrieve more evidence. Use the remaining "
    "investigation-state tools to account for the hypothesis and declared Tests. A decisive "
    "Finding is allowed only when every declared Test has an evidence-backed assessment; "
    "otherwise record an unknown Finding. Never upgrade retrieval exhaustion into proof."
)
_ORIGINAL_STOP_POLICY = canonical._apply_stop_policy
_ORIGINAL_TRANSPORT = canonical._ORIGINAL_POST_CHAT


def _investigation_path() -> Path | None:
    scratch = os.environ.get("TRACECITE_BENCH_SCRATCH", "").strip()
    if not scratch:
        return None
    return Path(scratch).resolve() / "canonical-investigation.json"


def _state_has_finding() -> bool:
    path = _investigation_path()
    if path is None or not path.is_file():
        return False
    try:
        return bool(InvestigationStore(path).load().findings)
    except Exception:
        return False


def _tool_name(tool: Mapping[str, Any]) -> str:
    if "name" in tool:
        return str(tool.get("name") or "")
    function = tool.get("function") or {}
    return str(function.get("name") or "") if isinstance(function, Mapping) else ""


def _closure_only_stop_policy(
    payload: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    request, event = _ORIGINAL_STOP_POLICY(payload)
    if event is None or _state_has_finding():
        return request, event

    raw_messages = payload.get("messages") or []
    raw_tools = payload.get("tools") or []
    messages = [dict(item) for item in raw_messages if isinstance(item, Mapping)]
    tools = [
        dict(item)
        for item in raw_tools
        if isinstance(item, Mapping) and _tool_name(item) in _CLOSURE_TOOL_NAMES
    ]
    if not tools:
        return request, event

    last = messages[-1] if messages else {}
    last_content = str(last.get("content") or "") if last.get("role") == "user" else ""
    if "Mechanical evidence acquisition has reached" not in last_content:
        messages.append({"role": "user", "content": _EPISTEMIC_CLOSURE_PROMPT})

    request = dict(payload)
    request["messages"] = messages
    request["tools"] = tools
    request["tool_choice"] = "required"
    replacement = dict(event)
    replacement["event"] = "force_epistemic_closure"
    replacement["finding_present"] = False
    replacement["closure_tools"] = sorted(_CLOSURE_TOOL_NAMES)
    return request, replacement


def _required_tool_transport(payload: Mapping[str, Any]) -> dict[str, Any]:
    request = dict(payload)
    if request.get("tools") and not _state_has_finding():
        request["tool_choice"] = "required"
    return _ORIGINAL_TRANSPORT(request)


canonical._apply_stop_policy = _closure_only_stop_policy
canonical._ORIGINAL_POST_CHAT = _required_tool_transport


class EvidenceContractRuntime(canonical.CanonicalRuntime):
    """Canonical evidence Runtime plus explicit investigation-state closure."""

    @property
    def _store(self) -> InvestigationStore:
        return InvestigationStore(self._investigation_path)

    def _links(self, args: Mapping[str, Any]) -> tuple[str | None, str | None]:
        hypothesis_id = str(args.get("hypothesis_id") or "").strip() or None
        test_id = str(args.get("test_id") or "").strip() or None
        if test_id is None:
            return hypothesis_id, None
        state = self._store.load()
        test = next(
            (item for item in state.tests if str(item.get("id") or "") == test_id),
            None,
        )
        if test is None:
            raise ValueError(f"unknown test_id: {test_id}")
        owner = str(test.get("hypothesis_id") or "").strip()
        if hypothesis_id is not None and hypothesis_id != owner:
            raise ValueError(
                f"test_id {test_id} belongs to hypothesis {owner}, not {hypothesis_id}"
            )
        return owner, test_id

    def _tracecite_hypothesis(self, args: Mapping[str, Any]) -> str:
        claim = str(args.get("claim") or "").strip()
        if not claim:
            raise ValueError("claim must be non-empty")
        hypothesis_id = str(args.get("hypothesis_id") or "").strip() or None
        rationale = str(args.get("rationale") or "").strip()
        row = self._store.add_hypothesis(
            claim,
            hypothesis_id=hypothesis_id,
            rationale=rationale,
        )
        return json.dumps(row, ensure_ascii=False, sort_keys=True)

    def _tracecite_test(self, args: Mapping[str, Any]) -> str:
        hypothesis_id = str(args.get("hypothesis_id") or "").strip()
        intent = str(args.get("intent") or "").strip()
        expected = str(args.get("expected_observation") or "").strip()
        contradicting = str(args.get("contradicting_observation") or "").strip()
        test_id = str(args.get("test_id") or "").strip() or None
        if not all((hypothesis_id, intent, expected, contradicting)):
            raise ValueError(
                "hypothesis_id, intent, expected_observation and contradicting_observation are required"
            )
        row = self._store.add_test(
            hypothesis_id,
            intent,
            expected_observation=expected,
            contradicting_observation=contradicting,
            test_id=test_id,
        )
        return json.dumps(row, ensure_ascii=False, sort_keys=True)

    def _tracecite_assess_test(self, args: Mapping[str, Any]) -> str:
        test_id = str(args.get("test_id") or "").strip()
        outcome = str(args.get("outcome") or "").strip().lower()
        raw_refs = args.get("evidence_refs") or []
        if isinstance(raw_refs, (str, bytes)) or not isinstance(raw_refs, Sequence):
            raise ValueError("evidence_refs must be an array")
        refs = [str(item).strip() for item in raw_refs if str(item).strip()]
        row = assess_test(
            self._store,
            test_id,
            outcome,
            evidence_refs=refs,
        )
        return json.dumps(row, ensure_ascii=False, sort_keys=True)

    def _tracecite_finding(self, args: Mapping[str, Any]) -> str:
        hypothesis_id = str(args.get("hypothesis_id") or "").strip()
        outcome = str(args.get("outcome") or "").strip().lower()
        summary = str(args.get("summary") or "").strip()
        support = args.get("supporting_evidence") or []
        contradiction = args.get("contradicting_evidence") or []
        limitations = args.get("limitations") or []
        for name, value in (
            ("supporting_evidence", support),
            ("contradicting_evidence", contradiction),
            ("limitations", limitations),
        ):
            if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
                raise ValueError(f"{name} must be an array")
        row = self._store.add_finding(
            hypothesis_id,
            outcome,
            summary,
            supporting_evidence=[str(item).strip() for item in support if str(item).strip()],
            contradicting_evidence=[
                str(item).strip() for item in contradiction if str(item).strip()
            ],
            limitations=[str(item).strip() for item in limitations if str(item).strip()],
        )
        return json.dumps(row, ensure_ascii=False, sort_keys=True)

    def _tracecite_state(self, _args: Mapping[str, Any]) -> str:
        state = self._store.load()
        assessments = latest_test_assessments(state, "")
        # latest_test_assessments is hypothesis-scoped; construct a bounded all-test view here.
        all_assessments: dict[str, str] = {}
        for hypothesis in state.hypotheses:
            hypothesis_id = str(hypothesis.get("id") or "")
            for test_id, execution in latest_test_assessments(state, hypothesis_id).items():
                all_assessments[test_id] = str(execution.get("outcome") or "unknown")
        payload = {
            "hypotheses": [
                {
                    "id": item.get("id"),
                    "status": item.get("status"),
                    "test_ids": list(item.get("test_ids") or []),
                }
                for item in state.hypotheses
            ],
            "tests": [
                {
                    "id": item.get("id"),
                    "hypothesis_id": item.get("hypothesis_id"),
                    "assessment": all_assessments.get(str(item.get("id") or ""), "unassessed"),
                    "execution_count": len(item.get("execution_ids") or []),
                }
                for item in state.tests
            ],
            "findings": [
                {
                    "id": item.get("id"),
                    "hypothesis_id": item.get("hypothesis_id"),
                    "outcome": item.get("outcome"),
                }
                for item in state.findings
            ],
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    def _tracecite_inspect(self, args: Mapping[str, Any]) -> str:
        file_name = str(args.get("file") or "")
        if not file_name:
            raise ValueError("file must be non-empty")
        path = common._safe_input(self.input_root, file_name)
        hypothesis_id, test_id = self._links(args)
        result = retrieve(
            EvidenceRequest(
                SourceTarget(path),
                investigation_path=self._investigation_path,
                hypothesis_id=hypothesis_id,
                test_id=test_id,
                cache=True,
            )
        )
        return self._render(result)

    def _tracecite_search(self, args: Mapping[str, Any]) -> str:
        file_name = str(args.get("file") or "")
        path = common._safe_input(self.input_root, file_name)
        query = str(args.get("query") or "").strip()
        if not query:
            raise ValueError("query must be non-empty")
        hypothesis_id, test_id = self._links(args)
        result = retrieve(
            EvidenceRequest(
                QueryTarget(
                    path,
                    query,
                    regex=bool(args.get("regex")),
                    snapshot=False,
                    max_evidence=None,
                    max_line_chars=None,
                ),
                investigation_path=self._investigation_path,
                hypothesis_id=hypothesis_id,
                test_id=test_id,
                cache=True,
            )
        )
        return self._render(result)

    def _tracecite_get(self, args: Mapping[str, Any]) -> str:
        file_name = str(args.get("file") or "")
        path = common._safe_input(self.input_root, file_name)
        try:
            line = int(args.get("line"))
            requested_radius = int(args.get("radius", 3))
        except (TypeError, ValueError) as exc:
            raise ValueError("line and radius must be integers") from exc
        if line < 1:
            raise ValueError("line must be >= 1")
        if requested_radius < 0:
            raise ValueError("radius must be >= 0")
        radius = (
            0
            if requested_radius == 0
            else min(canonical._MAX_GET_RADIUS, max(canonical._MIN_GET_RADIUS, requested_radius))
        )
        prefix = ""
        if radius != requested_radius:
            direction = "expanded" if radius > requested_radius else "clamped"
            prefix = f"@NORMALIZE radius_{direction}_from={requested_radius} radius={radius}"
        hypothesis_id, test_id = self._links(args)
        result = retrieve(
            EvidenceRequest(
                RangeTarget(
                    path,
                    line,
                    before=radius,
                    after=radius,
                    expected_sha256=self._sha_by_file[file_name],
                    max_chars=20_000,
                ),
                investigation_path=self._investigation_path,
                hypothesis_id=hypothesis_id,
                test_id=test_id,
                cache=True,
            )
        )
        return self._render(result, prefix=prefix)

    def call(self, name: str, args: Mapping[str, Any]) -> str:
        if self.mode in {"tracecite", "tracecite_context"}:
            if name == "tracecite_hypothesis":
                return self._tracecite_hypothesis(args)
            if name == "tracecite_test":
                return self._tracecite_test(args)
            if name == "tracecite_assess_test":
                return self._tracecite_assess_test(args)
            if name == "tracecite_finding":
                return self._tracecite_finding(args)
            if name == "tracecite_state":
                return self._tracecite_state(args)
            if name == "tracecite_inspect":
                return self._tracecite_inspect(args)
            if name == "tracecite_search":
                return self._tracecite_search(args)
            if name == "tracecite_get":
                return self._tracecite_get(args)
        return super().call(name, args)


def _tools_for_mode(mode: str, files: Sequence[Path]) -> list[dict[str, Any]]:
    tools = canonical._tools_for_mode(mode, files)
    if mode not in {"tracecite", "tracecite_context"}:
        return tools

    link_properties = {
        "hypothesis_id": {"type": ["string", "null"]},
        "test_id": {"type": ["string", "null"]},
    }
    for tool in tools:
        name = str(tool.get("name") or "")
        if name not in {"tracecite_inspect", "tracecite_search", "tracecite_get"}:
            continue
        parameters = tool.get("parameters") or {}
        if isinstance(parameters, dict):
            properties = parameters.get("properties") or {}
            if isinstance(properties, dict):
                properties.update(link_properties)

    investigation_tools = [
        common._function_tool(
            "tracecite_hypothesis",
            "Record one falsifiable hypothesis before treating retrieved facts as a root-cause conclusion.",
            {
                "claim": {"type": "string"},
                "hypothesis_id": {"type": ["string", "null"]},
                "rationale": {"type": ["string", "null"]},
            },
            ["claim", "hypothesis_id", "rationale"],
        ),
        common._function_tool(
            "tracecite_test",
            "Declare one concrete Test for a hypothesis, including both the observation that would support it and the observation that would contradict it. Every declared Test must be assessed before a decisive Finding.",
            {
                "hypothesis_id": {"type": "string"},
                "intent": {"type": "string"},
                "expected_observation": {"type": "string"},
                "contradicting_observation": {"type": "string"},
                "test_id": {"type": ["string", "null"]},
            },
            [
                "hypothesis_id",
                "intent",
                "expected_observation",
                "contradicting_observation",
                "test_id",
            ],
        ),
        common._function_tool(
            "tracecite_assess_test",
            "Assess one declared Test. supported/contradicted require immutable Evidence URIs produced by retrievals linked to the same Test; use unknown when evidence is insufficient.",
            {
                "test_id": {"type": "string"},
                "outcome": {
                    "type": "string",
                    "enum": ["supported", "contradicted", "unknown"],
                },
                "evidence_refs": {"type": "array", "items": {"type": "string"}},
            },
            ["test_id", "outcome", "evidence_refs"],
        ),
        common._function_tool(
            "tracecite_finding",
            "Record the epistemic Finding for a hypothesis. Runtime rejects a decisive supported/contradicted Finding when declared Tests are unassessed, unknown, contradictory to the requested outcome, or not evidence-backed. Record unknown when the investigation cannot close.",
            {
                "hypothesis_id": {"type": "string"},
                "outcome": {
                    "type": "string",
                    "enum": ["supported", "contradicted", "unknown"],
                },
                "summary": {"type": "string"},
                "supporting_evidence": {"type": "array", "items": {"type": "string"}},
                "contradicting_evidence": {"type": "array", "items": {"type": "string"}},
                "limitations": {"type": "array", "items": {"type": "string"}},
            },
            [
                "hypothesis_id",
                "outcome",
                "summary",
                "supporting_evidence",
                "contradicting_evidence",
                "limitations",
            ],
        ),
        common._function_tool(
            "tracecite_state",
            "Inspect the compact investigation bookkeeping state: hypotheses, declared Tests, latest Test assessments, and Findings. This does not retrieve new evidence.",
            {},
            [],
        ),
    ]
    return [*investigation_tools, *tools]


base.BenchmarkToolRuntime = EvidenceContractRuntime
common._tools_for_mode = _tools_for_mode


if __name__ == "__main__":
    try:
        raise SystemExit(base.run())
    except Exception as exc:
        transcript_value = os.environ.get("TRACECITE_BENCH_TRANSCRIPT", "").strip()
        failure_reason = canonical._host_failure_reason(exc)
        if transcript_value:
            try:
                common._append_event(
                    Path(transcript_value),
                    {
                        "type": "host_error",
                        "error": type(exc).__name__,
                        "failure_reason": failure_reason,
                        "message": str(exc),
                    },
                )
            except Exception:
                pass
        print(
            f"benchmark host failed: reason={failure_reason} {type(exc).__name__}: {exc}",
            file=os.sys.stderr,
        )
        raise
