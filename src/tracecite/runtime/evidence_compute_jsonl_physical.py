"""Shared JSONL physical execution for compatible Evidence Compute batches.

This module is intentionally mechanical. It reuses the existing Evidence
Compute compiler and output contract, but executes compatible aggregate + Top-K
analyses in one raw JSONL scan. Repeated sibling predicates are evaluated once
per line, Top-K state has fixed capacity, and projection is deferred until after
selection so discarded candidates stay cheap.

Unsupported siblings are partitioned into the established canonical remainder
instead of poisoning compatible work. Request-level time scopes are also
observable: a JSONL source with zero parseable canonical timestamps cannot
silently return unscoped aggregates as though the scope had been applied.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from tracecite_core.jsonline_semantics import JsonLineSemantics, extract_jsonline_semantics
from tracecite_core.segmenter import JsonLineSegmenter, build_segmenter, detect_segmenter_kind

from . import evidence_compute as legacy
from .evidence_shell import _budget_data, _payload_fits
from .evidence_shell_public import EvidenceShellPolicy
from .jsonl_physical import FixedCapacityTopK, JsonlLineContext, topk_sort_key
from .retrieval_session import RetrievalSessionStore
from .schema import AgentResult
from .source_versions import SourceVersionStore


def _project_selected(item: Any, context: JsonlLineContext) -> dict[str, Any]:
    values = {field: context.value(field) for field in item.project_fields}
    segment = context.segment
    line_number = context.line_number
    global_line = segment.line_base + max(0, line_number - 1)
    projected: dict[str, Any] = {
        "uri": f"evidence://sha256/{segment.sha256}#L{line_number}",
        "source": segment.path,
        "sha256": segment.sha256,
        "start_line": global_line,
        "end_line": global_line,
    }
    if len(item.project_fields) == 1:
        projected["value"] = values[item.project_fields[0]]
    else:
        projected["values"] = values
    return projected


def _finalize_topn(
    item: Any,
    accumulator: FixedCapacityTopK,
    *,
    policy: EvidenceShellPolicy,
) -> dict[str, Any]:
    rows = [_project_selected(item, context) for context in accumulator.values()]
    aggregate: dict[str, Any] = {"rows": rows, "row_total": len(rows)}
    if len(item.project_fields) == 1:
        aggregate["field"] = item.project_fields[0]
    else:
        aggregate["fields"] = list(item.project_fields)
    output = {
        "name": item.spec.name,
        "status": "ok",
        "program": item.normalized,
        "coverage": {"complete": True, "match_records": len(rows)},
        "aggregate": aggregate,
        "execution_engine": "jsonl_shared_scan_topn_project",
    }
    fits, token_count, byte_count = _payload_fits(output, policy)
    if fits:
        return output
    return {
        "name": item.spec.name,
        "status": "too_broad",
        "program": item.normalized,
        "coverage": {"complete": True, "match_records": len(rows)},
        "reason": "AGGREGATE_OUTPUT_BUDGET_EXCEEDED",
        "observed_at_least_tokens": token_count,
        "observed_at_least_bytes": byte_count,
        "execution_engine": "jsonl_shared_scan_topn_project",
    }


def _time_scope_unresolved_output(spec: legacy.EvidenceAnalysisSpec) -> dict[str, Any]:
    prepared = legacy._normalize_spec(spec)
    normalized = prepared[0] if prepared is not None else spec.program
    return {
        "name": spec.name,
        "status": "error",
        "program": normalized,
        "coverage": {"complete": False, "match_records": 0},
        "execution_engine": "jsonl_time_scope_unresolved",
        "error_code": "time_scope_unresolved",
        "error": (
            "request-level time scope could not be applied because the source "
            "exposed no parseable canonical record timestamp"
        ),
        "guidance": (
            "Use explicit predicates on the source's own time field, or select a "
            "segmenter configuration that maps that field to the canonical timestamp."
        ),
    }


def try_run_jsonl_batch(
    request: legacy.EvidenceComputeRequest,
    *,
    policy: EvidenceShellPolicy,
    session: RetrievalSessionStore | None,
) -> dict[str, Any] | None:
    """Return a partitioned shared JSONL batch, or ``None`` for full fallback."""

    source = Path(request.source).expanduser().resolve()
    if not source.is_file():
        return None
    kind = detect_segmenter_kind(source) if request.segmenter == "auto" else request.segmenter
    if not isinstance(kind, str) or kind.strip().lower() not in {"jsonline", "json", "jsonl"}:
        return None

    compiled: list[Any] = []
    fallback_specs: list[legacy.EvidenceAnalysisSpec] = []
    for spec in request.analyses:
        item = legacy._compile_jsonl(spec)
        if item is None:
            fallback_specs.append(spec)
        else:
            compiled.append(item)
    if not compiled:
        return None
    topn_items = [item for item in compiled if isinstance(item, legacy._CompiledJsonlTopN)]

    selected_segmenter = build_segmenter(kind)
    if not isinstance(selected_segmenter, JsonLineSegmenter):
        return None
    scope = legacy._scope_request(request)
    time_window = legacy._absolute_time_window(scope, segmenter=selected_segmenter)
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

    accumulators = {
        id(item): FixedCapacityTopK(item.limit, descending=item.descending)
        for item in topn_items
    }
    parseable_timestamp_records = 0
    untimestamped_records = 0

    for segment in view.segments:
        with Path(segment.path).open("r", encoding="utf-8", errors="replace") as handle:
            for line_number, raw in enumerate(handle, start=1):
                if not raw.strip():
                    continue

                obj: Mapping[str, Any] = {}
                semantics: JsonLineSemantics | None = None

                # A request-level scope is logically before the analysis
                # predicates. Decode every nonblank record so scope resolution is
                # auditable even when a later raw predicate matches nothing.
                if time_scoped:
                    try:
                        decoded = legacy.json.loads(raw)
                        obj = decoded if isinstance(decoded, Mapping) else {}
                    except legacy.json.JSONDecodeError:
                        obj = {}
                    semantics = extract_jsonline_semantics(
                        obj,
                        time_field=selected_segmenter._time_field,
                        level_field=selected_segmenter._level_field,
                        msg_field=selected_segmenter._msg_field,
                    )
                    if semantics.timestamp is None:
                        # Preserve canonical semantics: untimestamped records are
                        # retained when a source has a usable timestamp domain.
                        untimestamped_records += 1
                    else:
                        parseable_timestamp_records += 1
                        if time_from is not None and semantics.timestamp < time_from:
                            continue
                        if time_to is not None and semantics.timestamp > time_to:
                            continue

                raw_pass: list[Any] = []
                needs_json = False
                needs_semantics = False
                raw_cache: dict[tuple[str, tuple[str, ...]], bool] = {}
                for item in compiled:
                    passed = True
                    for stage in item.raw_predicates:
                        stage_key = (str(stage.command), tuple(str(value) for value in stage.args))
                        if stage_key not in raw_cache:
                            raw_cache[stage_key] = legacy._matches({}, raw, stage)
                        if not raw_cache[stage_key]:
                            passed = False
                            break
                    if not passed:
                        continue
                    raw_pass.append(item)
                    needs_json = needs_json or item.needs_json
                    needs_semantics = needs_semantics or item.needs_semantic_json
                if not raw_pass:
                    continue

                if not time_scoped and needs_json:
                    try:
                        decoded = legacy.json.loads(raw)
                        obj = decoded if isinstance(decoded, Mapping) else {}
                    except legacy.json.JSONDecodeError:
                        obj = {}
                if not time_scoped and needs_semantics:
                    semantics = extract_jsonline_semantics(
                        obj,
                        time_field=selected_segmenter._time_field,
                        level_field=selected_segmenter._level_field,
                        msg_field=selected_segmenter._msg_field,
                    )

                context = JsonlLineContext(
                    obj=obj,
                    raw=raw,
                    semantics=semantics,
                    segment=segment,
                    line_number=line_number,
                )
                for item in raw_pass:
                    if any(not context.predicate_matches(stage) for stage in item.field_predicates):
                        continue

                    if isinstance(item, legacy._CompiledJsonlAggregate):
                        item.matched += 1
                        if item.aggregate_stage.command != "count":
                            field_name = str(item.aggregate_stage.args[0])
                            value = context.value(field_name)
                            key = "<missing>" if value is None else str(value)
                            assert item.counts is not None
                            item.counts[key] = item.counts.get(key, 0) + 1
                    else:
                        sort_value = context.value(item.sort_field)
                        accumulators[id(item)].add(
                            topk_sort_key(sort_value, numeric=item.numeric),
                            context,
                        )

    source_view = view.to_dict()
    source_version = view.key
    time_scope_resolution: dict[str, Any] | None = None
    if time_scoped:
        time_scope_resolution = {
            "status": "applied" if parseable_timestamp_records else "unresolved",
            "parseable_timestamp_records": parseable_timestamp_records,
            "untimestamped_records": untimestamped_records,
            "retained_untimestamped_records": untimestamped_records,
        }
        if parseable_timestamp_records == 0:
            outputs = [_time_scope_unresolved_output(spec) for spec in request.analyses]
            return AgentResult(
                operation="evidence_compute",
                status="partial",
                outcome="not_assessed",
                coverage={"complete": False},
                data={
                    "outputs": outputs,
                    "analysis_count": len(outputs),
                    "source_view": source_view,
                    "source_version": source_version,
                    "evidence_budget": _budget_data(policy),
                    "execution_engine": "jsonl_time_scope_unresolved",
                    "shared_scan_analyses": len(compiled),
                    "canonical_remainder_analyses": len(fallback_specs),
                    "time_scope": {
                        "last": request.last,
                        "since": request.since,
                        "until": request.until,
                    },
                    "time_scope_resolution": time_scope_resolution,
                },
            ).to_dict()

    output_by_name: dict[str, dict[str, Any]] = {}
    for item in compiled:
        if isinstance(item, legacy._CompiledJsonlAggregate):
            output_by_name[item.spec.name] = legacy._finalize_aggregate(item, policy=policy)
        else:
            output_by_name[item.spec.name] = _finalize_topn(
                item,
                accumulators[id(item)],
                policy=policy,
            )

    fallback_view: Mapping[str, Any] | None = None
    fallback_version: str | None = None
    for spec in fallback_specs:
        output, candidate_view, candidate_version = legacy._fallback_output(
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
    fits, token_count, byte_count = _payload_fits({"outputs": outputs}, policy)
    if not fits:
        return AgentResult(
            operation="evidence_compute",
            status="too_broad",
            outcome="unknown",
            coverage={"complete": False},
            data={
                "reason": "BATCH_OUTPUT_BUDGET_EXCEEDED",
                "analysis_count": len(outputs),
                "observed_at_least_tokens": token_count,
                "observed_at_least_bytes": byte_count,
                "source_view": source_view or dict(fallback_view or {}),
                "source_version": source_version or fallback_version,
                "evidence_budget": _budget_data(policy),
                "execution_engine": (
                    "jsonl_shared_scan_batch" if not fallback_specs else "jsonl_partitioned_batch"
                ),
                "time_scope_resolution": time_scope_resolution,
            },
        ).to_dict()

    statuses = {str(item.get("status") or "") for item in outputs}
    engine = "jsonl_shared_scan_batch" if not fallback_specs else "jsonl_partitioned_batch"
    data: dict[str, Any] = {
        "outputs": outputs,
        "analysis_count": len(outputs),
        "source_view": source_view,
        "source_version": source_version,
        "evidence_budget": _budget_data(policy),
        "execution_engine": engine,
        "shared_scan_analyses": len(compiled),
        "canonical_remainder_analyses": len(fallback_specs),
        "physical_plan": {
            "source_scan": "jsonl_raw_lines",
            "json_decode": "shared_once_per_candidate_line",
            "predicate_evaluation": "memoized_once_per_unique_stage_per_line",
            "topk_projection": "post_selection" if topn_items else "none",
            "semantic_enrichment": "lazy_from_decoded_json",
        },
        "time_scope": {
            "last": request.last,
            "since": request.since,
            "until": request.until,
        },
    }
    if time_scope_resolution is not None:
        data["time_scope_resolution"] = time_scope_resolution
    return AgentResult(
        operation="evidence_compute",
        status="ok" if statuses == {"ok"} else "partial",
        outcome="not_assessed",
        coverage={"complete": all(item.get("status") == "ok" for item in outputs)},
        data=data,
    ).to_dict()


try_run_fixed_topk_jsonl_batch = try_run_jsonl_batch


__all__ = ["try_run_fixed_topk_jsonl_batch", "try_run_jsonl_batch"]
