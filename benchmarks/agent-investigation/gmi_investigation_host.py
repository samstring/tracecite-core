from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

import gmi_canonical_host as canonical
import gmi_host as base
import openai_host as common
from tracecite.runtime.investigation import FINDING_OUTCOMES, STOP_KINDS, InvestigationStore
from tracecite.runtime.investigation_summary import summarize_investigation
from tracecite.runtime.tools import expand, probe, sample, search, survey, verify


_MAX_TOOL_OUTPUT_CHARS = 24_000
_DEFAULT_PROVIDER_MAX_ATTEMPTS = 2
_DEFAULT_PROVIDER_BACKOFF_SECONDS = 20

base.SYSTEM_PROMPT = """You are debugging a production incident from runtime evidence only.
Use only the benchmark tools provided to you. Do not use web search or outside knowledge.
If TraceCite investigation tools are available, follow the TraceCite investigation protocol rather
than treating search as a standalone grep replacement: probe each source before reading/searching it;
use sample or survey only as bounded descriptive observations; state falsifiable hypotheses; search
separately for competing hypotheses; expand both supporting and contradicting EvidencePointers; record
tests/findings in InvestigationState for a non-trivial investigation; inspect the investigation summary;
and call the investigation stop tool before the final answer. Survey/sample observations are not causal
conclusions. A search match is an observation, not proof of cause. Preserve SHA-256/line provenance and
report missing evidence, coverage, truncation, and uncertainty. If a Scenario manifest is actually used,
verify it before relying on it. Keep the investigation bounded and stop on resolution, evidence exhaustion,
budget exhaustion, or when new authorization would be required.
If TraceCite tools are not available, use the provided bounded shell tools conservatively and follow the
same evidence/uncertainty rules. Your final answer must cite concrete evidence IDs or precise source
locations that support the conclusion.
"""


def _jsonable(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, Mapping):
        return dict(value)
    return value


def _bounded_json(value: Any, *, max_chars: int = _MAX_TOOL_OUTPUT_CHARS) -> str:
    rendered = json.dumps(_jsonable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(rendered) <= max_chars:
        return rendered
    envelope = {
        "status": "partial",
        "outcome": "unknown",
        "coverage": {"tool_output_truncated": True, "original_chars": len(rendered)},
        "warnings": ["Host transport bounded a non-evidence coordination payload."],
        "data": {"preview": rendered[: max_chars - 512]},
    }
    return json.dumps(envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _positive_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    value = int(raw)
    if value < 1:
        raise ValueError(f"{name} must be >= 1")
    return value


def _post_chat_resilient(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Canonical host policies plus bounded provider retry/backoff.

    The provider wrapper does not currently expose HTTP Retry-After headers, so
    this uses a conservative exponential fallback. Full-arm retries are bounded
    separately by run_paired_bounded_retry.py.
    """

    transcript_value = os.environ.get("TRACECITE_BENCH_TRANSCRIPT", "").strip()
    request_payload, action_event = canonical._apply_action_policy(payload)
    constraint_event = None
    if action_event is None:
        request_payload, constraint_event = canonical._apply_constraint_policy(request_payload)
    if action_event is None and constraint_event is None:
        request_payload, stop_event = canonical._apply_stop_policy(request_payload)
    else:
        stop_event = None

    if transcript_value:
        transcript = Path(transcript_value)
        for event in (action_event, constraint_event, stop_event):
            if event is not None:
                common._append_event(transcript, event)
        common._append_event(transcript, canonical._request_context_event(request_payload))

    max_attempts = _positive_env(
        "TRACECITE_BENCH_PROVIDER_MAX_ATTEMPTS", _DEFAULT_PROVIDER_MAX_ATTEMPTS
    )
    base_delay = _positive_env(
        "TRACECITE_BENCH_PROVIDER_BACKOFF_SECONDS", _DEFAULT_PROVIDER_BACKOFF_SECONDS
    )
    for attempt in range(1, max_attempts + 1):
        try:
            return canonical._ORIGINAL_POST_CHAT(request_payload)
        except RuntimeError as exc:
            reason = canonical._host_failure_reason(exc)
            transient = reason in {"provider_rate_limited", "provider_unavailable"}
            if not transient or attempt >= max_attempts:
                raise
            delay = base_delay * (2 ** (attempt - 1))
            if transcript_value:
                common._append_event(
                    Path(transcript_value),
                    {
                        "type": "protocol",
                        "event": "provider_retry",
                        "attempt": attempt,
                        "max_attempts": max_attempts,
                        "sleep_seconds": delay,
                        "failure_reason": reason,
                    },
                )
            time.sleep(delay)
    raise AssertionError("unreachable")


class InvestigationRuntime(canonical.CanonicalRuntime):
    """Benchmark adapter that exposes the complete TraceCite investigation protocol."""

    def __init__(self, *, mode: str, input_root: Path, scratch: Path, context_id: str) -> None:
        super().__init__(mode=mode, input_root=input_root, scratch=scratch, context_id=context_id)
        self._probed_files: set[str] = set()

    def _path(self, args: Mapping[str, Any]) -> tuple[str, Path]:
        file_name = str(args.get("file") or "").strip()
        if not file_name:
            raise ValueError("file must be non-empty")
        return file_name, common._safe_input(self.input_root, file_name)

    def _links(self, args: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "investigation_path": self._investigation_path,
            "hypothesis_id": str(args.get("hypothesis_id") or "").strip() or None,
            "test_id": str(args.get("test_id") or "").strip() or None,
        }

    def _requires_probe(self, file_name: str) -> str | None:
        if file_name in self._probed_files:
            return None
        return _bounded_json(
            {
                "status": "blocked",
                "outcome": "unknown",
                "missing_evidence": [{"kind": "probe_required", "detail": file_name}],
                "next_queries": [f"tracecite_probe(file={file_name!r})"],
                "data": {"stop_reason": {"kind": "protocol_gate", "detail": "probe_required"}},
            }
        )

    def _tracecite_probe(self, args: Mapping[str, Any]) -> str:
        file_name, path = self._path(args)
        result = probe(path, investigation_path=self._investigation_path, cache=True)
        if str(result.get("status") or "") != "error":
            self._probed_files.add(file_name)
        return self._render(result)

    def _tracecite_sample(self, args: Mapping[str, Any]) -> str:
        file_name, path = self._path(args)
        blocked = self._requires_probe(file_name)
        if blocked:
            return blocked
        result = sample(
            path,
            strategy=str(args.get("strategy") or "head-tail"),
            count=min(20, max(1, int(args.get("count", 10)))),
            max_chars=min(16_000, max(1_024, int(args.get("max_chars", 8_000)))),
            snapshot=True,
            investigation_path=self._investigation_path,
            cache=True,
        )
        return self._render(result)

    def _tracecite_survey(self, args: Mapping[str, Any]) -> str:
        file_name, path = self._path(args)
        blocked = self._requires_probe(file_name)
        if blocked:
            return blocked
        result = survey(
            path,
            snapshot=True,
            max_templates=min(30, max(2, int(args.get("max_templates", 20)))),
            samples_per_template=min(2, max(0, int(args.get("samples_per_template", 1)))),
            investigation_path=self._investigation_path,
            cache=True,
        )
        return self._render(result)

    def _tracecite_search(self, args: Mapping[str, Any]) -> str:
        file_name, path = self._path(args)
        blocked = self._requires_probe(file_name)
        if blocked:
            return blocked
        query = str(args.get("query") or "").strip()
        if not query:
            raise ValueError("query must be non-empty")
        result = search(
            path,
            query,
            regex=bool(args.get("regex")),
            snapshot=True,
            segmenter="auto",
            max_evidence=None,
            max_line_chars=None,
            cache=True,
            **self._links(args),
        )
        return self._render(result)

    def _tracecite_expand(self, args: Mapping[str, Any]) -> str:
        file_name, path = self._path(args)
        blocked = self._requires_probe(file_name)
        if blocked:
            return blocked
        start_line = int(args.get("start_line"))
        end_value = args.get("end_line")
        end_line = int(end_value) if end_value not in (None, "") else None
        result = expand(
            path,
            start_line,
            end_line=end_line,
            before=min(12, max(0, int(args.get("before", 3)))),
            after=min(12, max(0, int(args.get("after", 3)))),
            expected_sha256=str(args.get("expected_sha256") or "").strip() or None,
            max_chars=20_000,
            cache=True,
            **self._links(args),
        )
        return self._render(result)

    def _tracecite_verify(self, args: Mapping[str, Any]) -> str:
        manifest = str(args.get("manifest") or "").strip()
        if not manifest:
            raise ValueError("manifest must be non-empty")
        candidate = (self.scratch / manifest).resolve()
        if not candidate.is_file():
            candidate = (self.input_root / manifest).resolve()
        roots = (self.scratch.resolve(), self.input_root.resolve())
        if not any(candidate == root or root in candidate.parents for root in roots):
            raise ValueError("manifest must stay within benchmark input/scratch roots")
        return self._render(verify(candidate, investigation_path=self._investigation_path))

    def _add_hypothesis(self, args: Mapping[str, Any]) -> str:
        store = InvestigationStore(self._investigation_path)
        item = store.add_hypothesis(
            str(args.get("claim") or "").strip(),
            hypothesis_id=str(args.get("hypothesis_id") or "").strip() or None,
            rationale=str(args.get("rationale") or "").strip(),
        )
        return _bounded_json({"status": "ok", "operation": "investigation_add_hypothesis", "result": _jsonable(item)})

    def _add_test(self, args: Mapping[str, Any]) -> str:
        store = InvestigationStore(self._investigation_path)
        item = store.add_test(
            str(args.get("hypothesis_id") or "").strip(),
            str(args.get("intent") or "").strip(),
            expected_observation=str(args.get("expected_observation") or "").strip(),
            contradicting_observation=str(args.get("contradicting_observation") or "").strip(),
            test_id=str(args.get("test_id") or "").strip() or None,
        )
        return _bounded_json({"status": "ok", "operation": "investigation_add_test", "result": _jsonable(item)})

    def _add_finding(self, args: Mapping[str, Any]) -> str:
        store = InvestigationStore(self._investigation_path)
        item = store.add_finding(
            str(args.get("hypothesis_id") or "").strip(),
            str(args.get("outcome") or "unknown").strip(),
            str(args.get("summary") or "").strip(),
            supporting_evidence=[str(item) for item in args.get("supporting_evidence") or []],
            contradicting_evidence=[str(item) for item in args.get("contradicting_evidence") or []],
            coverage=dict(args.get("coverage") or {}),
            limitations=[str(item) for item in args.get("limitations") or []],
        )
        return _bounded_json({"status": "ok", "operation": "investigation_add_finding", "result": _jsonable(item)})

    def _investigation_summary(self) -> str:
        return _bounded_json(
            summarize_investigation(
                InvestigationStore(self._investigation_path),
                max_items=32,
                max_output_chars=_MAX_TOOL_OUTPUT_CHARS,
            )
        )

    def _investigation_stop(self, args: Mapping[str, Any]) -> str:
        store = InvestigationStore(self._investigation_path)
        state = store.stop(
            str(args.get("reason") or "investigation complete").strip(),
            kind=str(args.get("kind") or "completed").strip(),
        )
        return _bounded_json({"status": "ok", "operation": "investigation_stop", "state": _jsonable(state)})

    def call(self, name: str, args: Mapping[str, Any]) -> str:
        if self.mode in {"tracecite", "tracecite_context"}:
            if name == "tracecite_probe":
                return self._tracecite_probe(args)
            if name == "tracecite_sample":
                return self._tracecite_sample(args)
            if name == "tracecite_survey":
                return self._tracecite_survey(args)
            if name == "tracecite_search":
                return self._tracecite_search(args)
            if name == "tracecite_expand":
                return self._tracecite_expand(args)
            if name == "tracecite_verify":
                return self._tracecite_verify(args)
            if name == "tracecite_hypothesis":
                return self._add_hypothesis(args)
            if name == "tracecite_test":
                return self._add_test(args)
            if name == "tracecite_finding":
                return self._add_finding(args)
            if name == "tracecite_investigation_summary":
                return self._investigation_summary()
            if name == "tracecite_investigation_stop":
                return self._investigation_stop(args)
        return super().call(name, args)


def _tools_for_mode(mode: str, files: Sequence[Path]) -> list[dict[str, Any]]:
    if mode not in {"tracecite", "tracecite_context"}:
        return canonical._ORIGINAL_TOOLS_FOR_MODE(mode, files)
    file_property = common._common_file_property(files)
    link_properties = {
        "hypothesis_id": {"type": "string"},
        "test_id": {"type": "string"},
    }
    return [
        common._function_tool(
            "tracecite_probe",
            "Mandatory first step for each evidence source. Inspect immutable source identity, size, format, record/time coverage and safe next actions without dumping the source.",
            {"file": file_property},
            ["file"],
        ),
        common._function_tool(
            "tracecite_sample",
            "Optional bounded raw-context observation after probe. It is descriptive only and never a root-cause conclusion.",
            {
                "file": file_property,
                "strategy": {"type": "string", "enum": ["head-tail", "uniform"]},
                "count": {"type": "integer", "minimum": 1, "maximum": 20},
                "max_chars": {"type": "integer", "minimum": 1024, "maximum": 16000},
            },
            ["file", "strategy", "count", "max_chars"],
        ),
        common._function_tool(
            "tracecite_survey",
            "Optional bounded descriptive survey after probe when the source is unfamiliar or there is no defensible first query. Use it to form competing falsifiable hypotheses, not as causal proof.",
            {
                "file": file_property,
                "max_templates": {"type": "integer", "minimum": 2, "maximum": 30},
                "samples_per_template": {"type": "integer", "minimum": 0, "maximum": 2},
            },
            ["file", "max_templates", "samples_per_template"],
        ),
        common._function_tool(
            "tracecite_hypothesis",
            "Record a falsifiable hypothesis in InvestigationState before testing it. For non-trivial investigations record at least competing hypotheses when feasible.",
            {
                "claim": {"type": "string"},
                "rationale": {"type": "string"},
                "hypothesis_id": {"type": "string"},
            },
            ["claim"],
        ),
        common._function_tool(
            "tracecite_test",
            "Record a falsifiable test for a hypothesis, including observations that would support versus contradict it.",
            {
                "hypothesis_id": {"type": "string"},
                "intent": {"type": "string"},
                "expected_observation": {"type": "string"},
                "contradicting_observation": {"type": "string"},
                "test_id": {"type": "string"},
            },
            ["hypothesis_id", "intent", "expected_observation", "contradicting_observation"],
        ),
        common._function_tool(
            "tracecite_search",
            "Search a probed source for one concrete falsifiable hypothesis using an immutable snapshot. Inspect status/outcome/coverage/missing evidence/warnings/truncation independently. A match is observation, not proof of cause.",
            {
                "file": file_property,
                "query": {"type": "string"},
                "regex": {"type": "boolean"},
                **link_properties,
            },
            ["file", "query", "regex"],
        ),
        common._function_tool(
            "tracecite_expand",
            "Expand bounded context around a relevant EvidencePointer after search, including supporting and contradicting observations. Supply the EvidencePointer SHA-256 when available.",
            {
                "file": file_property,
                "start_line": {"type": "integer", "minimum": 1},
                "end_line": {"type": "integer", "minimum": 1},
                "before": {"type": "integer", "minimum": 0, "maximum": 12},
                "after": {"type": "integer", "minimum": 0, "maximum": 12},
                "expected_sha256": {"type": "string"},
                **link_properties,
            },
            ["file", "start_line"],
        ),
        common._function_tool(
            "tracecite_verify",
            "Verify a completed Scenario evidence manifest before relying on it. Use only if a manifest actually exists for this investigation.",
            {"manifest": {"type": "string"}},
            ["manifest"],
        ),
        common._function_tool(
            "tracecite_finding",
            "Record the evaluated outcome for a hypothesis before stopping. Cite supporting and contradicting Evidence URIs and preserve limitations/coverage.",
            {
                "hypothesis_id": {"type": "string"},
                "outcome": {"type": "string", "enum": sorted(FINDING_OUTCOMES)},
                "summary": {"type": "string"},
                "supporting_evidence": {"type": "array", "items": {"type": "string"}},
                "contradicting_evidence": {"type": "array", "items": {"type": "string"}},
                "coverage": {"type": "object"},
                "limitations": {"type": "array", "items": {"type": "string"}},
            },
            ["hypothesis_id", "outcome", "summary"],
        ),
        common._function_tool(
            "tracecite_investigation_summary",
            "Read bounded InvestigationState coordination metadata before stopping: hypotheses/tests/findings, gaps, budget and suggested action categories. It does not diagnose the incident.",
            {},
            [],
        ),
        common._function_tool(
            "tracecite_investigation_stop",
            "Close the InvestigationState and record the stopping reason. Call this before the final answer after findings are recorded.",
            {
                "reason": {"type": "string"},
                "kind": {"type": "string", "enum": sorted(STOP_KINDS)},
            },
            ["reason", "kind"],
        ),
    ]


base.BenchmarkToolRuntime = InvestigationRuntime
base._post_chat = _post_chat_resilient
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
