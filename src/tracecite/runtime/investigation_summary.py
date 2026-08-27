"""Bounded, read-only completeness hints for an InvestigationState.

This module deliberately does not advance an investigation or choose a domain
query.  It turns the small, validated coordination graph into counts and
stable references that an Agent can inspect before deciding what to do next.
The output is advisory metadata: it is not an enforcement funnel and it is
not an epistemic verdict.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple, Union

from .investigation import InvestigationError, InvestigationState, InvestigationStore


SUMMARY_SCHEMA_VERSION = 1

# These are deliberately smaller than the state-file limits.  A summary is a
# prompt-facing index, not a second copy of the investigation document.
MAX_SUMMARY_ITEMS = 32
MAX_SUMMARY_TEXT = 256
MAX_SUMMARY_OUTPUT_CHARS = 24_000
MAX_SUMMARY_SOURCE_BYTES = 1_048_576

_DETAIL_KEYS = (
    "unresolved_hypotheses",
    "untested_hypotheses",
    "untested_tests",
    "execution_gaps",
    "finding_gaps",
    "coverage_gaps",
    "suggested_actions",
)


@dataclass(frozen=True)
class SummaryLimits:
    """Hard limits for one summary request.

    Caller supplied values are clamped to the module's hard ceilings.  This
    means a host cannot accidentally request an unbounded prompt payload.
    ``max_text_chars`` applies to control text such as a stop detail; claims,
    findings, parameters, and evidence bodies are never copied.
    """

    max_items: int = MAX_SUMMARY_ITEMS
    max_text_chars: int = MAX_SUMMARY_TEXT
    max_output_chars: int = MAX_SUMMARY_OUTPUT_CHARS
    max_source_bytes: int = MAX_SUMMARY_SOURCE_BYTES

    def __post_init__(self) -> None:
        # Negative/non-numeric values are invalid arguments, while an
        # oversized positive request is safely capped at the hard ceiling.
        object.__setattr__(
            self,
            "max_items",
            _validate_limit(self.max_items, 1, MAX_SUMMARY_ITEMS, "max_items"),
        )
        object.__setattr__(
            self,
            "max_text_chars",
            _validate_limit(
                self.max_text_chars, 32, MAX_SUMMARY_TEXT, "max_text_chars"
            ),
        )
        object.__setattr__(
            self,
            "max_output_chars",
            _validate_limit(
                self.max_output_chars, 512, MAX_SUMMARY_OUTPUT_CHARS, "max_output_chars"
            ),
        )
        object.__setattr__(
            self,
            "max_source_bytes",
            _validate_limit(
                self.max_source_bytes, 4_096, MAX_SUMMARY_SOURCE_BYTES, "max_source_bytes"
            ),
        )


class InvestigationSummaryError(ValueError):
    """Raised only when a caller explicitly requests strict loading."""


def _validate_limit(value: Any, lower: int, upper: int, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < lower:
        raise InvestigationSummaryError("invalid_limit:" + field_name)
    return min(value, upper)


def _text(value: Any, *, limit: int) -> str:
    """Return bounded control text without preserving arbitrary objects."""

    if value is None:
        return ""
    return str(value)[:limit]


def _identifier(value: Any, *, limit: int = 128) -> str:
    # IDs have already been validated by InvestigationState.  Keeping this
    # helper defensive also makes a future state implementation safe to use.
    return _text(value, limit=limit)


def _truthy(value: Any) -> bool:
    """A small predicate that does not inspect or copy arbitrary payloads."""

    if value is None or value is False:
        return False
    if isinstance(value, (str, bytes)):
        return bool(value)
    if isinstance(value, Mapping) or isinstance(value, Sequence):
        return len(value) > 0
    return bool(value)


def _iter_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _state_zero() -> Dict[str, Any]:
    return {
        "observations": {"total": 0, "reported": 0, "omitted": 0},
        "hypotheses": {
            "total": 0,
            "open": 0,
            "supported": 0,
            "contradicted": 0,
            "unknown": 0,
            "unresolved": 0,
            "untested": 0,
            "reported": 0,
            "omitted": 0,
        },
        "tests": {
            "total": 0,
            "with_executions": 0,
            "without_executions": 0,
            "reported": 0,
            "omitted": 0,
        },
        "executions": {
            "total": 0,
            "ok": 0,
            "error": 0,
            "unknown": 0,
            "missing_evidence": 0,
            "omission": 0,
            "truncation": 0,
            "unlinked": 0,
            "reported": 0,
            "omitted": 0,
        },
        "findings": {
            "total": 0,
            "supported": 0,
            "contradicted": 0,
            "unknown": 0,
            "gaps": 0,
            "reported": 0,
            "omitted": 0,
        },
        "coverage": {"gaps": 0, "reported": 0, "omitted": 0},
    }


def _error_summary(source_kind: str, code: str, *, limits: SummaryLimits) -> Dict[str, Any]:
    progress = _state_zero()
    summary: Dict[str, Any] = {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "advisory": True,
        "status": "error",
        "valid": False,
        "source_kind": source_kind,
        "state_status": None,
        "stop": {"status": None, "kind": "", "reason": "", "present": False},
        "progress": progress,
        "unresolved_hypotheses": [],
        "untested_hypotheses": [],
        "untested_tests": [],
        "execution_gaps": [],
        "finding_gaps": [],
        "coverage_gaps": [],
        "suggested_actions": [],
        "advisory_completeness": {
            "complete": False,
            "advisory_only": True,
            "reasons": [code],
        },
        "omitted": {key: 0 for key in _DETAIL_KEYS},
        "truncated": False,
        "error": {"code": code},
    }
    return _fit_output(summary, limits)


def _source_kind(source: Any) -> str:
    if isinstance(source, InvestigationState):
        return "state"
    if isinstance(source, InvestigationStore):
        return "store"
    if isinstance(source, Mapping):
        return "mapping"
    if isinstance(source, (str, Path)):
        return "path"
    return "unsupported"


def _load_state(source: Any, *, limits: SummaryLimits) -> Tuple[InvestigationState, str]:
    """Load through the canonical validator without writing anything."""

    kind = _source_kind(source)
    if isinstance(source, InvestigationState):
        # State objects are validated at construction, but re-validate a
        # detached document so a caller cannot mutate a live object halfway
        # through summarization.
        detached = source.to_dict()
        _check_mapping_size(detached, limits=limits)
        return InvestigationState.from_dict(detached), kind
    if isinstance(source, InvestigationStore):
        path = getattr(source, "path", None)
        _check_path_size(path, limits=limits)
        return source.load(), kind
    if isinstance(source, Mapping):
        _check_mapping_size(source, limits=limits)
        return InvestigationState.from_dict(source), kind
    if isinstance(source, (str, Path)):
        path = Path(source).expanduser().resolve()
        _check_path_size(path, limits=limits)
        return InvestigationStore(path).load(), kind
    raise InvestigationSummaryError("unsupported_source")


def _check_path_size(path: Any, *, limits: SummaryLimits) -> None:
    if not isinstance(path, (str, Path)):
        raise InvestigationSummaryError("source_unreadable")
    resolved = Path(path).expanduser().resolve()
    try:
        if not resolved.is_file():
            raise InvestigationSummaryError("source_missing")
        if resolved.stat().st_size > limits.max_source_bytes:
            raise InvestigationSummaryError("source_too_large")
    except OSError as exc:
        raise InvestigationSummaryError("source_unreadable") from exc


def _check_mapping_size(value: Mapping[str, Any], *, limits: SummaryLimits) -> None:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as exc:
        raise InvestigationSummaryError("source_invalid") from exc
    if len(encoded) > limits.max_source_bytes:
        raise InvestigationSummaryError("source_too_large")


def _recording_flags(execution: Mapping[str, Any]) -> Tuple[bool, bool]:
    recording = _iter_mapping(execution.get("recording"))
    omission = False
    truncation = False
    for key, value in recording.items():
        key_text = str(key).lower()
        if not _truthy(value):
            continue
        # data/text omission is the intentional bounded-state contract for
        # every execution, not evidence loss.  Other omission flags indicate
        # metadata the caller could not preserve and are surfaced as gaps.
        if key_text.endswith("_omitted") and key_text not in {
            "data_omitted",
            "text_omitted",
        }:
            omission = True
        if key_text.endswith("_truncated"):
            truncation = True
    return omission, truncation


def _execution_flags(execution: Mapping[str, Any]) -> Dict[str, bool]:
    status = _text(execution.get("status"), limit=128).strip().lower()
    outcome = _text(execution.get("outcome"), limit=128).strip().lower()
    error = _truthy(execution.get("error"))
    is_error = error or status in {"error", "failed", "failure"} or outcome in {
        "error",
        "failed",
        "failure",
    }
    # Keep execution status and epistemic outcome independent.  A failed
    # operation conventionally has ``status=error, outcome=unknown`` and must
    # be visible in both counters rather than hiding the epistemic uncertainty
    # behind the transport error.
    is_unknown = status in {"", "unknown"} or outcome in {"", "unknown"}
    missing = _truthy(execution.get("missing_evidence"))
    if not missing and outcome in {"supported", "contradicted"}:
        # A positive/negative execution without a persisted Evidence pointer
        # cannot be independently checked.  Unknown executions already carry
        # their uncertainty in ``unknown`` and need no duplicate gap.
        missing = not _truthy(
            execution.get("evidence") or execution.get("evidence_refs")
        )
    omission, truncation = _recording_flags(execution)
    return {
        "error": is_error,
        "unknown": is_unknown,
        "missing_evidence": missing,
        "omission": omission,
        "truncation": truncation,
    }


def _append_bounded(
    rows: List[Dict[str, Any]],
    row: Dict[str, Any],
    *,
    limit: int,
    omitted: Dict[str, int],
    key: str,
) -> None:
    if len(rows) < limit:
        rows.append(row)
    else:
        omitted[key] = omitted.get(key, 0) + 1


def _safe_ids(values: Iterable[Any], *, limit: int = 128) -> List[str]:
    result: List[str] = []
    seen = set()
    for value in values:
        identifier = _identifier(value, limit=limit)
        if identifier and identifier not in seen:
            seen.add(identifier)
            result.append(identifier)
    return result


def _fit_output(summary: Dict[str, Any], limits: SummaryLimits) -> Dict[str, Any]:
    """Keep the serialized envelope below the hard prompt budget."""

    def encoded_size() -> int:
        return len(
            json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )

    while encoded_size() > limits.max_output_chars:
        removed = False
        # Detail is expendable; progress counts and reasons remain useful.
        for key in reversed(_DETAIL_KEYS):
            rows = summary.get(key)
            if isinstance(rows, list) and rows:
                rows.pop()
                omitted = summary.setdefault("omitted", {})
                omitted[key] = int(omitted.get(key) or 0) + 1
                summary["truncated"] = True
                removed = True
                break
        if not removed:
            # This path is only reachable with an unusually small caller
            # budget or a future schema change.  Return a compact, still-valid
            # control envelope rather than slicing JSON in the middle of a
            # string.
            compact = {
                "schema_version": SUMMARY_SCHEMA_VERSION,
                "advisory": True,
                "status": "ok" if summary.get("valid") else "error",
                "valid": bool(summary.get("valid")),
                "source_kind": summary.get("source_kind", "unsupported"),
                "state_status": summary.get("state_status"),
                "stop": summary.get("stop") or {},
                "progress": summary.get("progress") or _state_zero(),
                "advisory_completeness": summary.get("advisory_completeness") or {
                    "complete": False,
                    "advisory_only": True,
                    "reasons": ["output_truncated"],
                },
                "omitted": dict(summary.get("omitted") or {}),
                "truncated": True,
            }
            if summary.get("error"):
                compact["error"] = dict(summary["error"])
            # A very small caller budget may not fit even the useful compact
            # envelope.  Add fields in a stable order only when they fit,
            # finally retaining a minimal valid JSON object.
            if len(json.dumps(compact, ensure_ascii=False, separators=(",", ":"))) <= limits.max_output_chars:
                return compact
            minimal = {
                "schema_version": SUMMARY_SCHEMA_VERSION,
                "advisory": True,
                "status": compact["status"],
                "valid": compact["valid"],
                "truncated": True,
            }
            for key in ("source_kind", "state_status", "stop", "progress", "omitted", "error"):
                if key not in compact:
                    continue
                candidate = dict(minimal)
                candidate[key] = compact[key]
                if len(json.dumps(candidate, ensure_ascii=False, separators=(",", ":"))) <= limits.max_output_chars:
                    minimal = candidate
            return minimal
    return summary


def _summary_for_state(state: InvestigationState, *, kind: str, limits: SummaryLimits) -> Dict[str, Any]:
    def ordered(items: Sequence[Mapping[str, Any]]) -> List[Mapping[str, Any]]:
        return sorted(items, key=lambda item: _identifier(item.get("id")))

    hypotheses = ordered(list(state.hypotheses or []))
    tests = ordered(list(state.tests or []))
    executions = ordered(list(state.executions or []))
    findings = ordered(list(state.findings or []))
    observations = ordered(list(state.observations or []))

    progress = _state_zero()
    omitted: Dict[str, int] = {key: 0 for key in _DETAIL_KEYS}
    progress["observations"].update(
        total=len(observations),
        reported=min(len(observations), limits.max_items),
        omitted=max(0, len(observations) - limits.max_items),
    )

    tests_by_id = {
        _identifier(item.get("id")): item
        for item in tests
        if _identifier(item.get("id"))
    }
    executions_by_id = {
        _identifier(item.get("id")): item
        for item in executions
        if _identifier(item.get("id"))
    }
    findings_by_hypothesis: Dict[str, List[Mapping[str, Any]]] = {}
    for finding in findings:
        findings_by_hypothesis.setdefault(
            _identifier(finding.get("hypothesis_id")), []
        ).append(finding)

    unresolved_rows: List[Dict[str, Any]] = []
    untested_hypothesis_rows: List[Dict[str, Any]] = []
    untested_hypothesis_ids: List[str] = []
    unresolved_ids: List[str] = []
    hypotheses_with_clean_evidence: List[str] = []
    hypothesis_tests: Dict[str, List[Mapping[str, Any]]] = {}
    for hypothesis in hypotheses:
        identifier = _identifier(hypothesis.get("id"))
        status = _text(hypothesis.get("status") or "open", limit=128).lower()
        if status not in {"supported", "contradicted", "unknown"}:
            status = "open"
        progress["hypotheses"][status] += 1
        unresolved = status in {"open", "unknown"}
        test_ids = _safe_ids(hypothesis.get("test_ids") or [])
        linked_tests = [tests_by_id[item] for item in test_ids if item in tests_by_id]
        # Forward Test links are canonical after validation, but include a
        # defensive reverse lookup for future state readers.
        linked_tests.extend(
            item
            for item in tests
            if _identifier(item.get("hypothesis_id")) == identifier
            and item not in linked_tests
        )
        hypothesis_tests[identifier] = linked_tests
        if not linked_tests:
            progress["hypotheses"]["untested"] += 1
            untested_hypothesis_ids.append(identifier)
            _append_bounded(
                untested_hypothesis_rows,
                {"id": identifier, "status": status},
                limit=limits.max_items,
                omitted=omitted,
                key="untested_hypotheses",
            )
        if unresolved:
            progress["hypotheses"]["unresolved"] += 1
            unresolved_ids.append(identifier)
            if any(
                any(
                    execution_id in executions_by_id
                    and not any(_execution_flags(executions_by_id[execution_id]).values())
                    and bool(
                        executions_by_id[execution_id].get("evidence")
                        or executions_by_id[execution_id].get("evidence_refs")
                    )
                    for execution_id in _safe_ids(test.get("execution_ids") or [])
                )
                for test in linked_tests
            ):
                hypotheses_with_clean_evidence.append(identifier)
            row = {
                "id": identifier,
                "status": status,
                "test_ids": _safe_ids(item.get("id") for item in linked_tests)[: limits.max_items],
            }
            if len(linked_tests) > limits.max_items:
                omitted["unresolved_hypotheses"] += len(linked_tests) - limits.max_items
            _append_bounded(
                unresolved_rows,
                row,
                limit=limits.max_items,
                omitted=omitted,
                key="unresolved_hypotheses",
            )
    progress["hypotheses"]["total"] = len(hypotheses)
    progress["hypotheses"]["reported"] = min(len(hypotheses), limits.max_items)
    progress["hypotheses"]["omitted"] = max(0, len(hypotheses) - limits.max_items)

    untested_rows: List[Dict[str, Any]] = []
    untested_ids: List[str] = []
    for test in tests:
        test_id = _identifier(test.get("id"))
        execution_ids = _safe_ids(test.get("execution_ids") or [])
        if not execution_ids:
            untested_ids.append(test_id)
            _append_bounded(
                untested_rows,
                {
                    "id": test_id,
                    "hypothesis_id": _identifier(test.get("hypothesis_id")),
                },
                limit=limits.max_items,
                omitted=omitted,
                key="untested_tests",
            )
    progress["tests"].update(
        total=len(tests),
        with_executions=len(tests) - len(untested_ids),
        without_executions=len(untested_ids),
        reported=min(len(tests), limits.max_items),
        omitted=max(0, len(tests) - limits.max_items),
    )

    execution_gap_rows: List[Dict[str, Any]] = []
    bad_execution_ids: List[str] = []
    for execution in executions:
        execution_id = _identifier(execution.get("id"))
        flags = _execution_flags(execution)
        linked = bool(_identifier(execution.get("test_id")))
        if not linked:
            progress["executions"]["unlinked"] += 1
        for name in ("error", "unknown", "missing_evidence", "omission", "truncation"):
            if flags[name]:
                progress["executions"][name] += 1
        if not any(flags.values()):
            progress["executions"]["ok"] += 1
        else:
            bad_execution_ids.append(execution_id)
            gap_flags = [name for name in ("error", "unknown", "missing_evidence", "omission", "truncation") if flags[name]]
            _append_bounded(
                execution_gap_rows,
                {
                    "id": execution_id,
                    "hypothesis_id": _identifier(execution.get("hypothesis_id")),
                    "test_id": _identifier(execution.get("test_id")),
                    "status": _text(execution.get("status") or "unknown", limit=128),
                    "outcome": _text(execution.get("outcome") or "unknown", limit=128),
                    "flags": gap_flags,
                },
                limit=limits.max_items,
                omitted=omitted,
                key="execution_gaps",
            )
    progress["executions"].update(
        total=len(executions),
        reported=min(len(executions), limits.max_items),
        omitted=max(0, len(executions) - limits.max_items),
    )

    finding_gap_rows: List[Dict[str, Any]] = []
    finding_gap_count = 0
    for finding in findings:
        finding_id = _identifier(finding.get("id"))
        hypothesis_id = _identifier(finding.get("hypothesis_id"))
        outcome = _text(finding.get("outcome") or "unknown", limit=128).lower()
        if outcome not in {"supported", "contradicted", "unknown"}:
            outcome = "unknown"
        progress["findings"][outcome] += 1
        gap_kinds: List[str] = []
        if outcome == "unknown":
            gap_kinds.append("unknown_outcome")
        if not _truthy(finding.get("coverage")):
            gap_kinds.append("coverage_not_declared")
        if outcome == "supported" and not _truthy(finding.get("supporting_evidence")):
            gap_kinds.append("missing_supporting_evidence")
        if outcome == "contradicted" and not _truthy(finding.get("contradicting_evidence")):
            gap_kinds.append("missing_contradicting_evidence")
        related_tests = hypothesis_tests.get(hypothesis_id) or [
            test for test in tests if _identifier(test.get("hypothesis_id")) == hypothesis_id
        ]
        if not any(_safe_ids(test.get("execution_ids") or []) for test in related_tests):
            gap_kinds.append("no_execution")
        if gap_kinds:
            finding_gap_count += 1
            _append_bounded(
                finding_gap_rows,
                {"id": finding_id, "hypothesis_id": hypothesis_id, "outcome": outcome, "kinds": gap_kinds},
                limit=limits.max_items,
                omitted=omitted,
                key="finding_gaps",
            )
    progress["findings"].update(
        total=len(findings),
        gaps=finding_gap_count,
        reported=min(len(findings), limits.max_items),
        omitted=max(0, len(findings) - limits.max_items),
    )

    # Coverage gaps are stable category/reference pairs.  They intentionally
    # contain no claim, query, evidence body, or user-authored summary text.
    coverage_rows: List[Dict[str, Any]] = []
    coverage_gap_count = 0

    def add_coverage(kind_name: str, ref: str = "") -> None:
        nonlocal coverage_gap_count
        coverage_gap_count += 1
        _append_bounded(
            coverage_rows,
            {"kind": kind_name, "ref": _identifier(ref)},
            limit=limits.max_items,
            omitted=omitted,
            key="coverage_gaps",
        )

    if not hypotheses:
        add_coverage("no_hypotheses")
    for hypothesis_id in untested_hypothesis_ids:
        add_coverage("hypothesis_without_test", hypothesis_id)
    for hypothesis_id in unresolved_ids:
        add_coverage("unresolved_hypothesis", hypothesis_id)
    for test_id in untested_ids:
        add_coverage("test_without_execution", test_id)
    for execution in executions:
        execution_id = _identifier(execution.get("id"))
        flags = _execution_flags(execution)
        for name, gap_name in (
            ("error", "execution_error"),
            ("unknown", "execution_unknown"),
            ("missing_evidence", "execution_missing_evidence"),
            ("omission", "execution_omission"),
            ("truncation", "execution_truncation"),
        ):
            if flags[name]:
                add_coverage(gap_name, execution_id)
        if not _identifier(execution.get("test_id")):
            add_coverage("unlinked_execution", execution_id)
    for row in finding_gap_rows:
        for gap_kind in row["kinds"]:
            add_coverage("finding_" + gap_kind, row["id"])
    if state.status == "active":
        add_coverage("investigation_active", _identifier(state.investigation_id))
    progress["coverage"].update(
        gaps=coverage_gap_count,
        reported=min(coverage_gap_count, limits.max_items),
        omitted=max(0, coverage_gap_count - limits.max_items),
    )

    reasons: List[str] = []
    if not hypotheses:
        reasons.append("no_hypotheses")
    if unresolved_ids:
        reasons.append("unresolved_hypotheses")
    if untested_ids:
        reasons.append("tests_without_executions")
    if progress["executions"]["error"]:
        reasons.append("execution_errors")
    if progress["executions"]["unknown"]:
        reasons.append("execution_unknown")
    if progress["executions"]["missing_evidence"]:
        reasons.append("missing_evidence")
    if progress["executions"]["omission"]:
        reasons.append("recording_omission")
    if progress["executions"]["truncation"]:
        reasons.append("recording_truncation")
    if finding_gap_count:
        reasons.append("finding_coverage_gaps")
    if state.status == "active":
        reasons.append("investigation_active")

    suggested: List[Dict[str, Any]] = []

    def add_action(category: str, refs: Iterable[str]) -> None:
        ref_list = _safe_ids(refs)
        # Empty refs are meaningful only for the initial, domain-neutral
        # formulation hint; all other actions point to existing records.
        if not ref_list and category != "formulate_test":
            return
        _append_bounded(
            suggested,
            {"category": category, "refs": ref_list[: limits.max_items]},
            limit=limits.max_items,
            omitted=omitted,
            key="suggested_actions",
        )

    no_test_hypotheses = [
        identifier
        for identifier in untested_hypothesis_ids
        if identifier in unresolved_ids
    ]
    if no_test_hypotheses or not hypotheses:
        add_action("formulate_test", no_test_hypotheses)
    add_action("execute_test", untested_ids)
    add_action("gather_missing_evidence", bad_execution_ids)
    ready_ids = [
        identifier
        for identifier in unresolved_ids
        if identifier in hypotheses_with_clean_evidence
    ]
    add_action("seek_contradiction", ready_ids)
    no_finding_ready = [
        identifier
        for identifier in ready_ids
        if not findings_by_hypothesis.get(identifier)
    ]
    add_action("record_finding", no_finding_ready)
    substantive_reasons = [reason for reason in reasons if reason != "investigation_active"]
    if (state.status == "completed" and (unresolved_ids or coverage_gap_count)) or (
        state.status == "active" and not substantive_reasons
    ):
        add_action("stop/reopen", [_identifier(state.investigation_id)])

    stop_reason = _iter_mapping(state.stop_reason)
    stop = {
        "status": _text(state.status, limit=128),
        "kind": _text(stop_reason.get("kind"), limit=128),
        "reason": _text(stop_reason.get("detail"), limit=limits.max_text_chars),
        "present": bool(stop_reason),
    }
    complete = not reasons
    summary: Dict[str, Any] = {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "advisory": True,
        "status": "ok",
        "valid": True,
        "source_kind": kind,
        "investigation_id": _identifier(state.investigation_id),
        "state_status": _text(state.status, limit=128),
        "stop": stop,
        "progress": progress,
        "unresolved_hypotheses": unresolved_rows,
        "untested_hypotheses": untested_hypothesis_rows,
        "untested_tests": untested_rows,
        "execution_gaps": execution_gap_rows,
        "finding_gaps": finding_gap_rows,
        "coverage_gaps": coverage_rows,
        "suggested_actions": suggested,
        "advisory_completeness": {
            "complete": complete,
            "advisory_only": True,
            "reasons": reasons,
        },
        "omitted": omitted,
        "truncated": any(value > 0 for value in omitted.values()),
    }
    return _fit_output(summary, limits)


def summarize_investigation(
    source: Union[InvestigationState, InvestigationStore, Mapping[str, Any], str, Path],
    *,
    max_items: int = MAX_SUMMARY_ITEMS,
    max_text_chars: int = MAX_SUMMARY_TEXT,
    max_output_chars: int = MAX_SUMMARY_OUTPUT_CHARS,
    max_source_bytes: int = MAX_SUMMARY_SOURCE_BYTES,
    strict: bool = False,
) -> Dict[str, Any]:
    """Return a deterministic, bounded advisory summary.

    ``source`` may be a validated :class:`InvestigationState`, an
    :class:`InvestigationStore`, a JSON mapping, or a path.  Loading is
    read-only.  Invalid, corrupt, missing, or oversized inputs produce a
    bounded ``valid: false`` envelope by default; ``strict=True`` raises
    :class:`InvestigationSummaryError` with a stable code instead.
    """

    kind = _source_kind(source)
    try:
        limits = SummaryLimits(
            max_items=max_items,
            max_text_chars=max_text_chars,
            max_output_chars=max_output_chars,
            max_source_bytes=max_source_bytes,
        )
        state, kind = _load_state(source, limits=limits)
        return _summary_for_state(state, kind=kind, limits=limits)
    except (
        InvestigationSummaryError,
        InvestigationError,
        OSError,
        ValueError,
        TypeError,
        KeyError,
        OverflowError,
        RecursionError,
    ) as exc:
        if isinstance(exc, InvestigationSummaryError):
            code = str(exc) or "source_invalid"
        else:
            code = "source_invalid"
        if strict:
            raise InvestigationSummaryError(code) from exc
        limits = SummaryLimits()
        return _error_summary(kind, code, limits=limits)


# A concise alias is convenient for hosts that treat summaries as a read-only
# operation, while the longer name remains the discoverable public contract.
investigation_summary = summarize_investigation


__all__ = [
    "InvestigationSummaryError",
    "MAX_SUMMARY_ITEMS",
    "MAX_SUMMARY_OUTPUT_CHARS",
    "MAX_SUMMARY_SOURCE_BYTES",
    "MAX_SUMMARY_TEXT",
    "SUMMARY_SCHEMA_VERSION",
    "SummaryLimits",
    "investigation_summary",
    "summarize_investigation",
]
