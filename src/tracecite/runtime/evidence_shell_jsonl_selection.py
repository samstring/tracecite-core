"""Streaming JSONL physical plan for bounded raw Evidence selection.

The plan covers caller-selected predicate + head/top-K programs without routing
JSONL through JsonLineSegmenter -> Record construction.  It reuses the same
SourceVersion, JSONL semantic extraction, Evidence budget and RetrievalSession
projection as canonical Evidence Shell.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from tracecite_core.jsonline_semantics import JsonLineSemantics, extract_jsonline_semantics
from tracecite_core.segmenter import JsonLineSegmenter, build_segmenter, detect_segmenter_kind

from .evidence_shell import _RecordRow
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
    referenced_fields: frozenset[str]

    @property
    def needs_semantics_for_match(self) -> bool:
        return bool(self.referenced_fields & SEMANTIC_JSON_FIELDS)



def _compile(program: str) -> _SelectionPlan | None:
    try:
        agent_normalized = normalize_agent_evidence_shell_program(program)
        normalized = normalize_evidence_shell_program(agent_normalized)
        stages = [stage for stage in _tokenize(normalized) if stage.command != "emit"]
    except ValueError:
        return None
    if not stages:
        return None
    select_stage = stages[-1]
    if select_stage.command not in _HEAD_COMMANDS or len(select_stage.args) != 1:
        return None
    try:
        limit = int(select_stage.args[0])
    except ValueError:
        return None
    if limit < 1:
        return None

    prefix = list(stages[:-1])
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
    fields = referenced_fields(prefix)
    if sort_field is not None:
        fields.add(sort_field)
    # JsonLineSegmenter synthesizes these only for malformed/non-object JSON.
    # Until the shared resolver models those fallback fields, keep canonical
    # execution authoritative for programs that explicitly ask for them.
    if fields & RAW_FALLBACK_FIELDS:
        return None
    return _SelectionPlan(
        normalized=normalized,
        raw_predicates=tuple(raw_predicates),
        field_predicates=tuple(field_predicates),
        limit=limit,
        sort_field=sort_field,
        descending=descending,
        numeric=numeric,
        referenced_fields=frozenset(fields),
    )


def _decode(raw: str) -> Mapping[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, Mapping) else {}


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

    head_rows: list[_RecordRow] = []
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
                needs_semantics = time_scoped or plan.needs_semantics_for_match
                if plan.sort_field in _SPECIAL_FIELDS:
                    needs_semantics = needs_semantics or plan.sort_field in SEMANTIC_JSON_FIELDS
                if needs_semantics:
                    semantics = extract_jsonline_semantics(
                        obj,
                        time_field=selected_segmenter._time_field,
                        level_field=selected_segmenter._level_field,
                        msg_field=selected_segmenter._msg_field,
                    )

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

                # EvidencePointer timestamp/semantic aliases must match the
                # canonical JsonLineSegmenter even when no predicate needed it.
                if semantics is None:
                    semantics = extract_jsonline_semantics(
                        obj,
                        time_field=selected_segmenter._time_field,
                        level_field=selected_segmenter._level_field,
                        msg_field=selected_segmenter._msg_field,
                    )
                row = _row(raw, semantics=semantics, segment=segment, line_number=line_number)
                if topk is None:
                    head_rows.append(row)
                    if len(head_rows) >= plan.limit:
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
                    topk.add(topk_sort_key(value, numeric=plan.numeric), row)
        if done:
            break

    selected = head_rows if topk is None else topk.values()
    payload = _evidence_payload(
        request=scoped,
        policy=policy,
        session=session,
        view=view,
        kind=kind,
        selected=selected,
    )
    data = dict(payload.get("data") or {})
    data["execution_engine"] = (
        "jsonl_streaming_bounded_head" if topk is None else "jsonl_streaming_fixed_topk"
    )
    data["physical_plan"] = {
        "source_scan": "jsonl_raw_lines",
        "json_decode": "once_per_predicate_candidate",
        "semantic_enrichment": "lazy_from_decoded_json",
        "selection": "early_stop_head" if topk is None else "fixed_capacity_topk",
    }
    payload["data"] = data
    return payload


__all__ = ["try_run_jsonl_selection"]
