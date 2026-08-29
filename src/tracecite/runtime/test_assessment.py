"""Evidence-grounded bookkeeping for declared investigation Tests.

A Test is the Agent's explicit statement of what it intends to verify for a
Hypothesis. ``assess_test`` records the Agent's semantic judgment about that
Test. Runtime does not certify that the natural-language judgment is true; it
only verifies the mechanical evidence contract: cited Evidence was actually
materialized, is immutable/line-addressable, is linked to the Test, and has no
known blocking coverage or integrity defect.

Free exploration may happen before a Test is declared. Previously observed
Evidence is not silently grandfathered into a later Test: the Agent must
explicitly confirm/relink immutable line-addressable Evidence that was actually
materialized by a recorded execution before it can be used by that Test. This
preserves exploration flexibility while keeping the evidence trail auditable.

A future Runtime-mechanical Test verdict must come from a deterministic
assertion/capability path. It must not be created by letting an Agent label its
own semantic interpretation as Runtime-verified.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Sequence

from .investigation import InvestigationError, InvestigationState, InvestigationStore


TEST_ASSESSMENT_OUTCOMES = frozenset({"supported", "contradicted", "unknown"})
TEST_ASSESSMENT_SOURCE_AGENT = "agent"
_TEST_ASSESSMENT_OPERATION = "assess_test"
_CONFIRM_EVIDENCE_OPERATION = "confirm_test_evidence"
_EVIDENCE_URI_RE = re.compile(
    r"^evidence://sha256/(?P<digest>[0-9a-fA-F]{64})"
    r"#L(?P<start>[1-9][0-9]*)(?:-L(?P<end>[1-9][0-9]*))?$"
)


@dataclass(frozen=True)
class TestAssessmentValidation:
    """Mechanical grounding result for one Agent-proposed Test assessment."""

    valid: bool
    test_id: str
    hypothesis_id: str
    outcome: str
    assessment_source: str = TEST_ASSESSMENT_SOURCE_AGENT
    evidence_refs: Sequence[str] = field(default_factory=tuple)
    reasons: Sequence[str] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid": self.valid,
            "test_id": self.test_id,
            "hypothesis_id": self.hypothesis_id,
            "outcome": self.outcome,
            "assessment_source": self.assessment_source,
            "evidence_refs": list(self.evidence_refs),
            "reasons": list(self.reasons),
        }


def _normalize_refs(values: Sequence[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _coverage_has_blocking_gap(value: Any) -> bool:
    """Detect explicit incompleteness without interpreting domain semantics."""

    if isinstance(value, Mapping):
        for raw_key, child in value.items():
            key = str(raw_key).strip().lower()
            if key in {"evidence_truncated", "truncated", "omitted", "incomplete"} and child is True:
                return True
            if key in {"complete", "accepted", "integrity_checked"} and child is False:
                return True
            if key in {"missing_evidence", "missing", "coverage_warning", "warnings"}:
                if child not in (None, False, "", [], {}, ()):
                    return True
            if _coverage_has_blocking_gap(child):
                return True
        return False
    if isinstance(value, (list, tuple)):
        return any(_coverage_has_blocking_gap(item) for item in value)
    return False


def _state(store_or_state: InvestigationStore | InvestigationState) -> InvestigationState:
    return store_or_state.load() if isinstance(store_or_state, InvestigationStore) else store_or_state


def _find_test(state: InvestigationState, test_id: str) -> Mapping[str, Any]:
    for item in state.tests:
        if str(item.get("id") or "") == test_id:
            return item
    raise InvestigationError(f"未知 test: {test_id}")


def _source_executions(state: InvestigationState, test_id: str) -> list[Mapping[str, Any]]:
    return [
        item
        for item in state.executions
        if str(item.get("test_id") or "") == test_id
        and str(item.get("operation") or "") != _TEST_ASSESSMENT_OPERATION
    ]


def _relinkable_executions(state: InvestigationState) -> list[Mapping[str, Any]]:
    """Evidence-bearing executions that may be explicitly confirmed for a later Test."""

    return [
        item
        for item in state.executions
        if str(item.get("operation") or "") != _TEST_ASSESSMENT_OPERATION
    ]


def _parse_evidence_ref(ref: str) -> tuple[str, int, int] | None:
    match = _EVIDENCE_URI_RE.fullmatch(str(ref or "").strip())
    if match is None:
        return None
    start = int(match.group("start"))
    end = int(match.group("end") or match.group("start"))
    if end < start:
        return None
    return match.group("digest").lower(), start, end


def _pointer_digest(pointer: Mapping[str, Any]) -> str:
    raw = str(pointer.get("sha256") or "").strip().lower()
    if re.fullmatch(r"[0-9a-f]{64}", raw):
        return raw
    parsed = _parse_evidence_ref(str(pointer.get("uri") or ""))
    return parsed[0] if parsed is not None else ""


def _materialized_ranges(
    execution: Mapping[str, Any],
    pointer: Mapping[str, Any],
) -> list[tuple[int, int]]:
    """Return line ranges that this execution demonstrably materialized.

    A canonical EvidencePointer may identify only the anchor hit (for example
    ``#L506``) while a bounded range retrieval visibly materializes the full
    context window (for example L494-L518). Precise citations inside that
    recorded window are legitimate evidence and must not be rejected merely
    because they are not byte-for-byte equal to the anchor URI.
    """

    ranges: list[tuple[int, int]] = []
    parsed = _parse_evidence_ref(str(pointer.get("uri") or ""))
    if parsed is not None:
        ranges.append((parsed[1], parsed[2]))

    try:
        start = int(pointer.get("start_line"))
        end = int(pointer.get("end_line", start))
        if start >= 1 and end >= start:
            ranges.append((start, end))
    except (TypeError, ValueError):
        pass

    coverage = execution.get("coverage") or {}
    if isinstance(coverage, Mapping):
        for start_key, end_key in (
            ("context_start_line", "context_end_line"),
            ("start_line", "end_line"),
        ):
            try:
                start = int(coverage.get(start_key))
                end = int(coverage.get(end_key))
            except (TypeError, ValueError):
                continue
            if start >= 1 and end >= start:
                ranges.append((start, end))

    return list(dict.fromkeys(ranges))


def _source_validation_reasons(execution: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    status = str(execution.get("status") or "").strip().lower()
    if status == "no_match":
        reasons.append("assessment_source_no_match")
    elif status in {"partial", "error"}:
        reasons.append("assessment_source_incomplete")
    recording = execution.get("recording") or {}
    if isinstance(recording, Mapping) and any(
        recording.get(key) is True
        for key in ("evidence_truncated", "warnings_truncated", "error_truncated")
    ):
        reasons.append("assessment_source_truncated")
    if _coverage_has_blocking_gap(execution.get("coverage") or {}):
        reasons.append("assessment_source_coverage_gap")
    verification = execution.get("verification") or {}
    if isinstance(verification, Mapping) and verification.get("integrity_checked") is False:
        reasons.append("assessment_source_unverified")
    return reasons


def _matching_materialized_sources(
    executions: Sequence[Mapping[str, Any]],
    ref: str,
) -> list[tuple[Mapping[str, Any], dict[str, Any]]]:
    """Find recorded executions that actually exposed the requested line range."""

    requested = _parse_evidence_ref(ref)
    if requested is None:
        return []
    digest, requested_start, requested_end = requested
    matches: list[tuple[Mapping[str, Any], dict[str, Any]]] = []
    for execution in executions:
        for raw_pointer in execution.get("evidence") or []:
            if not isinstance(raw_pointer, Mapping):
                continue
            if _pointer_digest(raw_pointer) != digest:
                continue
            if not any(
                start <= requested_start and requested_end <= end
                for start, end in _materialized_ranges(execution, raw_pointer)
            ):
                continue
            pointer = dict(raw_pointer)
            pointer["uri"] = ref
            pointer["sha256"] = digest
            pointer["start_line"] = requested_start
            pointer["end_line"] = requested_end
            matches.append((execution, pointer))
            break
    return matches


def _best_materialized_source(
    executions: Sequence[Mapping[str, Any]],
    ref: str,
) -> tuple[Mapping[str, Any], dict[str, Any]] | None:
    """Prefer any mechanically clean observation when a line was seen repeatedly."""

    candidates = _matching_materialized_sources(executions, ref)
    for execution, pointer in candidates:
        if not _source_validation_reasons(execution):
            return execution, pointer
    return candidates[0] if candidates else None


def confirm_test_evidence(
    store: InvestigationStore,
    test_id: str,
    *,
    evidence_refs: Sequence[str],
) -> Dict[str, Any]:
    """Explicitly bind previously materialized Evidence to a declared Test.

    This is the safe bridge from free exploration to formal verification. Every
    requested line range must have actually been visible in a recorded execution
    of the same immutable source digest. The original execution must also have
    an acceptable status, coverage and integrity state. The confirmation itself
    is persisted as a Test-linked execution, so later assessment uses the normal
    same-Test evidence rule.
    """

    if not isinstance(store, InvestigationStore):
        raise TypeError("confirm_test_evidence requires InvestigationStore")

    state = store.load()
    resolved_test = str(test_id or "").strip()
    test = _find_test(state, resolved_test)
    hypothesis_id = str(test.get("hypothesis_id") or "").strip()
    refs = _normalize_refs(evidence_refs)
    if not refs:
        raise InvestigationError("confirm_test_evidence 至少需要一个 evidence ref")

    relinkable = _relinkable_executions(state)
    reasons: list[str] = []
    origin_execution_ids: list[str] = []
    evidence: list[dict[str, Any]] = []

    for ref in refs:
        parsed = _parse_evidence_ref(ref)
        if parsed is None:
            reasons.append("non_citable_confirmed_evidence")
            continue
        candidates = _matching_materialized_sources(relinkable, ref)
        if not candidates:
            reasons.append("confirmed_evidence_not_materialized")
            continue
        clean = [
            (execution, pointer)
            for execution, pointer in candidates
            if not _source_validation_reasons(execution)
        ]
        if not clean:
            for execution, _ in candidates:
                reasons.extend(_source_validation_reasons(execution))
            continue
        execution, pointer = clean[0]
        execution_id = str(execution.get("id") or "").strip()
        if execution_id and execution_id not in origin_execution_ids:
            origin_execution_ids.append(execution_id)
        evidence.append(pointer)

    deduped = list(dict.fromkeys(reasons))
    if deduped:
        raise InvestigationError(
            "Test Evidence Confirmation 拒绝不满足机械证据要求的引用；"
            f"test_id={resolved_test}, reasons={', '.join(deduped)}."
        )

    result = {
        "status": "ok",
        "outcome": "not_assessed",
        "evidence": evidence,
        "coverage": {"complete": True},
        "verification": {
            "integrity_checked": True,
            "confirmation_contract": "materialized_window_relinked_v2",
        },
    }
    execution = store.record_execution(
        _CONFIRM_EVIDENCE_OPERATION,
        result,
        hypothesis_id=hypothesis_id,
        test_id=resolved_test,
        parameters={
            "evidence_refs": refs,
            "origin_execution_ids": origin_execution_ids,
        },
    )
    return {
        "test_id": resolved_test,
        "hypothesis_id": hypothesis_id,
        "evidence_refs": refs,
        "origin_execution_ids": origin_execution_ids,
        "execution_id": execution["id"],
        "recorded_at": execution["recorded_at"],
    }


def validate_test_assessment(
    store_or_state: InvestigationStore | InvestigationState,
    test_id: str,
    outcome: str,
    *,
    evidence_refs: Sequence[str] = (),
    coverage: Mapping[str, Any] | None = None,
) -> TestAssessmentValidation:
    """Check only the mechanical grounding of an Agent Test assessment."""

    state = _state(store_or_state)
    resolved_test = str(test_id or "").strip()
    test = _find_test(state, resolved_test)
    hypothesis_id = str(test.get("hypothesis_id") or "").strip()
    resolved_outcome = str(outcome or "").strip().lower()
    if resolved_outcome not in TEST_ASSESSMENT_OUTCOMES:
        raise InvestigationError("test assessment outcome 必须是 supported / contradicted / unknown")

    refs = _normalize_refs(evidence_refs)
    reasons: list[str] = []
    decisive = resolved_outcome in {"supported", "contradicted"}
    if decisive and not refs:
        reasons.append("missing_assessment_evidence")

    source_executions = _source_executions(state, resolved_test)
    for ref in refs:
        if _parse_evidence_ref(ref) is None:
            reasons.append("non_citable_assessment_evidence")
            continue
        source = _best_materialized_source(source_executions, ref)
        if source is None:
            reasons.append("assessment_evidence_not_from_test")
            continue
        execution, _pointer = source
        source_reasons = _source_validation_reasons(execution)
        if source_reasons:
            reasons.extend(source_reasons)

    if decisive and _coverage_has_blocking_gap(coverage or {}):
        reasons.append("assessment_coverage_gap")

    deduped = tuple(dict.fromkeys(reasons))
    return TestAssessmentValidation(
        valid=not deduped,
        test_id=resolved_test,
        hypothesis_id=hypothesis_id,
        outcome=resolved_outcome,
        assessment_source=TEST_ASSESSMENT_SOURCE_AGENT,
        evidence_refs=tuple(refs),
        reasons=deduped,
    )


def assess_test(
    store: InvestigationStore,
    test_id: str,
    outcome: str,
    *,
    evidence_refs: Sequence[str] = (),
    coverage: Mapping[str, Any] | None = None,
    limitations: Sequence[str] = (),
) -> Dict[str, Any]:
    """Persist an Agent semantic assessment with mechanically checked Evidence.

    ``supported`` here means "the Agent judges this Test supported by these
    cited observations". It does *not* mean Runtime has mechanically verified
    the natural-language semantics of the Test.
    """

    if not isinstance(store, InvestigationStore):
        raise TypeError("assess_test requires InvestigationStore")
    validation = validate_test_assessment(
        store,
        test_id,
        outcome,
        evidence_refs=evidence_refs,
        coverage=coverage,
    )
    if not validation.valid:
        reasons = ", ".join(validation.reasons) or "unknown"
        raise InvestigationError(
            "Test Assessment 拒绝不满足机械证据约束的评估；"
            f"test_id={validation.test_id}, outcome={validation.outcome}, reasons={reasons}."
        )

    state = store.load()
    source_executions = _source_executions(state, validation.test_id)
    evidence: list[dict[str, Any]] = []
    for ref in validation.evidence_refs:
        source = _best_materialized_source(source_executions, ref)
        if source is not None and not _source_validation_reasons(source[0]):
            evidence.append(source[1])
    result = {
        "status": "ok",
        "outcome": validation.outcome,
        "evidence": evidence,
        "coverage": dict(coverage or {}),
        "verification": {
            "assessment_contract": "agent_semantic_evidence_grounded_v2",
            "assessment_source": TEST_ASSESSMENT_SOURCE_AGENT,
            "evidence_binding_verified": True,
            "semantic_claim_verified": False,
        },
    }
    execution = store.record_execution(
        _TEST_ASSESSMENT_OPERATION,
        result,
        hypothesis_id=validation.hypothesis_id,
        test_id=validation.test_id,
        parameters={
            "evidence_refs": list(validation.evidence_refs),
            "limitations": [str(item) for item in limitations if str(item).strip()],
        },
    )
    return {
        "test_id": validation.test_id,
        "hypothesis_id": validation.hypothesis_id,
        "outcome": validation.outcome,
        "assessment_source": TEST_ASSESSMENT_SOURCE_AGENT,
        "semantic_claim_verified": False,
        "evidence_refs": list(validation.evidence_refs),
        "execution_id": execution["id"],
        "recorded_at": execution["recorded_at"],
    }


def latest_test_assessments(
    state: InvestigationState,
    hypothesis_id: str,
) -> Dict[str, Mapping[str, Any]]:
    """Return the latest persisted assessment Execution for every assessed Test."""

    test_ids = {
        str(item.get("id") or "")
        for item in state.tests
        if str(item.get("hypothesis_id") or "") == hypothesis_id
    }
    result: Dict[str, Mapping[str, Any]] = {}
    for execution in state.executions:
        test_id = str(execution.get("test_id") or "")
        if (
            test_id in test_ids
            and str(execution.get("operation") or "") == _TEST_ASSESSMENT_OPERATION
        ):
            result[test_id] = execution
    return result


__all__ = [
    "TEST_ASSESSMENT_OUTCOMES",
    "TEST_ASSESSMENT_SOURCE_AGENT",
    "TestAssessmentValidation",
    "assess_test",
    "confirm_test_evidence",
    "latest_test_assessments",
    "validate_test_assessment",
]
