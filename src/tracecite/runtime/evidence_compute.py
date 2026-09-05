"""Bounded batch computation over one TraceCite evidence source.

The first Evidence Compute slice deliberately reuses existing Evidence Shell
semantics. A caller supplies several *already chosen* mechanical aggregate
programs; TraceCite keeps them behind one Agent/tool boundary and fuses
compatible JSONL scans. It does not choose analyses, hypotheses, causal tests,
or stopping conditions.

Large intermediate rows never cross the model boundary. SourceVersion,
Segmenter/canonical fallback, provenance, and Host-owned transport policy remain
authoritative.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from tracecite_core.segmenter import detect_segmenter_kind

from .evidence_shell import _budget_data, _payload_fits
from .evidence_shell_agent import run_evidence_shell
from .evidence_shell_agent_compat import normalize_agent_evidence_shell_program
from .evidence_shell_compat import normalize_evidence_shell_program
from .evidence_shell_fast_jsonl import (
    _SPECIAL_FIELDS,
    _matches,
    _postprocess,
    _referenced_fields,
    _split,
    _tokenize,
    _value,
)
from .evidence_shell_public import EvidenceShellPolicy, EvidenceShellRequest
from .retrieval_session import RetrievalSessionStore
from .schema import AgentResult
from .source_versions import SourceVersionStore


MAX_BATCH_ANALYSES = 16


@dataclass(frozen=True)
class EvidenceAnalysisSpec:
    """One caller-selected mechanical aggregate program in a batch."""

    name: str
    program: str

    def __post_init__(self) -> None:
        name = str(self.name or "").strip()
        program = str(self.program or "").strip()
        if not name:
            raise ValueError("analysis name is required")
        if len(name) > 80:
            raise ValueError("analysis name must be at most 80 characters")
        if not program:
            raise ValueError("analysis program is required")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "program", program)


@dataclass(frozen=True)
class EvidenceComputeRequest:
    """Several bounded mechanical analyses over one logical source."""

    source: str | Path
    analyses: tuple[EvidenceAnalysisSpec, ...]
    segmenter: str = "auto"

    def __post_init__(self) -> None:
        analyses = tuple(self.analyses)
        if not analyses:
            raise ValueError("at least one analysis is required")
        if len(analyses) > MAX_BATCH_ANALYSES:
            raise ValueError(f"at most {MAX_BATCH_ANALYSES} analyses are allowed per batch")
        names = [item.name for item in analyses]
        if len(names) != len(set(names)):
            raise ValueError("analysis names must be unique")
        object.__setattr__(self, "analyses", analyses)


@dataclass
class _CompiledJsonlAnalysis:
    spec: EvidenceAnalysisSpec
    normalized: str
    predicates: list[Any]
    aggregate_stage: Any
    post: list[Any]
    raw_predicates: list[Any]
    field_predicates: list[Any]
    matched: int = 0
    counts: dict[str, int] | None = None

    def __post_init__(self) -> None:
        if self.counts is None:
            self.counts = {}

    @property
    def needs_json(self) -> bool:
        return bool(self.field_predicates) or self.aggregate_stage.command != "count"


def _compile_jsonl(spec: EvidenceAnalysisSpec) -> _CompiledJsonlAnalysis | None:
    try:
        agent_normalized = normalize_agent_evidence_shell_program(spec.program)
        normalized = normalize_evidence_shell_program(agent_normalized)
        stages = _tokenize(normalized)
        split = _split(stages)
    except ValueError:
        return None
    if split is None or _referenced_fields(stages) & _SPECIAL_FIELDS:
        return None
    predicates, aggregate_stage, post = split
    return _CompiledJsonlAnalysis(
        spec=spec,
        normalized=normalized,
        predicates=predicates,
        aggregate_stage=aggregate_stage,
        post=post,
        raw_predicates=[
            stage
            for stage in predicates
            if stage.command in {"search", "regex", "exclude", "exclude-regex", "all"}
        ],
        field_predicates=[
            stage
            for stage in predicates
            if stage.command not in {"search", "regex", "exclude", "exclude-regex", "all"}
        ],
    )


def _finalize_analysis(
    compiled: _CompiledJsonlAnalysis,
    *,
    policy: EvidenceShellPolicy,
) -> dict[str, Any]:
    aggregate_stage = compiled.aggregate_stage
    aggregate_field = aggregate_stage.args[0] if aggregate_stage.args else None
    if aggregate_stage.command == "count":
        aggregate: dict[str, Any] = {"count": compiled.matched}
    else:
        counts = compiled.counts or {}
        ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        if aggregate_stage.command == "group":
            aggregate = {
                "field": aggregate_field,
                "groups": [{"key": key, "count": count} for key, count in ordered],
                "group_total": len(ordered),
            }
        else:
            aggregate = {
                "field": aggregate_field,
                "values": [key for key, _ in ordered],
                "distinct_total": len(ordered),
            }
        aggregate = _postprocess(aggregate, aggregate_stage.command, compiled.post)

    output = {
        "name": compiled.spec.name,
        "status": "ok",
        "program": compiled.normalized,
        "coverage": {"complete": True, "match_records": compiled.matched},
        "aggregate": aggregate,
    }
    fits, token_count, byte_count = _payload_fits(output, policy)
    if fits:
        return output
    return {
        "name": compiled.spec.name,
        "status": "too_broad",
        "program": compiled.normalized,
        "coverage": {"complete": True, "match_records": compiled.matched},
        "reason": "AGGREGATE_OUTPUT_BUDGET_EXCEEDED",
        "observed_at_least_tokens": token_count,
        "observed_at_least_bytes": byte_count,
    }


def _try_shared_jsonl(
    request: EvidenceComputeRequest,
    *,
    policy: EvidenceShellPolicy,
    session: RetrievalSessionStore | None,
) -> dict[str, Any] | None:
    source = Path(request.source).expanduser().resolve()
    if not source.is_file():
        return None
    kind = detect_segmenter_kind(source) if request.segmenter == "auto" else request.segmenter
    if not isinstance(kind, str) or kind.strip().lower() not in {"jsonline", "json", "jsonl"}:
        return None

    compiled: list[_CompiledJsonlAnalysis] = []
    for spec in request.analyses:
        item = _compile_jsonl(spec)
        if item is None:
            return None
        compiled.append(item)

    version_store = (
        SourceVersionStore.for_session(session)
        if session is not None
        else SourceVersionStore(source.parent / ".tracecite")
    )
    view = version_store.resolve(
        source,
        mode=policy.source_mode,
        live_cut_timeout_seconds=policy.live_cut_timeout_seconds,
    )

    for segment in view.segments:
        with Path(segment.path).open("r", encoding="utf-8", errors="replace") as handle:
            for raw in handle:
                if not raw.strip():
                    continue

                raw_pass: list[_CompiledJsonlAnalysis] = []
                needs_json = False
                for item in compiled:
                    if any(not _matches({}, raw, stage) for stage in item.raw_predicates):
                        continue
                    raw_pass.append(item)
                    needs_json = needs_json or item.needs_json
                if not raw_pass:
                    continue

                obj: Mapping[str, Any] = {}
                if needs_json:
                    try:
                        decoded = json.loads(raw)
                        obj = decoded if isinstance(decoded, Mapping) else {}
                    except json.JSONDecodeError:
                        obj = {}

                for item in raw_pass:
                    if any(not _matches(obj, raw, stage) for stage in item.field_predicates):
                        continue
                    item.matched += 1
                    if item.aggregate_stage.command != "count":
                        field = str(item.aggregate_stage.args[0])
                        value = _value(obj, field)
                        key = "<missing>" if value is None else str(value)
                        assert item.counts is not None
                        item.counts[key] = item.counts.get(key, 0) + 1

    outputs = [_finalize_analysis(item, policy=policy) for item in compiled]
    result_data = {
        "outputs": outputs,
        "analysis_count": len(outputs),
        "source_view": view.to_dict(),
        "source_version": view.key,
        "evidence_budget": _budget_data(policy),
        "execution_engine": "jsonl_shared_scan_batch",
    }
    fits, token_count, byte_count = _payload_fits({"outputs": outputs}, policy)
    if not fits:
        return AgentResult(
            operation="evidence_compute",
            status="too_broad",
            outcome="not_assessed",
            coverage={"complete": False},
            data={
                "reason": "BATCH_OUTPUT_BUDGET_EXCEEDED",
                "analysis_count": len(outputs),
                "observed_at_least_tokens": token_count,
                "observed_at_least_bytes": byte_count,
                "source_view": view.to_dict(),
                "source_version": view.key,
                "evidence_budget": _budget_data(policy),
                "execution_engine": "jsonl_shared_scan_batch",
            },
        ).to_dict()

    statuses = {str(item.get("status") or "") for item in outputs}
    status = "ok" if statuses == {"ok"} else "partial"
    return AgentResult(
        operation="evidence_compute",
        status=status,
        outcome="not_assessed",
        coverage={"complete": all(item.get("status") == "ok" for item in outputs)},
        data=result_data,
    ).to_dict()


def _fallback_sequential(
    request: EvidenceComputeRequest,
    *,
    policy: EvidenceShellPolicy,
    session: RetrievalSessionStore | None,
) -> dict[str, Any]:
    outputs: list[dict[str, Any]] = []
    source_view: Mapping[str, Any] | None = None
    source_version: str | None = None

    for spec in request.analyses:
        result = run_evidence_shell(
            EvidenceShellRequest(
                source=request.source,
                program=spec.program,
                segmenter=request.segmenter,
            ),
            policy=policy,
            session=session,
        )
        data = result.get("data") if isinstance(result.get("data"), Mapping) else {}
        if source_view is None and isinstance(data.get("source_view"), Mapping):
            source_view = data.get("source_view")
        if source_version is None and data.get("source_version") is not None:
            source_version = str(data.get("source_version"))

        status = str(result.get("status") or "error")
        output: dict[str, Any] = {
            "name": spec.name,
            "status": status,
            "program": str(data.get("normalized_program") or data.get("program") or spec.program),
            "coverage": dict(result.get("coverage") or {}),
        }
        aggregate = data.get("aggregate")
        if status == "ok" and isinstance(aggregate, Mapping):
            output["aggregate"] = dict(aggregate)
        elif status == "ok":
            output["status"] = "error"
            output["error_code"] = "analysis_requires_bounded_aggregate"
            output["error"] = (
                "batch evidence compute currently accepts aggregate/scalar programs only; "
                "use tracecite_run for raw Evidence selection"
            )
        else:
            for key in ("error_code", "error", "guidance"):
                if result.get(key) is not None:
                    output[key] = result.get(key)
            if data.get("reason") is not None:
                output["reason"] = data.get("reason")
        outputs.append(output)

    fits, token_count, byte_count = _payload_fits({"outputs": outputs}, policy)
    if not fits:
        return AgentResult(
            operation="evidence_compute",
            status="too_broad",
            outcome="not_assessed",
            coverage={"complete": False},
            data={
                "reason": "BATCH_OUTPUT_BUDGET_EXCEEDED",
                "analysis_count": len(outputs),
                "observed_at_least_tokens": token_count,
                "observed_at_least_bytes": byte_count,
                "source_view": dict(source_view or {}),
                "source_version": source_version,
                "evidence_budget": _budget_data(policy),
                "execution_engine": "canonical_batch_fallback",
            },
        ).to_dict()

    statuses = {str(item.get("status") or "") for item in outputs}
    status = "ok" if statuses == {"ok"} else "partial"
    return AgentResult(
        operation="evidence_compute",
        status=status,
        outcome="not_assessed",
        coverage={"complete": all(item.get("status") == "ok" for item in outputs)},
        data={
            "outputs": outputs,
            "analysis_count": len(outputs),
            "source_view": dict(source_view or {}),
            "source_version": source_version,
            "evidence_budget": _budget_data(policy),
            "execution_engine": "canonical_batch_fallback",
        },
    ).to_dict()


def run_evidence_compute(
    request: EvidenceComputeRequest,
    *,
    policy: EvidenceShellPolicy,
    session: RetrievalSessionStore | None = None,
) -> dict[str, Any]:
    """Run caller-selected bounded aggregate programs behind one tool boundary."""

    if not isinstance(request, EvidenceComputeRequest):
        raise TypeError("run_evidence_compute requires EvidenceComputeRequest")
    if not isinstance(policy, EvidenceShellPolicy):
        raise TypeError("policy must be EvidenceShellPolicy")

    fused = _try_shared_jsonl(request, policy=policy, session=session)
    if fused is not None:
        return fused
    return _fallback_sequential(request, policy=policy, session=session)


__all__ = [
    "MAX_BATCH_ANALYSES",
    "EvidenceAnalysisSpec",
    "EvidenceComputeRequest",
    "run_evidence_compute",
]
