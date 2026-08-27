"""Mechanical validation for proposed investigation Findings.

The validator intentionally checks only claims TraceCite can verify from
InvestigationState.  It does not interpret natural-language causality.  Its job
is to prevent a host from presenting an ungrounded decisive Finding as if it
were TraceCite-validated.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Sequence

from .investigation import FINDING_OUTCOMES, InvestigationError, InvestigationState, InvestigationStore

_EVIDENCE_URI_RE = re.compile(
    r"^evidence://sha256/(?P<digest>[0-9a-fA-F]{64})"
    r"#L(?P<start>[1-9][0-9]*)(?:-L(?P<end>[1-9][0-9]*))?$"
)
_DECISIVE_OUTCOMES = frozenset({"supported", "contradicted"})
_BLOCKING_STATUSES = frozenset({"partial", "error"})


@dataclass(frozen=True)
class FindingValidationResult:
    """Result of validating one proposed Finding against persisted state."""

    valid: bool
    requested_outcome: str
    validated_outcome: str
    reasons: Sequence[str] = field(default_factory=tuple)
    hypothesis_id: str = ""
    test_ids: Sequence[str] = field(default_factory=tuple)
    execution_ids: Sequence[str] = field(default_factory=tuple)
    supporting_evidence: Sequence[str] = field(default_factory=tuple)
    contradicting_evidence: Sequence[str] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid": self.valid,
            "requested_outcome": self.requested_outcome,
            "validated_outcome": self.validated_outcome,
            "reasons": list(self.reasons),
            "hypothesis_id": self.hypothesis_id,
            "test_ids": list(self.test_ids),
            "execution_ids": list(self.execution_ids),
            "supporting_evidence": list(self.supporting_evidence),
            "contradicting_evidence": list(self.contradicting_evidence),
        }


def _normalize_refs(values: Sequence[str]) -> List[str]:
    result: List[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _execution_evidence_uris(execution: Mapping[str, Any]) -> List[str]:
    result: List[str] = []
    for item in execution.get("evidence") or []:
        if not isinstance(item, Mapping):
            continue
        uri = str(item.get("uri") or "").strip()
        if uri and uri not in result:
            result.append(uri)
    return result


def _coverage_has_blocking_gap(value: Any) -> bool:
    """Detect explicit incompleteness without inventing domain semantics."""

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


def validate_finding(
    store_or_state: InvestigationStore | InvestigationState,
    hypothesis_id: str,
    outcome: str,
    *,
    supporting_evidence: Sequence[str] = (),
    contradicting_evidence: Sequence[str] = (),
    coverage: Mapping[str, Any] | None = None,
) -> FindingValidationResult:
    """Validate whether a proposed Finding may be treated as decisive.

    Decisive Findings must be grounded in at least one executed Test, cite only
    immutable line-addressable Evidence produced by those executions, and have
    no explicit execution/coverage gaps. ``no_match`` is never accepted as
    decisive proof by itself, and an execution that explicitly reports failed
    integrity verification cannot certify a Finding. ``unknown`` remains valid
    with less evidence because uncertainty is the safe fallback.
    """

    state = store_or_state.load() if isinstance(store_or_state, InvestigationStore) else store_or_state
    requested_outcome = str(outcome or "").strip().lower()
    if requested_outcome not in FINDING_OUTCOMES:
        raise InvestigationError("finding outcome 必须是 supported / contradicted / unknown")

    hypothesis = next((item for item in state.hypotheses if item.get("id") == hypothesis_id), None)
    if hypothesis is None:
        raise InvestigationError(f"未知 hypothesis: {hypothesis_id}")

    support = _normalize_refs(supporting_evidence)
    contradiction = _normalize_refs(contradicting_evidence)
    tests = [item for item in state.tests if item.get("hypothesis_id") == hypothesis_id]
    test_ids = [str(item.get("id") or "") for item in tests]
    execution_ids: List[str] = []
    linked_executions: List[Mapping[str, Any]] = []
    by_id = {str(item.get("id") or ""): item for item in state.executions}
    for test in tests:
        for execution_id in test.get("execution_ids") or []:
            execution_id = str(execution_id or "")
            if execution_id and execution_id not in execution_ids:
                execution_ids.append(execution_id)
                if execution_id in by_id:
                    linked_executions.append(by_id[execution_id])

    reasons: List[str] = []
    decisive = requested_outcome in _DECISIVE_OUTCOMES
    required_refs = support if requested_outcome == "supported" else contradiction

    if decisive and not tests:
        reasons.append("no_test")
    if decisive and not linked_executions:
        reasons.append("test_not_executed")
    if requested_outcome == "supported" and not support:
        reasons.append("missing_supporting_evidence")
    if requested_outcome == "contradicted" and not contradiction:
        reasons.append("missing_contradicting_evidence")

    if decisive:
        for ref in required_refs:
            match = _EVIDENCE_URI_RE.match(ref)
            if not match:
                reasons.append("non_citable_evidence")
                continue
            end = match.group("end")
            if end is not None and int(end) < int(match.group("start")):
                reasons.append("invalid_evidence_range")

        available = {
            uri
            for execution in linked_executions
            for uri in _execution_evidence_uris(execution)
        }
        if any(ref not in available for ref in required_refs):
            reasons.append("evidence_not_from_linked_test")

        for execution in linked_executions:
            status = str(execution.get("status") or "").strip().lower()
            if status == "no_match":
                reasons.append("linked_execution_no_match")
            elif status in _BLOCKING_STATUSES:
                reasons.append("linked_execution_incomplete")

            recording = execution.get("recording") or {}
            if isinstance(recording, Mapping) and any(
                recording.get(key) is True
                for key in ("evidence_truncated", "warnings_truncated", "error_truncated")
            ):
                reasons.append("linked_execution_truncated")

            verification = execution.get("verification") or {}
            if isinstance(verification, Mapping) and verification.get("integrity_checked") is False:
                reasons.append("linked_execution_unverified")

            if _coverage_has_blocking_gap(execution.get("coverage") or {}):
                reasons.append("linked_execution_coverage_gap")

        if _coverage_has_blocking_gap(coverage or {}):
            reasons.append("finding_coverage_gap")

    deduped_reasons: List[str] = []
    for reason in reasons:
        if reason not in deduped_reasons:
            deduped_reasons.append(reason)

    valid = not deduped_reasons
    validated_outcome = requested_outcome if valid else "unknown"
    return FindingValidationResult(
        valid=valid,
        requested_outcome=requested_outcome,
        validated_outcome=validated_outcome,
        reasons=tuple(deduped_reasons),
        hypothesis_id=hypothesis_id,
        test_ids=tuple(test_ids),
        execution_ids=tuple(execution_ids),
        supporting_evidence=tuple(support),
        contradicting_evidence=tuple(contradiction),
    )
