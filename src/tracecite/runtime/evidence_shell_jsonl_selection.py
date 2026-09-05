"""Streaming JSONL physical plan for bounded raw or projected Evidence selection.

The plan covers caller-selected predicate + head/top-K programs without routing
JSONL through JsonLineSegmenter -> Record construction. It reuses the same
SourceVersion, JSONL semantic extraction, Evidence budget and RetrievalSession
projection as canonical Evidence Shell. Projection is deliberately applied only
after bounded selection so wide source rows and semantic aliases are not
materialized for candidates that will be discarded.
"""

from __future__ import annotations

from dataclasses import dataclass
from json import JSONDecodeError, loads as json_loads
from pathlib import Path
from typing import Any, Mapping

from tracecite_core.jsonline_semantics import JsonLineSemantics, extract_jsonline_semantics
from tracecite_core.segmenter import JsonLineSegmenter, build_segmenter, detect_segmenter_kind

from .evidence_shell import (
    _RecordRow,
    _aggregate,
    _budget_data,
    _payload_fits,
    _too_broad,
)
from .evidence_shell_agent_compat import normalize_agent_evidence_shell_program
from .evidence_shell_compat import normalize_evidence_shell_program
from .evidence_shell_fast_jsonl import _PREDICATES, _SPECIAL_FIELDS, _absolute_time_window, _matches, _tokenize
from .evidence_shell_fast_topn import _evidence_payload
from .evidence_shell_public import EvidenceShellPolicy, EvidenceShellRequest
from .jsonl_physical import (
    FixedCapacityTopK,
    RAW_FALLBACK_FIELDS,
    SEMANTIC_JSON_FIELDS,
    field_predicate_matches,
    field_value,
    referenced_fields,
    split_predicates,
    topk_sort_key,
)
from .retrieval_session import RetrievalSessionStore
from .schema import AgentResult
from .source_versions import SourceSegment, SourceVersionStore


_HEAD_COMMANDS = {"head", "take", "first"}


@dataclass(frozen=True)
class _SelectionPlan:
    normalized: str
    raw_predicates: tuple[Any, ...]
    field_predicates: tuple[Any, ...]
    limit: int
    sort_field: str | None
    descending: bool
    numeric: bool
    scan_fields: frozenset[str]
    project_fields: tuple[str, ...]

    @property
    def needs_semantics_for_scan(self) -> bool:
        return bool(self.scan_fields & SEMANTIC_JSON_FIELDS)

    @property
    def needs_semantics_for_output(self) -> bool:
        if not self.project_fields:
            # Raw EvidencePointer projection includes canonical timestamp.
            return True
        return bool(set(self.project_fields) & SEMANTIC_JSON_FIELDS)


def _compile(program: str) -> _SelectionPlan | None:
    try:
        agent_normalized = normalize_agent_evidence_shell_program(program)
        normalized = normalize_evidence_shell_program(agent_normalized)
        stages = [stage for stage in _tokenize(normalized) if stage.command != "emit"]
    except ValueError:
        return None
    if not stages:
        return None

    material = list(stages)
    project_fields: tuple[str, ...] = ()
    if material and material[-1].command == "project":
        project_stage = material.pop()
        if not project_stage.args:
            return None
        project_fields = tuple(str(field) for field in project_stage.args)

    if not material:
        return None
    select_stage = material[-1]
    if select_stage.command not in _HEAD_COMMANDS or len(select_stage.args) != 1:
        return None
    try:
        limit = int(select_stage.args[0])
    except ValueError:
        return None
    if limit < 1:
        return None

    prefix = list(material[:-1])
    sort_field: str | None = None
    descending = False
    numeric = False
    if prefix and prefix[-1].command == "sort":
        sort_stage = prefix.pop()
        if not sort_stage.args or len(sort_stage.args) > 3:
            return None
        sort_field = str(sort_stage.args[0])
        direction = str(sort_stage.args[1]).lower() if len(sort_stage.args) > 1 else "asc"
        numeric = len(sort_stage.args) > 2 and str(sort_stage.args[2]).lower() == "numeric"
        if direction not in {"asc", "desc"}:
            return None
        if len(sort_stage.args) > 2 and not numeric:
            return None
        descending = direction == "desc"

    if any(stage.command not in _PREDICATES for stage in prefix):
        return None
    raw_predicates, field_predicates = split_predicates(prefix)
    scan_fields = referenced_fields(prefix)
    if sort_field is not None:
        scan_fields.add(sort_field)
    all_fields = scan_fields | set(project_fields)
    # JsonLineSegmenter synthesizes these only for malformed/non-object JSON.
    # Until the shared resolver models those fallback fields, keep canonical
    # execution authoritative for programs that explicitly ask for them.
    if all_fields & RAW_FALLBACK_FIELDS:
        return None
    return _SelectionPlan(
        normalized=normalized,
        raw_predicates=tuple(raw_predicates),
        field_predicates=tuple(field_predicates),
        limit=limit,
        sort_field=sort_field,
        descending=descending,
        numeric=numeric,
        scan_fields=frozenset(scan_fields),
        project_fields=project_fields,
    )


def _decode(raw: str) -> Mapping[str, Any]:
    try:
        value = json_loads(raw)
    except JSONDecodeError:
        return {}
    return value if isinstance(value, Mapping) else {}


def _semantics(
    obj: Mapping[str, Any],
    *,
    segmenter: JsonLineSegmenter,
) -> JsonLineSemantics:
    return extract_jsonline_semantics(
        obj,
        time_field=segmenter._time_field,
        level_field=segmenter._level_field,
        msg_field=segmenter._msg_field,
    )


def _row(
    raw: str,
    *,
    semantics: JsonLineSemantics | None,
    segment: SourceSegment,
    line_number: int,
) -> _RecordRow:
    timestamp = None
    fields: dict[str, Any] = {}
    if semantics is not None:
        fields.update(semantics.fields)
        if semantics.timestamp is not None:
            timestamp = semantics.timestamp.isoformat(timespec="milliseconds")
    return _RecordRow(
        text=raw if raw.endswith("\n") else raw + "\n",
        metadata={
            "start_line": line_number,
            "end_line": line_number,
            "timestamp": timestamp,
            "fields": fields,
        },
        source_path=segment.path,
        sha256=segment.sha256,
        line_base=segment.line_base,
    )


@dataclass(frozen=True)
class _Candidate:
    raw: str
    obj: Mapping[str, Any]
    semantics: JsonLineSemantics | None
    segment: SourceSegment
    line_number: int


def _candidate_row(
    candidate: _Candidate,
    *,
    segmenter: JsonLineSegmenter,
    require_semantics: bool,
) -> _RecordRow:
    semantics = candidate.semantics
    if require_semantics and semantics is None:
        semantics = _semantics(candidate.obj, segmenter=segmenter)
    return _row(
        candidate.raw,
        semantics=semantics,
        segment=candidate.segment,
        line_number=candidate.line_number,
    )


def _projected_payload(
    *,
    request: EvidenceShellRequest,
    policy: EvidenceShellPolicy,
    view: Any,
    kind: Any,
    rows: list[_RecordRow],
    project_fields: tuple[str, ...],
    physical_plan: Mapping[str, Any],
) -> dict[str, Any]:
    # Reuse the canonical project implementation after bounded selection. This
    # keeps the public aggregate shape and special-field semantics identical.
    project_stage = type("ProjectStage", (), {"command": "project", "args": project_fields})()
    aggregate, matched = _aggregate(rows, project_stage)
    aggregate_payload = {"aggregate": aggregate, "match_records": matched}
    fits, token_count, byte_count = _payload_fits(aggregate_payload, policy)
    if not fits:
        return _too_broad(
            request=request,
            policy=policy,
            view=view,
            reason="AGGREGATE_OUTPUT_BUDGET_EXCEEDED",
            tokens=token_count,
            bytes_used=byte_count,
        )
    return AgentResult(
        operation="evidence_shell",
        status="ok",
        outcome="not_assessed",
        coverage={"complete": True, "match_records": matched},
        data={
            "program": request.program,
            "segmenter": str(kind),
            "aggregate": aggregate,
            "source_view": view.to_dict(),
            "source_version": view.key,
            "evidence_budget": _budget_data(policy),
            "execution_engine": "bounded_terminal_topn",
            "physical_plan": dict(physical_plan),
        },
    ).to_dict()


def try_run_jsonl_selection(
    request: EvidenceShellRequest,
    *,
    policy: EvidenceShellPolicy,
    session: RetrievalSessionStore | None = None,
) -> dict[str, Any] | None:
    """Execute a bounded JSONL predicate/head or predicate/sort/head plan."""

    if request.fold:
        return None
    plan = _compile(request.program)
    if plan is None:
        return None
    source = Path(request.source).expanduser().resolve()
    if not source.is_file():
        return None
    kind = detect_segmenter_kind(source) if request.segmenter == "auto" else request.segmenter
    if not isinstance(kind, str) or kind.strip().lower() not in {"jsonline", "json", "jsonl"}:
        return None
    selected_segmenter = build_segmenter(kind)
    if not isinstance(selected_segmenter, JsonLineSegmenter):
        return None

    scoped = EvidenceShellRequest(
        source=request.source,
        program=plan.normalized,
        segmenter=request.segmenter,
        last=request.last,
        since=request.since,
        until=request.until,
        fold=request.fold,
    )
    time_window = _absolute_time_window(scoped, segmenter=selected_segmenter)
    scope_requested = any(value is not None for value in (request.last, request.since, request.until))
    if scope_requested and time_window is None:
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

    head_candidates: list[_Candidate] = []
    topk = (
        FixedCapacityTopK(plan.limit, descending=plan.descending)
        if plan.sort_field is not None
        else None
    )
    done = False
    for segment in view.segments:
        with Path(segment.path).open("r", encoding="utf-8", errors="replace") as handle:
            for line_number, raw in enumerate(handle, start=1):
                if not raw.strip():
                    continue
                if any(not _matches({}, raw, stage) for stage in plan.raw_predicates):
                    continue

                obj = _decode(raw)
                semantics: JsonLineSemantics | None = None
                needs_semantics = time_scoped or plan.needs_semantics_for_scan
                if needs_semantics:
                    semantics = _semantics(obj, segmenter=selected_segmenter)

                if time_scoped and semantics is not None and semantics.timestamp is not None:
                    if time_from is not None and semantics.timestamp < time_from:
                        continue
                    if time_to is not None and semantics.timestamp > time_to:
                        continue

                if any(
                    not field_predicate_matches(
                        obj,
                        raw,
                        stage,
                        semantics=semantics,
                        segment=segment,
                        local_start_line=line_number,
                        local_end_line=line_number,
                    )
                    for stage in plan.field_predicates
                ):
                    continue

                candidate = _Candidate(
                    raw=raw,
                    obj=obj,
                    semantics=semantics,
                    segment=segment,
                    line_number=line_number,
                )
                if topk is None:
                    head_candidates.append(candidate)
                    if len(head_candidates) >= plan.limit:
                        done = True
                        break
                else:
                    assert plan.sort_field is not None
                    value = field_value(
                        obj,
                        raw,
                        plan.sort_field,
                        semantics=semantics,
                        segment=segment,
                        local_start_line=line_number,
                        local_end_line=line_number,
                    )
                    topk.add(topk_sort_key(value, numeric=plan.numeric), candidate)
        if done:
            break

    selected_candidates = head_candidates if topk is None else topk.values()
    rows = [
        _candidate_row(
            candidate,
            segmenter=selected_segmenter,
            require_semantics=plan.needs_semantics_for_output,
        )
        for candidate in selected_candidates
    ]
    physical_plan = {
        "source_scan": "jsonl_raw_lines",
        "json_decode": "once_per_predicate_candidate",
        "semantic_enrichment": "lazy_from_decoded_json",
        "selection": "early_stop_head" if topk is None else "fixed_capacity_topk",
        "projection": "post_selection" if plan.project_fields else "evidence_pointer",
    }

    if plan.project_fields:
        return _projected_payload(
            request=scoped,
            policy=policy,
            view=view,
            kind=kind,
            rows=rows,
            project_fields=plan.project_fields,
            physical_plan=physical_plan,
        )

    payload = _evidence_payload(
        request=scoped,
        policy=policy,
        session=session,
        view=view,
        kind=kind,
        selected=rows,
    )
    data = dict(payload.get("data") or {})
    # Keep the pre-existing agent-visible engine label for sorted Top-N so this
    # physical optimization is transport-compatible. The richer physical_plan
    # below is the authoritative way to identify the implementation.
    data["execution_engine"] = (
        "jsonl_streaming_bounded_head" if topk is None else "bounded_terminal_topn"
    )
    data["physical_plan"] = physical_plan
    payload["data"] = data
    return payload


__all__ = ["try_run_jsonl_selection"]
