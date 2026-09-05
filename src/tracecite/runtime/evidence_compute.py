"""Bounded batch computation over one TraceCite evidence source.

A caller supplies several *already chosen* mechanical analyses. TraceCite keeps
them behind one Agent/tool boundary and compiles compatible JSONL work into one
shared physical scan. The Runtime never chooses analyses, hypotheses, causal
tests, or stopping conditions.

Large intermediate rows never cross the model boundary. SourceVersion,
Segmenter/canonical fallback, provenance, and Host-owned transport policy remain
authoritative. Unsupported siblings do not poison otherwise optimizable work:
the planner partitions a batch into shared-scan work and a canonical remainder.
"""

from __future__ import annotations

import hashlib
import heapq
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from tracecite_core.segmenter import build_segmenter, detect_segmenter_kind
from tracecite_core.state_file import state_lock

from .evidence_shell import (
    _budget_data,
    _field_value as _canonical_field_value,
    _payload_fits,
    _predicate as _canonical_predicate,
    _row as _canonical_row,
)
from .evidence_shell_agent import run_evidence_shell
from .evidence_shell_agent_compat import normalize_agent_evidence_shell_program
from .evidence_shell_compat import normalize_evidence_shell_program
from .evidence_shell_fast_jsonl import (
    _PREDICATES,
    _SPECIAL_FIELDS,
    _absolute_time_window,
    _matches,
    _postprocess,
    _record_in_absolute_window,
    _split,
    _tokenize,
    _value,
)
from .evidence_shell_public import EvidenceShellPolicy, EvidenceShellRequest
from .retrieval_session import RetrievalOperation, RetrievalSessionStore
from .schema import AgentResult
from .source_versions import SourceSegment, SourceVersionStore


MAX_BATCH_ANALYSES = 16
_HEAD_COMMANDS = {"head", "take", "first"}


@dataclass(frozen=True)
class EvidenceAnalysisSpec:
    """One caller-selected mechanical analysis in a batch."""

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
    last: str | None = None
    since: str | None = None
    until: str | None = None

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
class _CompiledJsonlAggregate:
    spec: EvidenceAnalysisSpec
    normalized: str
    predicates: list[Any]
    aggregate_stage: Any
    post: list[Any]
    raw_predicates: list[Any]
    field_predicates: list[Any]
    referenced_fields: set[str]
    matched: int = 0
    counts: dict[str, int] | None = None

    def __post_init__(self) -> None:
        if self.counts is None:
            self.counts = {}

    @property
    def needs_record(self) -> bool:
        return bool(self.referenced_fields & _SPECIAL_FIELDS)

    @property
    def needs_json(self) -> bool:
        aggregate_field = (
            str(self.aggregate_stage.args[0])
            if self.aggregate_stage.command != "count" and self.aggregate_stage.args
            else None
        )
        normal_predicate_field = any(
            _predicate_field(stage) not in _SPECIAL_FIELDS
            for stage in self.field_predicates
            if _predicate_field(stage) is not None
        )
        return normal_predicate_field or (
            aggregate_field is not None and aggregate_field not in _SPECIAL_FIELDS
        )


@dataclass
class _CompiledJsonlTopN:
    spec: EvidenceAnalysisSpec
    normalized: str
    predicates: list[Any]
    raw_predicates: list[Any]
    field_predicates: list[Any]
    sort_field: str
    project_fields: tuple[str, ...]
    descending: bool
    numeric: bool
    limit: int
    referenced_fields: set[str]
    candidates: list[tuple[tuple[int, float | str], int, dict[str, Any]]] | None = None
    ordinal: int = 0

    def __post_init__(self) -> None:
        if self.candidates is None:
            self.candidates = []

    @property
    def needs_record(self) -> bool:
        return bool(self.referenced_fields & _SPECIAL_FIELDS)

    @property
    def needs_json(self) -> bool:
        normal_predicate_field = any(
            _predicate_field(stage) not in _SPECIAL_FIELDS
            for stage in self.field_predicates
            if _predicate_field(stage) is not None
        )
        return (
            normal_predicate_field
            or self.sort_field not in _SPECIAL_FIELDS
            or any(field not in _SPECIAL_FIELDS for field in self.project_fields)
        )


_CompiledJsonl = _CompiledJsonlAggregate | _CompiledJsonlTopN


def _predicate_field(stage: Any) -> str | None:
    if stage.command in {"where", "exists", "missing"} and stage.args:
        return str(stage.args[0])
    return None


def _referenced_fields_for(stages: Sequence[Any]) -> set[str]:
    fields: set[str] = set()
    for stage in stages:
        field = _predicate_field(stage)
        if field is not None:
            fields.add(field)
    return fields


def _split_predicates(predicates: Sequence[Any]) -> tuple[list[Any], list[Any]]:
    raw = [
        stage
        for stage in predicates
        if stage.command in {"search", "regex", "exclude", "exclude-regex", "all"}
    ]
    fields = [stage for stage in predicates if stage not in raw]
    return raw, fields


def _normalize_spec(spec: EvidenceAnalysisSpec) -> tuple[str, list[Any]] | None:
    try:
        agent_normalized = normalize_agent_evidence_shell_program(spec.program)
        normalized = normalize_evidence_shell_program(agent_normalized)
        stages = [stage for stage in _tokenize(normalized) if stage.command != "emit"]
    except ValueError:
        return None
    return normalized, stages


def _compile_jsonl_aggregate(
    spec: EvidenceAnalysisSpec,
    normalized: str,
    stages: list[Any],
) -> _CompiledJsonlAggregate | None:
    split = _split(stages)
    if split is None:
        return None
    predicates, aggregate_stage, post = split
    raw_predicates, field_predicates = _split_predicates(predicates)
    referenced = _referenced_fields_for(predicates)
    if aggregate_stage.command != "count" and aggregate_stage.args:
        referenced.add(str(aggregate_stage.args[0]))
    return _CompiledJsonlAggregate(
        spec=spec,
        normalized=normalized,
        predicates=predicates,
        aggregate_stage=aggregate_stage,
        post=post,
        raw_predicates=raw_predicates,
        field_predicates=field_predicates,
        referenced_fields=referenced,
    )


def _compile_jsonl_topn(
    spec: EvidenceAnalysisSpec,
    normalized: str,
    stages: list[Any],
) -> _CompiledJsonlTopN | None:
    if len(stages) < 3:
        return None
    sort_stage, select_stage, project_stage = stages[-3:]
    if (
        sort_stage.command != "sort"
        or select_stage.command not in _HEAD_COMMANDS
        or project_stage.command != "project"
    ):
        return None
    if not sort_stage.args or len(sort_stage.args) > 3:
        return None
    if len(select_stage.args) != 1 or not project_stage.args:
        return None
    try:
        limit = int(select_stage.args[0])
    except ValueError:
        return None
    if limit < 1:
        return None

    sort_field = str(sort_stage.args[0])
    direction = str(sort_stage.args[1]).lower() if len(sort_stage.args) > 1 else "asc"
    numeric = len(sort_stage.args) > 2 and str(sort_stage.args[2]).lower() == "numeric"
    if direction not in {"asc", "desc"}:
        return None
    if len(sort_stage.args) > 2 and not numeric:
        return None

    predicates = stages[:-3]
    if any(stage.command not in _PREDICATES for stage in predicates):
        return None
    raw_predicates, field_predicates = _split_predicates(predicates)
    project_fields = tuple(str(field) for field in project_stage.args)
    referenced = _referenced_fields_for(predicates) | {sort_field} | set(project_fields)
    return _CompiledJsonlTopN(
        spec=spec,
        normalized=normalized,
        predicates=predicates,
        raw_predicates=raw_predicates,
        field_predicates=field_predicates,
        sort_field=sort_field,
        project_fields=project_fields,
        descending=direction == "desc",
        numeric=numeric,
        limit=limit,
        referenced_fields=referenced,
    )


def _compile_jsonl(spec: EvidenceAnalysisSpec) -> _CompiledJsonl | None:
    prepared = _normalize_spec(spec)
    if prepared is None:
        return None
    normalized, stages = prepared
    aggregate = _compile_jsonl_aggregate(spec, normalized, stages)
    if aggregate is not None:
        return aggregate
    return _compile_jsonl_topn(spec, normalized, stages)


def _field_value(
    obj: Mapping[str, Any],
    field: str,
    *,
    canonical_row: Any | None,
) -> Any:
    if field in _SPECIAL_FIELDS:
        if canonical_row is None:
            return None
        return _canonical_field_value(canonical_row, field)
    return _value(obj, field)


def _field_predicate_matches(
    obj: Mapping[str, Any],
    raw: str,
    stage: Any,
    *,
    canonical_row: Any | None,
) -> bool:
    field = _predicate_field(stage)
    if field in _SPECIAL_FIELDS:
        if canonical_row is None:
            return False
        return bool(_canonical_predicate(canonical_row, stage))
    return _matches(obj, raw, stage)


def _topn_sort_key(value: Any, *, numeric: bool) -> tuple[int, float | str]:
    if value is None:
        return (1, 0.0 if numeric else "")
    if numeric:
        try:
            return (0, float(str(value).strip()))
        except ValueError:
            return (1, 0.0)
    return (0, str(value))


def _trim_topn(item: _CompiledJsonlTopN) -> None:
    assert item.candidates is not None
    if len(item.candidates) <= item.limit:
        return
    if item.descending:
        item.candidates = heapq.nlargest(
            item.limit,
            item.candidates,
            key=lambda candidate: (candidate[0], -candidate[1]),
        )
    else:
        item.candidates = heapq.nsmallest(
            item.limit,
            item.candidates,
            key=lambda candidate: (candidate[0], candidate[1]),
        )


def _update_topn(
    item: _CompiledJsonlTopN,
    *,
    obj: Mapping[str, Any],
    canonical_row: Any | None,
    segment: SourceSegment,
    local_start_line: int,
    local_end_line: int,
) -> None:
    sort_value = _field_value(obj, item.sort_field, canonical_row=canonical_row)
    values = {
        field: _field_value(obj, field, canonical_row=canonical_row)
        for field in item.project_fields
    }
    global_start = segment.line_base + max(0, local_start_line - 1)
    global_end = segment.line_base + max(0, local_end_line - 1)
    fragment = f"#L{local_start_line}"
    if local_end_line != local_start_line:
        fragment += f"-L{local_end_line}"
    projected: dict[str, Any] = {
        "uri": f"evidence://sha256/{segment.sha256}{fragment}",
        "source": segment.path,
        "sha256": segment.sha256,
        "start_line": global_start,
        "end_line": global_end,
    }
    if len(item.project_fields) == 1:
        projected["value"] = values[item.project_fields[0]]
    else:
        projected["values"] = values
    item.ordinal += 1
    assert item.candidates is not None
    item.candidates.append(
        (
            _topn_sort_key(sort_value, numeric=item.numeric),
            item.ordinal,
            projected,
        )
    )
    _trim_topn(item)


def _finalize_aggregate(
    compiled: _CompiledJsonlAggregate,
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
        "execution_engine": "jsonl_shared_scan_aggregate",
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
        "execution_engine": "jsonl_shared_scan_aggregate",
    }


def _finalize_topn(
    compiled: _CompiledJsonlTopN,
    *,
    policy: EvidenceShellPolicy,
) -> dict[str, Any]:
    assert compiled.candidates is not None
    if compiled.descending:
        selected = heapq.nlargest(
            compiled.limit,
            compiled.candidates,
            key=lambda candidate: (candidate[0], -candidate[1]),
        )
    else:
        selected = heapq.nsmallest(
            compiled.limit,
            compiled.candidates,
            key=lambda candidate: (candidate[0], candidate[1]),
        )
    rows = [candidate[2] for candidate in selected]
    aggregate: dict[str, Any] = {
        "rows": rows,
        "row_total": len(rows),
    }
    if len(compiled.project_fields) == 1:
        aggregate["field"] = compiled.project_fields[0]
    else:
        aggregate["fields"] = list(compiled.project_fields)
    output = {
        "name": compiled.spec.name,
        "status": "ok",
        "program": compiled.normalized,
        "coverage": {"complete": True, "match_records": len(rows)},
        "aggregate": aggregate,
        "execution_engine": "jsonl_shared_scan_topn_project",
    }
    fits, token_count, byte_count = _payload_fits(output, policy)
    if fits:
        return output
    return {
        "name": compiled.spec.name,
        "status": "too_broad",
        "program": compiled.normalized,
        "coverage": {"complete": True, "match_records": len(rows)},
        "reason": "AGGREGATE_OUTPUT_BUDGET_EXCEEDED",
        "observed_at_least_tokens": token_count,
        "observed_at_least_bytes": byte_count,
        "execution_engine": "jsonl_shared_scan_topn_project",
    }


def _finalize_compiled(
    item: _CompiledJsonl,
    *,
    policy: EvidenceShellPolicy,
) -> dict[str, Any]:
    if isinstance(item, _CompiledJsonlAggregate):
        return _finalize_aggregate(item, policy=policy)
    return _finalize_topn(item, policy=policy)


def _scope_request(request: EvidenceComputeRequest) -> EvidenceShellRequest:
    return EvidenceShellRequest(
        source=request.source,
        program="count",
        segmenter=request.segmenter,
        last=request.last,
        since=request.since,
        until=request.until,
    )


def _fallback_output(
    spec: EvidenceAnalysisSpec,
    *,
    request: EvidenceComputeRequest,
    policy: EvidenceShellPolicy,
    session: RetrievalSessionStore | None,
) -> tuple[dict[str, Any], Mapping[str, Any] | None, str | None]:
    result = run_evidence_shell(
        EvidenceShellRequest(
            source=request.source,
            program=spec.program,
            segmenter=request.segmenter,
            last=request.last,
            since=request.since,
            until=request.until,
        ),
        policy=policy,
        session=session,
    )
    data = result.get("data") if isinstance(result.get("data"), Mapping) else {}
    source_view = data.get("source_view") if isinstance(data.get("source_view"), Mapping) else None
    source_version = str(data.get("source_version")) if data.get("source_version") is not None else None
    status = str(result.get("status") or "error")
    output: dict[str, Any] = {
        "name": spec.name,
        "status": status,
        "program": str(data.get("normalized_program") or data.get("program") or spec.program),
        "coverage": dict(result.get("coverage") or {}),
        "execution_engine": str(data.get("execution_engine") or "canonical_analysis_fallback"),
    }
    aggregate = data.get("aggregate")
    if status == "ok" and isinstance(aggregate, Mapping):
        output["aggregate"] = dict(aggregate)
    elif status == "ok":
        output["status"] = "error"
        output["error_code"] = "analysis_requires_bounded_aggregate"
        output["error"] = (
            "batch evidence compute accepts bounded aggregate/project programs only; "
            "use tracecite_run for raw Evidence selection"
        )
    else:
        for key in ("error_code", "error", "guidance"):
            if result.get(key) is not None:
                output[key] = result.get(key)
        if data.get("reason") is not None:
            output["reason"] = data.get("reason")
    return output, source_view, source_version


def _try_partitioned_jsonl(
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

    compiled: list[_CompiledJsonl] = []
    fallback_specs: list[EvidenceAnalysisSpec] = []
    for spec in request.analyses:
        item = _compile_jsonl(spec)
        if item is None:
            fallback_specs.append(spec)
        else:
            compiled.append(item)
    if not compiled:
        return None

    selected_segmenter = build_segmenter(kind)
    scope = _scope_request(request)
    time_window = _absolute_time_window(scope, segmenter=selected_segmenter)
    scope_requested = any(value is not None for value in (request.last, request.since, request.until))
    if scope_requested and time_window is None:
        # Reference-relative clock scopes / last still use the canonical engine
        # until the planner can prove an equivalent shared physical plan.
        return None
    assert time_window is not None
    time_from, time_to = time_window
    time_scoped = time_from is not None or time_to is not None

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

    needs_record = time_scoped or any(item.needs_record for item in compiled)
    for segment in view.segments:
        segment_path = Path(segment.path)
        if needs_record:
            records = selected_segmenter.segment_file(segment_path, encoding="utf-8")
            iterator = (
                (
                    record.text,
                    record.start_line,
                    record.end_line,
                    record,
                    _canonical_row(record, segment),
                )
                for record in records
            )
        else:
            def raw_rows():
                with segment_path.open("r", encoding="utf-8", errors="replace") as handle:
                    for line_number, raw in enumerate(handle, start=1):
                        yield raw, line_number, line_number, None, None
            iterator = raw_rows()

        for raw, local_start, local_end, record, canonical_row in iterator:
            if not raw.strip():
                continue
            if time_scoped:
                assert record is not None
                if not _record_in_absolute_window(
                    record,
                    segmenter=selected_segmenter,
                    time_from=time_from,
                    time_to=time_to,
                ):
                    continue

            raw_pass: list[_CompiledJsonl] = []
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
                if any(
                    not _field_predicate_matches(
                        obj,
                        raw,
                        stage,
                        canonical_row=canonical_row,
                    )
                    for stage in item.field_predicates
                ):
                    continue
                if isinstance(item, _CompiledJsonlAggregate):
                    item.matched += 1
                    if item.aggregate_stage.command != "count":
                        field = str(item.aggregate_stage.args[0])
                        value = _field_value(obj, field, canonical_row=canonical_row)
                        key = "<missing>" if value is None else str(value)
                        assert item.counts is not None
                        item.counts[key] = item.counts.get(key, 0) + 1
                else:
                    _update_topn(
                        item,
                        obj=obj,
                        canonical_row=canonical_row,
                        segment=segment,
                        local_start_line=int(local_start),
                        local_end_line=int(local_end),
                    )

    output_by_name = {
        item.spec.name: _finalize_compiled(item, policy=policy)
        for item in compiled
    }
    fallback_view: Mapping[str, Any] | None = None
    fallback_version: str | None = None
    for spec in fallback_specs:
        output, candidate_view, candidate_version = _fallback_output(
            spec,
            request=request,
            policy=policy,
            session=session,
        )
        output_by_name[spec.name] = output
        if fallback_view is None and candidate_view is not None:
            fallback_view = candidate_view
        if fallback_version is None and candidate_version is not None:
            fallback_version = candidate_version

    outputs = [output_by_name[spec.name] for spec in request.analyses]
    engine = "jsonl_shared_scan_batch" if not fallback_specs else "jsonl_partitioned_batch"
    source_view = view.to_dict() if compiled else dict(fallback_view or {})
    source_version = view.key if compiled else fallback_version
    result_data = {
        "outputs": outputs,
        "analysis_count": len(outputs),
        "source_view": source_view,
        "source_version": source_version,
        "evidence_budget": _budget_data(policy),
        "execution_engine": engine,
        "shared_scan_analyses": len(compiled),
        "canonical_remainder_analyses": len(fallback_specs),
        "time_scope": {
            "last": request.last,
            "since": request.since,
            "until": request.until,
        },
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
                "source_view": source_view,
                "source_version": source_version,
                "evidence_budget": _budget_data(policy),
                "execution_engine": engine,
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
        output, candidate_view, candidate_version = _fallback_output(
            spec,
            request=request,
            policy=policy,
            session=session,
        )
        outputs.append(output)
        if source_view is None and candidate_view is not None:
            source_view = candidate_view
        if source_version is None and candidate_version is not None:
            source_version = candidate_version

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
            "time_scope": {
                "last": request.last,
                "since": request.since,
                "until": request.until,
            },
        },
    ).to_dict()


def _compute_request_fingerprint(
    request: EvidenceComputeRequest,
    *,
    source_version: str,
    payload: Mapping[str, Any],
) -> str:
    data = payload.get("data") if isinstance(payload.get("data"), Mapping) else {}
    normalized_by_name = {
        str(item.get("name") or ""): str(item.get("program") or "")
        for item in data.get("outputs") or ()
        if isinstance(item, Mapping)
    }
    analyses = [
        {
            "name": spec.name,
            "program": normalized_by_name.get(spec.name) or spec.program,
        }
        for spec in request.analyses
    ]
    encoded = json.dumps(
        {
            "operation": "evidence_compute",
            "source_version": source_version,
            "segmenter": request.segmenter,
            "last": request.last,
            "since": request.since,
            "until": request.until,
            "analyses": analyses,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _record_compute_session(
    payload: dict[str, Any],
    *,
    request: EvidenceComputeRequest,
    session: RetrievalSessionStore | None,
) -> dict[str, Any]:
    """Record one batch as one mechanical session operation, never N Agent rounds."""

    if session is None or payload.get("status") == "too_broad":
        return payload
    data = payload.get("data") if isinstance(payload.get("data"), Mapping) else {}
    source_version = str(data.get("source_version") or "").strip()
    if not source_version:
        return payload

    operation = RetrievalOperation(
        operation="evidence_compute",
        status=str(payload.get("status") or "unknown"),
        request_fingerprint=_compute_request_fingerprint(
            request,
            source_version=source_version,
            payload=payload,
        ),
        source_version=source_version,
    )
    with state_lock(session.path):
        state = session.load()
        next_state, _ = state.advance(operation=operation)
        session.save(next_state)
    return payload


def run_evidence_compute(
    request: EvidenceComputeRequest,
    *,
    policy: EvidenceShellPolicy,
    session: RetrievalSessionStore | None = None,
) -> dict[str, Any]:
    """Run caller-selected bounded analyses behind one tool boundary."""

    if not isinstance(request, EvidenceComputeRequest):
        raise TypeError("run_evidence_compute requires EvidenceComputeRequest")
    if not isinstance(policy, EvidenceShellPolicy):
        raise TypeError("policy must be EvidenceShellPolicy")

    payload = _try_partitioned_jsonl(request, policy=policy, session=session)
    if payload is None:
        payload = _fallback_sequential(request, policy=policy, session=session)
    return _record_compute_session(payload, request=request, session=session)


__all__ = [
    "MAX_BATCH_ANALYSES",
    "EvidenceAnalysisSpec",
    "EvidenceComputeRequest",
    "run_evidence_compute",
]
