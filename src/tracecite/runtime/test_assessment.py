"""Evidence-backed assessment for declared investigation Tests.

A Test is the Agent's explicit statement of what it intends to verify for a
Hypothesis. Runtime does not decide whether the natural-language interpretation
is correct; it verifies that a decisive Test assessment is grounded in
immutable Evidence formally linked to that Test.

Free exploration may happen before a Test is declared. Previously observed
Evidence is not silently grandfathered into a later Test: the Agent must
explicitly confirm/relink exact immutable Evidence refs to the Test before they
can support a decisive assessment. This preserves exploration flexibility while
keeping the epistemic contract auditable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Sequence

from .investigation import InvestigationError, InvestigationState, InvestigationStore


TEST_ASSESSMENT_OUTCOMES = frozenset({"supported", "contradicted", "unknown"})
_TEST_ASSESSMENT_OPERATION = "assess_test"
_CONFIRM_EVIDENCE_OPERATION = "confirm_test_evidence"
_EVIDENCE_URI_RE = re.compile(
    r"^evidence://sha256/(?P<digest>[0-9a-fA-F]{64})"
    r"#L(?P<start>[1-9][0-9]*)(?:-L(?P<end>[1-9][0-9]*))?$"
)


@dataclass(frozen=True)
class TestAssessmentValidation:
    """Mechanical validation result for one proposed Test assessment."""

    valid: bool
    test_id: str
    hypothesis_id: str
    outcome: str
    evidence_refs: Sequence[str] = field(default_factory=tuple)
    reasons: Sequence[str] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid": self.valid,
            "test_id": self.test_id,
            "hypothesis_id": self.hypothesis_id,
            "outcome": self.outcome,
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
    """Evidence-bearing executions that may be explicitly confirmed for a later Test.

    Assessment executions are derived epistemic records and therefore are never
    a source for relinking. Confirmation executions are allowed because they
    preserve the original immutable Evidence pointer and provenance chain.
    """

    return [
        item
        for item in state.executions
        if str(item.get("operation") or "") != _TEST_ASSESSMENT_OPERATION
    ]


def _pointer_index(
    executions: Sequence[Mapping[str, Any]],
) -> dict[str, tuple[Mapping[str, Any], Mapping[str, Any]]]:
    result: dict[str, tuple[Mapping[str, Any], Mapping[str, Any]]] = {}
    for execution in executions:
        for item in execution.get("evidence") or []:
            if not isinstance(item, Mapping):
                continue
            uri = str(item.get("uri") or "").strip()
            if uri and uri not in result:
                result[uri] = (execution, item)
    return result


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


def confirm_test_evidence(
    store: InvestigationStore,
    test_id: str,
    *,
    evidence_refs: Sequence[str],
) -> Dict[str, Any]:
    """Explicitly bind previously observed immutable Evidence to a declared Test.

    This is the safe bridge from free exploration to formal verification.
    Evidence is not copied merely because it appeared earlier: every requested
    ref must already exist in this Investigation, be line-addressable, and come
    from an execution with mechanically acceptable status/coverage/integrity.

    The confirmation itself is persisted as a Test-linked execution, so later
    decisive assessment uses the normal same-Test evidence rule.
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

    pointer_index = _pointer_index(_relinkable_executions(state))
    reasons: list[str] = []
    origin_execution_ids: list[str] = []
    evidence: list[dict[str, Any]] = []

    for ref in refs:
        match = _EVIDENCE_URI_RE.fullmatch(ref)
        if match is None:
            reasons.append("non_citable_confirmed_evidence")
            continue
        end = match.group("end")
        if end is not None and int(end) < int(match.group("start")):
            reasons.append("invalid_confirmed_evidence_range")
            continue
        source = pointer_index.get(ref)
        if source is None:
            reasons.append("confirmed_evidence_not_in_investigation")
            continue
        execution, pointer = source
        reasons.extend(_source_validation_reasons(execution))
        execution_id = str(execution.get("id") or "").strip()
        if execution_id and execution_id not in origin_execution_ids:
            origin_execution_ids.append(execution_id)
        evidence.append(dict(pointer))

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
            "confirmation_contract": "prior_evidence_relinked_v1",
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
    """Validate a Test assessment against Evidence formally linked to the Test.

    ``supported`` and ``contradicted`` are decisive and therefore require at
    least one immutable line-addressable Evidence pointer from an execution of
    the same Test. Free-exploration Evidence can become eligible only through
    ``confirm_test_evidence``. ``unknown`` is always a safe epistemic fallback
    and may be recorded without Evidence.
    """

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
    pointer_index = _pointer_index(source_executions)

    for ref in refs:
        match = _EVIDENCE_URI_RE.fullmatch(ref)
        if match is None:
            reasons.append("non_citable_assessment_evidence")
            continue
        end = match.group("end")
        if end is not None and int(end) < int(match.group("start")):
            reasons.append("invalid_assessment_evidence_range")
        if ref not in pointer_index:
            reasons.append("assessment_evidence_not_from_test")

    for ref in refs:
        source = pointer_index.get(ref)
        if source is None:
            continue
        execution, _ = source
        reasons.extend(_source_validation_reasons(execution))

    if decisive and _coverage_has_blocking_gap(coverage or {}):
        reasons.append("assessment_coverage_gap")

    deduped = tuple(dict.fromkeys(reasons))
    return TestAssessmentValidation(
        valid=not deduped,
        test_id=resolved_test,
        hypothesis_id=hypothesis_id,
        outcome=resolved_outcome,
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
    """Persist one evidence-backed Test assessment as a linked Execution.

    Re-assessment is allowed after new Evidence is collected or confirmed;
    Finding validation uses the latest assessment for each declared Test.
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
            "Test Assessment 拒绝未经验证的决定性评估；"
            f"test_id={validation.test_id}, outcome={validation.outcome}, reasons={reasons}."
        )

    state = store.load()
    source_executions = _source_executions(state, validation.test_id)
    pointer_index = _pointer_index(source_executions)
    evidence = [dict(pointer_index[ref][1]) for ref in validation.evidence_refs if ref in pointer_index]
    result = {
        "status": "ok",
        "outcome": validation.outcome,
        "evidence": evidence,
        "coverage": dict(coverage or {}),
        "verification": {"assessment_contract": "evidence_backed_test_v1"},
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
    "TestAssessmentValidation",
    "assess_test",
    "confirm_test_evidence",
    "latest_test_assessments",
    "validate_test_assessment",
]
