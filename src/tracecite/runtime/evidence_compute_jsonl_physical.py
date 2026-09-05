"""Shared JSONL physical execution for Evidence Compute batches with Top-K work.

This module is intentionally mechanical.  It reuses the existing Evidence
Compute compiler and output contract, but executes compatible aggregate + Top-K
analyses in one raw JSONL scan with a true fixed-capacity Top-K accumulator.
Unsupported programs fall back to the established planner.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from tracecite_core.jsonline_semantics import JsonLineSemantics, extract_jsonline_semantics
from tracecite_core.segmenter import JsonLineSegmenter, build_segmenter, detect_segmenter_kind

from . import evidence_compute as legacy
from .evidence_shell import _budget_data, _payload_fits
from .evidence_shell_fast_jsonl import _matches
from .evidence_shell_public import EvidenceShellPolicy
from .jsonl_physical import FixedCapacityTopK, field_predicate_matches, field_value, topk_sort_key
from .retrieval_session import RetrievalSessionStore
from .schema import AgentResult
from .source_versions import SourceSegment, SourceVersionStore


def _project_topn(
    item: Any,
    *,
    obj: Mapping[str, Any],
    raw: str,
    semantics: JsonLineSemantics | None,
    segment: SourceSegment,
    line_number: int,
) -> tuple[tuple[int, float | str], dict[str, Any]]:
    sort_value = field_value(
        obj,
        raw,
        item.sort_field,
        semantics=semantics,
        segment=segment,
        local_start_line=line_number,
        local_end_line=line_number,
    )
    values = {
        field: field_value(
            obj,
            raw,
            field,
            semantics=semantics,
            segment=segment,
            local_start_line=line_number,
            local_end_line=line_number,
        )
        for field in item.project_fields
    }
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
    return topk_sort_key(sort_value, numeric=item.numeric), projected


def _finalize_topn(item: Any, accumulator: FixedCapacityTopK, *, policy: EvidenceShellPolicy) -> dict[str, Any]:
    rows = accumulator.values()
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


def try_run_fixed_topk_jsonl_batch(
    request: legacy.EvidenceComputeRequest,
    *,
    policy: EvidenceShellPolicy,
    session: RetrievalSessionStore | None,
) -> dict[str, Any] | None:
    """Return a shared fixed-TopK JSONL batch, or ``None`` for planner fallback."""

    source = Path(request.source).expanduser().resolve()
    if not source.is_file():
        return None
    kind = detect_segmenter_kind(source) if request.segmenter == "auto" else request.segmenter
    if not isinstance(kind, str) or kind.strip().lower() not in {"jsonline", "json", "jsonl"}:
        return None

    compiled: list[Any] = []
    for spec in request.analyses:
        item = legacy._compile_jsonl(spec)
        if item is None:
            return None
        compiled.append(item)
    topn_items = [item for item in compiled if isinstance(item, legacy._CompiledJsonlTopN)]
    if not topn_items:
        return None

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

    for segment in view.segments:
        with Path(segment.path).open("r", encoding="utf-8", errors="replace") as handle:
            for line_number, raw in enumerate(handle, start=1):
                if not raw.strip():
                    continue

                raw_pass: list[Any] = []
                needs_json = time_scoped
                needs_semantics = time_scoped
                for item in compiled:
                    if any(not _matches({}, raw, stage) for stage in item.raw_predicates):
                        continue
                    raw_pass.append(item)
                    needs_json = needs_json or item.needs_json
                    needs_semantics = needs_semantics or item.needs_semantic_json
                if not raw_pass:
                    continue

                obj: Mapping[str, Any] = {}
                if needs_json:
                    try:
                        # Preserve the existing planner's shared JSON decoder seam
                        # so instrumentation and compatibility tests observe one
                        # decode per candidate line across both physical plans.
                        decoded = legacy.json.loads(raw)
                        obj = decoded if isinstance(decoded, Mapping) else {}
                    except legacy.json.JSONDecodeError:
                        obj = {}

                semantics: JsonLineSemantics | None = None
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

                for item in raw_pass:
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
                        for stage in item.field_predicates
                    ):
                        continue

                    if isinstance(item, legacy._CompiledJsonlAggregate):
                        item.matched += 1
                        if item.aggregate_stage.command != "count":
                            field = str(item.aggregate_stage.args[0])
                            value = field_value(
                                obj,
                                raw,
                                field,
                                semantics=semantics,
                                segment=segment,
                                local_start_line=line_number,
                                local_end_line=line_number,
                            )
                            key = "<missing>" if value is None else str(value)
                            assert item.counts is not None
                            item.counts[key] = item.counts.get(key, 0) + 1
                    else:
                        key, projected = _project_topn(
                            item,
                            obj=obj,
                            raw=raw,
                            semantics=semantics,
                            segment=segment,
                            line_number=line_number,
                        )
                        accumulators[id(item)].add(key, projected)

    outputs: list[dict[str, Any]] = []
    for item in compiled:
        if isinstance(item, legacy._CompiledJsonlAggregate):
            outputs.append(legacy._finalize_aggregate(item, policy=policy))
        else:
            outputs.append(_finalize_topn(item, accumulators[id(item)], policy=policy))

    fits, token_count, byte_count = _payload_fits({"outputs": outputs}, policy)
    source_view = view.to_dict()
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
                "source_version": view.key,
                "evidence_budget": _budget_data(policy),
                "execution_engine": "jsonl_shared_scan_batch",
            },
        ).to_dict()

    statuses = {str(item.get("status") or "") for item in outputs}
    return AgentResult(
        operation="evidence_compute",
        status="ok" if statuses == {"ok"} else "partial",
        outcome="not_assessed",
        coverage={"complete": all(item.get("status") == "ok" for item in outputs)},
        data={
            "outputs": outputs,
            "analysis_count": len(outputs),
            "source_view": source_view,
            "source_version": view.key,
            "evidence_budget": _budget_data(policy),
            "execution_engine": "jsonl_shared_scan_batch",
            "shared_scan_analyses": len(outputs),
            "canonical_remainder_analyses": 0,
            "physical_plan": {
                "source_scan": "jsonl_raw_lines",
                "json_decode": "shared_once_per_candidate_line",
                "semantic_enrichment": "lazy_from_decoded_json",
            },
            "time_scope": {
                "last": request.last,
                "since": request.since,
                "until": request.until,
            },
        },
    ).to_dict()


__all__ = ["try_run_fixed_topk_jsonl_batch"]