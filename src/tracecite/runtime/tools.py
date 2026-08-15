"""Small, deterministic tool surface intended for AI agents."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union

from tracecite_core.run import RunFile, RunIntegrityError, verify_manifest
from tracecite_core.segmenter import build_segmenter, detect_segmenter_kind
from tracecite_core.source import SourceError, resolve_paths
from tracecite_core.sample import SampleError, sample_file
from tracecite_core.survey import SurveyError, survey_file
from tracecite_core.text_filter import FilterError, filter_text, text_time_range

from .investigation import (
    BudgetExhausted,
    BudgetReservation,
    InvestigationCacheStore,
    InvestigationError,
    InvestigationStore,
    SAFE_CACHE_OPERATIONS,
    attach_investigation_result,
)
from .runtime import DEFAULT_RUNTIME, ScenarioRuntime
from .schema import AgentResult, EvidencePointer, MAX_RESULT_EVIDENCE, ScenarioDocument
from .scenario import load_spec, run_scenario


def _sha256(path: Path) -> str:
    item = RunFile.from_path("evidence", path)
    if not item.sha256:
        raise RunIntegrityError(f"无法计算证据摘要: {path}")
    return item.sha256


def _evidence_uri(sha256: str, start_line: Optional[int], end_line: Optional[int]) -> str:
    fragment = ""
    if start_line is not None:
        fragment = f"#L{start_line}"
        if end_line is not None and end_line != start_line:
            fragment += f"-L{end_line}"
    return f"evidence://sha256/{sha256}{fragment}"


def _error(operation: str, exc: Exception) -> Dict[str, Any]:
    return AgentResult(
        operation=operation,
        status="error",
        outcome="unknown",
        error={"type": type(exc).__name__, "message": str(exc)},
    ).to_dict()


def _mark_cache(result: Mapping[str, Any], metadata: Mapping[str, Any]) -> Dict[str, Any]:
    payload = dict(result)
    data = dict(payload.get("data") or {})
    data["cache"] = dict(metadata)
    payload["data"] = data
    return payload


def _budget_error(operation: str, exc: BudgetExhausted) -> Dict[str, Any]:
    payload = _error(operation, exc)
    payload["error"] = {
        "type": type(exc).__name__,
        "message": str(exc),
        "budget": dict(exc.details),
    }
    data = dict(payload.get("data") or {})
    data["budget"] = {
        "status": "exhausted",
        **dict(exc.details),
    }
    data["stop_reason"] = {"kind": "budget_exhausted", "detail": str(exc)}
    payload["data"] = data
    return payload


def _prepare_linked(
    operation: str,
    investigation_path: Optional[Union[str, Path]],
    *,
    budget_request: Optional[Mapping[str, Any]] = None,
    cache_enabled: bool = True,
    cache_safe: bool = False,
    cache_bypass_reason: str = "",
    cache_parameters: Optional[Mapping[str, Any]] = None,
    cache_sources: Sequence[Mapping[str, Any]] = (),
    cache_segmenter: str = "",
    cache_snapshot: Optional[bool] = None,
    defer_cache: bool = False,
) -> Dict[str, Any]:
    """Reserve linked budget and optionally look up a safe deterministic cache."""

    prepared: Dict[str, Any] = {
        "reservation": None,
        "cache_store": None,
        "cache_key": None,
        "cache_meta": None,
        "cached": None,
        "budget_error": None,
    }
    if investigation_path is None:
        return prepared
    store = InvestigationStore(investigation_path)
    request = dict(budget_request or {})
    try:
        prepared["reservation"] = store.reserve_budget(operation, **request)
    except BudgetExhausted as exc:
        prepared["budget_error"] = _budget_error(operation, exc)
        return prepared
    if defer_cache:
        return prepared
    _lookup_linked_cache(
        prepared,
        investigation_path,
        operation=operation,
        cache_enabled=cache_enabled,
        cache_safe=cache_safe,
        cache_bypass_reason=cache_bypass_reason,
        cache_parameters=cache_parameters,
        cache_sources=cache_sources,
        cache_segmenter=cache_segmenter,
        cache_snapshot=cache_snapshot,
    )
    return prepared


def _lookup_linked_cache(
    prepared: Dict[str, Any],
    investigation_path: Optional[Union[str, Path]],
    *,
    operation: str,
    cache_enabled: bool,
    cache_safe: bool,
    cache_bypass_reason: str = "",
    cache_parameters: Optional[Mapping[str, Any]] = None,
    cache_sources: Sequence[Mapping[str, Any]] = (),
    cache_segmenter: str = "",
    cache_snapshot: Optional[bool] = None,
) -> None:
    if investigation_path is None:
        return
    if not cache_enabled:
        prepared["cache_meta"] = {"status": "bypass", "reason": "disabled"}
        return
    if operation not in SAFE_CACHE_OPERATIONS or not cache_safe:
        prepared["cache_meta"] = {
            "status": "bypass",
            "reason": cache_bypass_reason or "operation_not_cache_safe",
        }
        return
    if len(cache_sources) > 100:
        prepared["cache_meta"] = {
            "status": "bypass",
            "reason": "source_count_limit",
        }
        return
    try:
        cache_store = InvestigationCacheStore(
            InvestigationCacheStore.default_path(investigation_path)
        )
        key = cache_store.make_key(
            operation,
            cache_parameters or {},
            source_refs=cache_sources,
            segmenter=cache_segmenter,
            snapshot=cache_snapshot,
        )
        cached, metadata = cache_store.lookup(
            key,
            source_refs=cache_sources,
            operation=operation,
            parameters=cache_parameters,
            segmenter=cache_segmenter,
            snapshot=cache_snapshot,
        )
        prepared.update(
            {
                "cache_store": cache_store,
                "cache_key": key,
                "cache_meta": metadata,
                "cached": cached,
            }
        )
    except (OSError, ValueError, InvestigationError) as exc:
        prepared["cache_meta"] = {
            "status": "bypass",
            "reason": "cache_unavailable",
            "detail": str(exc),
        }


def _actual_budget_usage(
    operation: str,
    result: Mapping[str, Any],
    *,
    parameters: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    params = parameters or {}
    data = result.get("data") or {}
    text = data.get("text") if isinstance(data, Mapping) else None
    usage: Dict[str, Any] = {
        "executions": 1,
        "searches": 1 if operation == "search" else 0,
        "queries": 1 if operation == "search" else 0,
        "recorded_evidence_pointers": len(result.get("evidence") or []),
        "expand_requested_chars": int(params.get("max_chars") or 0)
        if operation == "expand"
        else 0,
        "expand_returned_chars": len(str(text)) if operation == "expand" and text is not None else 0,
    }
    return usage


def _record_result(
    result: Mapping[str, Any],
    *,
    operation: str,
    investigation_path: Optional[Union[str, Path]],
    hypothesis_id: Optional[str],
    test_id: Optional[str],
    parameters: Optional[Mapping[str, Any]] = None,
    reservation: Optional[BudgetReservation] = None,
    cache_store: Optional[InvestigationCacheStore] = None,
    cache_key: Optional[str] = None,
    cache_sources: Sequence[Mapping[str, Any]] = (),
    cache_segmenter: str = "",
    cache_snapshot: Optional[bool] = None,
) -> Dict[str, Any]:
    payload = dict(result)
    if reservation is not None:
        try:
            budget_status = reservation.finalize(
                _actual_budget_usage(operation, payload, parameters=parameters)
            )
            data = dict(payload.get("data") or {})
            data["budget"] = {
                "status": "ok" if not budget_status.get("violations") else "exhausted",
                "usage": budget_status.get("usage"),
                "remaining": budget_status.get("remaining"),
            }
            if budget_status.get("violations"):
                data["stop_reason"] = budget_status.get("stop_reason")
            payload["data"] = data
        except InvestigationError as exc:
            payload = _error(operation, exc)
    if (
        cache_store is not None
        and cache_key
        and payload.get("status") != "error"
    ):
        try:
            cache_store.put(
                cache_key,
                operation=operation,
                result=payload,
                source_refs=cache_sources,
                parameters=parameters,
                segmenter=cache_segmenter,
                snapshot=cache_snapshot,
            )
        except (OSError, ValueError, InvestigationError) as exc:
            data = dict(payload.get("data") or {})
            cache_meta = dict(data.get("cache") or {})
            cache_meta.update({"status": "bypass", "reason": "write_failed", "detail": str(exc)})
            data["cache"] = cache_meta
            payload["data"] = data
    try:
        return attach_investigation_result(
            payload,
            operation=operation,
            investigation_path=investigation_path,
            hypothesis_id=hypothesis_id,
            test_id=test_id,
            parameters=parameters,
        )
    except InvestigationError as exc:
        return _error(operation, exc)
    except (OSError, ValueError, TypeError) as exc:
        return _error(operation, InvestigationError(f"调查状态关联失败: {exc}"))


def probe(
    input_path: Union[str, Path],
    *,
    glob: str = "*",
    recursive: bool = False,
    segmenter: str = "auto",
    investigation_path: Optional[Union[str, Path]] = None,
    hypothesis_id: Optional[str] = None,
    test_id: Optional[str] = None,
    cache: bool = True,
) -> Dict[str, Any]:
    """Inspect sources without producing filter artifacts."""
    prepared: Dict[str, Any] = {}
    parameters = {
        "input": str(input_path),
        "glob": glob,
        "recursive": recursive,
        "segmenter": segmenter,
    }
    try:
        prepared = _prepare_linked(
            "probe",
            investigation_path,
            budget_request={
                "executions": 1,
                "recorded_evidence_pointers": 0,
            },
            cache_enabled=cache,
            cache_safe=True,
            cache_parameters=parameters,
            defer_cache=True,
        )
        if prepared.get("budget_error") is not None:
            return prepared["budget_error"]
        files = resolve_paths(str(input_path), glob=glob, recursive=recursive)
        source_refs = [
            {"path": str(path.resolve()), "sha256": _sha256(path)} for path in files
        ]
        segmenter_identity = "|".join(
            detect_segmenter_kind(path) if segmenter == "auto" else segmenter
            for path in files
        )
        _lookup_linked_cache(
            prepared,
            investigation_path,
            operation="probe",
            cache_enabled=cache,
            cache_safe=True,
            cache_parameters=parameters,
            cache_sources=source_refs,
            cache_segmenter=segmenter_identity,
            cache_snapshot=None,
        )
        if prepared.get("cached") is not None:
            return _record_result(
                _mark_cache(
                    prepared["cached"],
                    {**dict(prepared.get("cache_meta") or {}), "operation": "probe"},
                ),
                operation="probe",
                investigation_path=investigation_path,
                hypothesis_id=hypothesis_id,
                test_id=test_id,
                parameters=parameters,
                reservation=prepared.get("reservation"),
            )
        sources: List[Dict[str, Any]] = []
        recommendations: List[str] = []
        for path in files:
            kind = detect_segmenter_kind(path) if segmenter == "auto" else segmenter
            seg = build_segmenter(kind)
            source = RunFile.from_path("source", path)
            time_info = text_time_range(path, segmenter=seg)
            line_lengths: List[int] = []
            json_like_lines = 0
            sampled_lines = 0
            try:
                with path.open("r", encoding="utf-8", errors="replace") as handle:
                    for line in handle:
                        sampled_lines += 1
                        if sampled_lines > 1000:
                            break
                        stripped = line.strip()
                        line_lengths.append(len(line))
                        if stripped.startswith("{") and stripped.endswith("}"):
                            json_like_lines += 1
            except OSError:
                line_lengths = []
            if line_lengths:
                ordered = sorted(line_lengths)
                p99 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.99))]
                if p99 > 2048:
                    recommendations.append(
                        f"{path.name}: line_length_p99={p99}; "
                        "use filter --max-line-chars 1024 or search --max-line-chars N"
                    )
                if json_like_lines >= max(3, sampled_lines // 10):
                    recommendations.append(
                        f"{path.name}: single_line_json_detected; "
                        "prefer records_path + expand over reading filter output_path"
                    )
            sources.append(
                {
                    "path": str(path.resolve()),
                    "size": source.size,
                    "sha256": source.sha256,
                    "segmenter": kind,
                    "records": time_info.get("total_records"),
                    "time_from": time_info.get("time_from"),
                    "time_to": time_info.get("time_to"),
                    "timestamped_records": time_info.get("timestamped_records"),
                }
            )
        result = AgentResult(
            operation="probe",
            outcome="not_assessed",
            data={"sources": sources, "source_count": len(sources)},
            coverage={"files": len(sources)},
            next_queries=recommendations[:5],
        ).to_dict()
        cache_meta = prepared.get("cache_meta")
        if cache_meta is not None:
            result = _mark_cache(result, {**dict(cache_meta), "operation": "probe"})
        return _record_result(
            result,
            operation="probe",
            investigation_path=investigation_path,
            hypothesis_id=hypothesis_id,
            test_id=test_id,
            parameters=parameters,
            reservation=prepared.get("reservation"),
            cache_store=prepared.get("cache_store"),
            cache_key=prepared.get("cache_key"),
            cache_sources=source_refs,
            cache_segmenter=segmenter_identity,
            cache_snapshot=None,
        )
    except (OSError, ValueError, SourceError) as exc:
        return _record_result(
            _error("probe", exc),
            operation="probe",
            investigation_path=investigation_path,
            hypothesis_id=hypothesis_id,
            test_id=test_id,
            parameters=parameters,
            reservation=prepared.get("reservation"),
        )
    except Exception as exc:
        return _record_result(
            _error("probe", exc),
            operation="probe",
            investigation_path=investigation_path,
            hypothesis_id=hypothesis_id,
            test_id=test_id,
            parameters=parameters,
            reservation=prepared.get("reservation"),
        )


def search(
    input_path: Union[str, Path],
    query: str,
    *,
    regex: bool = False,
    output_path: Optional[Union[str, Path]] = None,
    snapshot: bool = True,
    segmenter: str = "auto",
    last: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    fold: bool = False,
    max_evidence: Optional[int] = None,
    max_line_chars: Optional[int] = None,
    investigation_path: Optional[Union[str, Path]] = None,
    hypothesis_id: Optional[str] = None,
    test_id: Optional[str] = None,
    cache: bool = True,
) -> Dict[str, Any]:
    """Search one source and return pointers; literal matching is the default."""
    prepared: Dict[str, Any] = {}
    parameters = {
        "input": str(input_path),
        "query": query,
        "regex": regex,
        "snapshot": snapshot,
        "segmenter": segmenter,
        "last": last,
        "since": since,
        "until": until,
        "fold": fold,
        "max_evidence": max_evidence,
        "max_line_chars": max_line_chars,
    }
    evidence_limit = MAX_RESULT_EVIDENCE if max_evidence is None else max(1, int(max_evidence))
    try:
        source = Path(input_path).expanduser().resolve()
        cache_safe = bool(snapshot and output_path is None)
        prepared = _prepare_linked(
            "search",
            investigation_path,
            budget_request={
                "executions": 1,
                "searches": 1,
                "queries": 1,
                # Search may return any number of pointers up to the public
                # result bound. Reserve that bound before scanning so a hard
                # pointer policy can never be exceeded after finalization.
                "recorded_evidence_pointers": evidence_limit,
            },
            cache_enabled=cache,
            cache_safe=cache_safe,
            cache_bypass_reason=(
                "no_snapshot" if not snapshot else "output_side_effect"
            ),
            cache_parameters=parameters,
            defer_cache=True,
        )
        if prepared.get("budget_error") is not None:
            return prepared["budget_error"]
        kind = detect_segmenter_kind(source) if segmenter == "auto" else segmenter
        source_sha256 = _sha256(source)
        source_refs = [{"path": str(source), "sha256": source_sha256}]
        _lookup_linked_cache(
            prepared,
            investigation_path,
            operation="search",
            cache_enabled=cache,
            cache_safe=cache_safe,
            cache_bypass_reason=(
                "no_snapshot" if not snapshot else "output_side_effect"
            ),
            cache_parameters=parameters,
            cache_sources=source_refs,
            cache_segmenter=kind,
            cache_snapshot=snapshot,
        )
        if prepared.get("cached") is not None:
            return _record_result(
                _mark_cache(
                    prepared["cached"],
                    {**dict(prepared.get("cache_meta") or {}), "operation": "search"},
                ),
                operation="search",
                investigation_path=investigation_path,
                hypothesis_id=hypothesis_id,
                test_id=test_id,
                parameters=parameters,
                reservation=prepared.get("reservation"),
            )
        pattern = query if regex else re.escape(query)
        if output_path is None:
            run_id = datetime.now().strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
            resolved_output = (
                source.parent / ".tracecite" / "agent-search" / run_id / "evidence.log"
            )
        else:
            resolved_output = Path(output_path)
        result = filter_text(
            source,
            pattern=pattern,
            output_path=resolved_output,
            snapshot=snapshot,
            segmenter=build_segmenter(kind),
            last=last,
            since=since,
            until=until,
            template_threshold=10 if fold else 0,
            max_line_chars=max_line_chars,
        )
        evidence_source = Path(result.work_input).resolve()
        digest = _sha256(evidence_source)
        evidence: List[Dict[str, Any]] = []
        if result.records_path and result.records_path.is_file():
            with result.records_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if len(evidence) >= evidence_limit:
                        break
                    row = json.loads(line)
                    meta = row.get("metadata") or {}
                    start_line = meta.get("start_line")
                    end_line = meta.get("end_line")
                    text = str(row.get("text") or "")
                    pointer = EvidencePointer(
                        uri=_evidence_uri(digest, start_line, end_line),
                        source_path=str(evidence_source),
                        sha256=digest,
                        start_line=start_line,
                        end_line=end_line,
                        timestamp=meta.get("timestamp"),
                        label=next((item.strip() for item in text.splitlines() if item.strip()), "")[:240] or None,
                        metadata={"term": meta.get("term"), "terms": meta.get("terms") or []},
                    )
                    evidence.append(pointer.to_dict())
        summary = dict(result.unmatched_summary or {})
        next_queries = [
            str(item.get("token"))
            for item in summary.get("top_unmatched_tokens") or []
            if item.get("token")
        ][:10]
        warnings: List[str] = []
        if not evidence:
            warnings.append(
                "零命中只表示当前查询和范围内证据不足；可使用 next_queries、放宽时间窗或更换格式。"
            )
        artifacts = [
            {"role": role, "path": str(path)}
            for role, path in (
                ("filtered_log", result.output_path),
                ("matched_records", result.records_path),
                ("hit_metadata", result.hits_path),
                ("templates", result.templates_path),
            )
            if path is not None
        ]
        result = AgentResult(
            operation="search",
            status="ok" if evidence else "no_match",
            outcome="supported" if evidence else "unknown",
            evidence=evidence,
            artifacts=artifacts,
            coverage={
                "scoped_lines": result.total_lines,
                "match_records": result.match_records,
                "match_lines": result.match_lines,
                "evidence_returned": len(evidence),
                "evidence_truncated": result.match_records > len(evidence),
                "unmatched": summary,
            },
            warnings=warnings,
            missing_evidence=(
                []
                if evidence
                else [
                    {
                        "kind": "query_coverage",
                        "detail": "No evidence matched the current query and scope.",
                    }
                ]
            ),
            next_queries=next_queries,
            data={
                "query": query,
                "regex": regex,
                "segmenter": kind,
                "engine": result.engine,
                "source_sha256": digest,
            },
        ).to_dict()
        cache_meta = prepared.get("cache_meta")
        if cache_meta is not None:
            result = _mark_cache(result, {**dict(cache_meta), "operation": "search"})
        return _record_result(
            result,
            operation="search",
            investigation_path=investigation_path,
            hypothesis_id=hypothesis_id,
            test_id=test_id,
            parameters=parameters,
            reservation=prepared.get("reservation"),
            cache_store=prepared.get("cache_store"),
            cache_key=prepared.get("cache_key"),
            cache_sources=source_refs,
            cache_segmenter=kind,
            cache_snapshot=snapshot,
        )
    except (OSError, ValueError, FilterError, RunIntegrityError) as exc:
        return _record_result(
            _error("search", exc),
            operation="search",
            investigation_path=investigation_path,
            hypothesis_id=hypothesis_id,
            test_id=test_id,
            parameters=parameters,
            reservation=prepared.get("reservation"),
        )
    except Exception as exc:
        return _record_result(
            _error("search", exc),
            operation="search",
            investigation_path=investigation_path,
            hypothesis_id=hypothesis_id,
            test_id=test_id,
            parameters=parameters,
            reservation=prepared.get("reservation"),
        )


def survey(
    input_path: Union[str, Path],
    *,
    snapshot: bool = True,
    segmenter: str = "auto",
    last: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    max_templates: int = 20,
    samples_per_template: int = 2,
    investigation_path: Optional[Union[str, Path]] = None,
    hypothesis_id: Optional[str] = None,
    test_id: Optional[str] = None,
    cache: bool = True,
) -> Dict[str, Any]:
    """Return a bounded, descriptive overview of one source.

    Survey intentionally has no query or diagnostic proposition.  Its Core
    summary is adapted into the same Result envelope as the other Agent tools;
    sample rows become EvidencePointers only when the default immutable
    snapshot boundary is enabled.
    """

    prepared: Dict[str, Any] = {}
    parameters = {
        "input": str(input_path),
        "snapshot": snapshot,
        "segmenter": segmenter,
        "last": last,
        "since": since,
        "until": until,
        "max_templates": max_templates,
        "samples_per_template": samples_per_template,
    }
    try:
        source = Path(input_path).expanduser().resolve()
        kind = detect_segmenter_kind(source) if segmenter == "auto" else segmenter
        prepared = _prepare_linked(
            "survey",
            investigation_path,
            budget_request={
                "executions": 1,
                "recorded_evidence_pointers": min(
                    MAX_RESULT_EVIDENCE,
                    max(0, int(max_templates) * int(samples_per_template)),
                ) if snapshot else 0,
            },
            cache_enabled=cache,
            cache_safe=False,
            cache_bypass_reason="raw_payload",
        )
        if prepared.get("budget_error") is not None:
            return prepared["budget_error"]
        summary = survey_file(
            source,
            snapshot=snapshot,
            segmenter=build_segmenter(kind),
            last=last,
            since=since,
            until=until,
            max_templates=max_templates,
            samples_per_template=samples_per_template,
        )
        payload = summary.to_dict()
        data = dict(payload.get("data") or {})
        coverage = dict(payload.get("coverage") or {})
        warnings: List[str] = []
        if summary.unparsed_timestamp_records:
            warnings.append(
                "部分记录未解析出时间戳；时间范围与时间过滤对这些记录只能保守覆盖。"
            )
        if summary.template_evictions or summary.spike_evictions or summary.level_evictions:
            warnings.append(
                "统计达到内存预算并使用有界近似；top_templates、spikes 或 levels 不是全量唯一集合。"
            )
        if not snapshot and samples_per_template:
            warnings.append(
                "snapshot=false：样本引用的是可变源，不应作为不可变证据引用；需要证据时请重新启用 snapshot。"
            )

        evidence: List[Dict[str, Any]] = []
        templates = data.get("top_templates") or []
        for template_row in templates:
            if not isinstance(template_row, dict):
                continue
            for sample in template_row.get("samples") or []:
                if len(evidence) >= MAX_RESULT_EVIDENCE:
                    break
                if not isinstance(sample, dict):
                    continue
                start_line = sample.get("start_line")
                end_line = sample.get("end_line")
                if not snapshot or start_line is None:
                    continue
                pointer = EvidencePointer(
                    uri=_evidence_uri(
                        summary.source_sha256,
                        int(start_line),
                        int(end_line) if end_line is not None else int(start_line),
                    ),
                    source_path=str(summary.work_input),
                    sha256=summary.source_sha256,
                    start_line=int(start_line),
                    end_line=int(end_line) if end_line is not None else int(start_line),
                    timestamp=sample.get("timestamp"),
                    label=str(template_row.get("template") or "survey sample")[:240],
                    metadata={
                        "kind": "survey_sample",
                        "template": template_row.get("template"),
                        "text": sample.get("text"),
                    },
                )
                evidence.append(pointer.to_dict())
            if len(evidence) >= MAX_RESULT_EVIDENCE:
                break
        coverage.update(
            {
                "evidence_returned": len(evidence),
                "evidence_truncated": bool(
                    snapshot
                    and
                    sum(
                        len(row.get("samples") or [])
                        for row in templates
                        if isinstance(row, dict)
                    )
                    > len(evidence)
                ),
                "evidence_withheld": bool(not snapshot and samples_per_template),
                "snapshot": snapshot,
            }
        )
        if not evidence and samples_per_template:
            coverage.setdefault("evidence_returned", 0)
        data.update(
            {
                "source": str(summary.original_source),
                "work_input": str(summary.work_input),
                "snapshot_path": str(summary.snapshot_path) if summary.snapshot_path else None,
                "source_sha256": summary.source_sha256,
                "segmenter": summary.segmenter,
                "snapshot": snapshot,
            }
        )
        result = AgentResult(
            operation="survey",
            status="ok",
            outcome="not_assessed",
            evidence=evidence,
            coverage=coverage,
            warnings=warnings,
            missing_evidence=(
                [
                    {
                        "kind": "immutable_snapshot",
                        "detail": "snapshot=false prevents survey samples from being immutable evidence.",
                    }
                ]
                if not snapshot and samples_per_template
                else []
            ),
            data=data,
        ).to_dict()
        cache_meta = prepared.get("cache_meta")
        if cache_meta is not None:
            result = _mark_cache(result, {**dict(cache_meta), "operation": "survey"})
        return _record_result(
            result,
            operation="survey",
            investigation_path=investigation_path,
            hypothesis_id=hypothesis_id,
            test_id=test_id,
            parameters=parameters,
            reservation=prepared.get("reservation"),
        )
    except (OSError, ValueError, FilterError, SurveyError, RunIntegrityError) as exc:
        return _record_result(
            _error("survey", exc),
            operation="survey",
            investigation_path=investigation_path,
            hypothesis_id=hypothesis_id,
            test_id=test_id,
            parameters=parameters,
            reservation=prepared.get("reservation"),
        )
    except Exception as exc:
        return _record_result(
            _error("survey", exc),
            operation="survey",
            investigation_path=investigation_path,
            hypothesis_id=hypothesis_id,
            test_id=test_id,
            parameters=parameters,
            reservation=prepared.get("reservation"),
        )


def sample(
    input_path: Union[str, Path],
    *,
    strategy: str = "head-tail",
    count: int = 10,
    max_chars: int = 8_000,
    snapshot: bool = True,
    segmenter: str = "auto",
    last: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    investigation_path: Optional[Union[str, Path]] = None,
    hypothesis_id: Optional[str] = None,
    test_id: Optional[str] = None,
    cache: bool = True,
) -> Dict[str, Any]:
    """Return bounded raw context without a query or diagnostic conclusion.

    ``sample`` is intentionally one implementation for both the Python API
    and the CLI's ``sample``/``peek`` commands.  The Core result is adapted to
    the Agent envelope here; Core itself never imports Runtime schemas.
    """

    prepared: Dict[str, Any] = {}
    parameters = {
        "input": str(input_path),
        "strategy": strategy,
        "count": count,
        "max_chars": max_chars,
        "snapshot": snapshot,
        "segmenter": segmenter,
        "last": last,
        "since": since,
        "until": until,
    }
    try:
        source = Path(input_path).expanduser().resolve()
        kind = segmenter
        prepared = _prepare_linked(
            "sample",
            investigation_path,
            budget_request={
                "executions": 1,
                "recorded_evidence_pointers": (
                    min(MAX_RESULT_EVIDENCE, max(0, int(count))) if snapshot else 0
                ),
            },
            cache_enabled=cache,
            cache_safe=False,
            cache_bypass_reason="raw_payload",
        )
        if prepared.get("budget_error") is not None:
            return prepared["budget_error"]
        summary = sample_file(
            source,
            strategy=strategy,
            count=count,
            max_chars=max_chars,
            snapshot=snapshot,
            segmenter=kind,
            last=last,
            since=since,
            until=until,
        )
        payload = summary.to_dict()
        coverage = dict(payload.get("coverage") or {})
        data = dict(payload.get("data") or {})
        warnings: List[str] = []
        if summary.unparsed_timestamp_records:
            warnings.append(
                "部分记录未解析出时间戳；时间范围与时间过滤对这些记录只能保守覆盖。"
            )
        if coverage.get("omissions"):
            warnings.append(
                "sample 是有界原始语境观察；覆盖中的 omissions 记录了时间范围、抽样和字符预算造成的省略。"
            )
        if not snapshot:
            warnings.append(
                "snapshot=false：样本引用的是可变源，不应作为不可变证据引用；需要证据时请重新启用 snapshot。"
            )

        evidence: List[Dict[str, Any]] = []
        for row in summary.samples:
            if len(evidence) >= MAX_RESULT_EVIDENCE:
                break
            start_line = row.get("start_line")
            end_line = row.get("end_line")
            if not snapshot or start_line is None:
                continue
            end = int(end_line) if end_line is not None else int(start_line)
            pointer = EvidencePointer(
                uri=_evidence_uri(summary.source_sha256, int(start_line), end),
                source_path=str(summary.work_input),
                sha256=summary.source_sha256,
                start_line=int(start_line),
                end_line=end,
                timestamp=row.get("timestamp"),
                label="sample",
                metadata={
                    "kind": "sample",
                    "strategy": summary.strategy,
                    "truncated": bool(row.get("truncated")),
                },
            )
            evidence.append(pointer.to_dict())

        selected_count = len(summary.samples)
        coverage.update(
            {
                "evidence_returned": len(evidence),
                "evidence_truncated": bool(snapshot and selected_count > len(evidence)),
                "evidence_withheld": bool(not snapshot and selected_count),
                "snapshot": snapshot,
            }
        )
        missing_evidence: List[Dict[str, Any]] = []
        if not snapshot and selected_count:
            missing_evidence.append(
                {
                    "kind": "immutable_snapshot",
                    "detail": "snapshot=false prevents sample snippets from being immutable evidence.",
                }
            )
        if coverage.get("evidence_truncated"):
            missing_evidence.append(
                {
                    "kind": "evidence_budget",
                    "detail": "the inline EvidencePointer budget was reached; inspect coverage and rerun with a narrower scope if needed.",
                }
            )
        result = AgentResult(
            operation="sample",
            status="ok",
            outcome="not_assessed",
            evidence=evidence,
            coverage=coverage,
            warnings=warnings,
            missing_evidence=missing_evidence,
            data=data,
        ).to_dict()
        cache_meta = prepared.get("cache_meta")
        if cache_meta is not None:
            result = _mark_cache(result, {**dict(cache_meta), "operation": "sample"})
        return _record_result(
            result,
            operation="sample",
            investigation_path=investigation_path,
            hypothesis_id=hypothesis_id,
            test_id=test_id,
            parameters=parameters,
            reservation=prepared.get("reservation"),
        )
    except (OSError, ValueError, FilterError, SampleError, RunIntegrityError) as exc:
        return _record_result(
            _error("sample", exc),
            operation="sample",
            investigation_path=investigation_path,
            hypothesis_id=hypothesis_id,
            test_id=test_id,
            parameters=parameters,
            reservation=prepared.get("reservation"),
        )
    except Exception as exc:
        return _record_result(
            _error("sample", exc),
            operation="sample",
            investigation_path=investigation_path,
            hypothesis_id=hypothesis_id,
            test_id=test_id,
            parameters=parameters,
            reservation=prepared.get("reservation"),
        )


# ``peek`` is a compatibility spelling for the same operation, not a second
# implementation with potentially different sampling semantics.
peek = sample


def expand(
    source_path: Union[str, Path],
    start_line: int,
    *,
    end_line: Optional[int] = None,
    before: int = 3,
    after: int = 3,
    expected_sha256: Optional[str] = None,
    max_chars: int = 20_000,
    investigation_path: Optional[Union[str, Path]] = None,
    hypothesis_id: Optional[str] = None,
    test_id: Optional[str] = None,
    cache: bool = True,
) -> Dict[str, Any]:
    """Expand bounded context around a cited line range after hash checking."""
    prepared: Dict[str, Any] = {}
    parameters = {
        "source": str(source_path),
        "start_line": start_line,
        "end_line": end_line,
        "before": before,
        "after": after,
        "expected_sha256": expected_sha256,
        "max_chars": max_chars,
    }
    try:
        prepared = _prepare_linked(
            "expand",
            investigation_path,
            budget_request={
                "executions": 1,
                "recorded_evidence_pointers": 1,
                "expand_requested_chars": max_chars,
            },
            cache_enabled=cache,
            cache_safe=False,
            cache_bypass_reason="raw_payload",
        )
        if prepared.get("budget_error") is not None:
            return prepared["budget_error"]
        path = Path(source_path).expanduser().resolve()
        if start_line <= 0 or (end_line is not None and end_line < start_line):
            raise ValueError("行号范围无效")
        if max_chars <= 0:
            raise ValueError("max_chars 必须大于 0")
        digest = _sha256(path)
        if expected_sha256 and digest != expected_sha256:
            raise RunIntegrityError(
                f"证据文件摘要不匹配: {digest} != {expected_sha256}"
            )
        selected_end = end_line or start_line
        context_start = max(1, start_line - max(0, before))
        context_end = selected_end + max(0, after)
        rows: List[str] = []
        last_seen = 0
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for number, line in enumerate(handle, start=1):
                last_seen = number
                if number < context_start:
                    continue
                if number > context_end:
                    break
                rows.append(f"{number}: {line}")
        if last_seen < selected_end:
            raise ValueError(
                f"引用行超出证据文件范围: {selected_end} > {last_seen}"
            )
        text = "".join(rows)
        truncated = len(text) > max_chars
        if truncated:
            text = text[:max_chars]
        pointer = EvidencePointer(
            uri=_evidence_uri(digest, start_line, selected_end),
            source_path=str(path),
            sha256=digest,
            start_line=start_line,
            end_line=selected_end,
        )
        result = AgentResult(
            operation="expand",
            outcome="supported",
            evidence=[pointer.to_dict()],
            coverage={
                "context_start_line": context_start,
                "context_end_line": context_end,
                "truncated": truncated,
            },
            data={"text": text},
        ).to_dict()
        cache_meta = prepared.get("cache_meta")
        if cache_meta is not None:
            result = _mark_cache(result, {**dict(cache_meta), "operation": "expand"})
        return _record_result(
            result,
            operation="expand",
            investigation_path=investigation_path,
            hypothesis_id=hypothesis_id,
            test_id=test_id,
            parameters=parameters,
            reservation=prepared.get("reservation"),
        )
    except (OSError, ValueError, RunIntegrityError) as exc:
        return _record_result(
            _error("expand", exc),
            operation="expand",
            investigation_path=investigation_path,
            hypothesis_id=hypothesis_id,
            test_id=test_id,
            parameters=parameters,
            reservation=prepared.get("reservation"),
        )
    except Exception as exc:
        return _record_result(
            _error("expand", exc),
            operation="expand",
            investigation_path=investigation_path,
            hypothesis_id=hypothesis_id,
            test_id=test_id,
            parameters=parameters,
            reservation=prepared.get("reservation"),
        )


def verify(
    manifest_path: Union[str, Path],
    *,
    investigation_path: Optional[Union[str, Path]] = None,
    hypothesis_id: Optional[str] = None,
    test_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Verify a completed evidence manifest without throwing to the caller."""
    parameters = {"manifest": str(manifest_path)}
    prepared = _prepare_linked(
        "verify",
        investigation_path,
        budget_request={"executions": 1},
        cache_enabled=False,
        cache_safe=False,
        cache_bypass_reason="verification_not_cache_safe",
    )
    if prepared.get("budget_error") is not None:
        return prepared["budget_error"]
    try:
        checked = verify_manifest(Path(manifest_path))
        result = AgentResult(
            operation="verify",
            run_id=str(checked.get("run_id") or "") or None,
            verdict=str(checked.get("verdict") or "") or None,
            outcome="supported",
            coverage={"checked_files": checked.get("checked_files", 0)},
            verification={"integrity_checked": True, "manifest": str(Path(manifest_path))},
            data=checked,
        ).to_dict()
        return _record_result(
            result,
            operation="verify",
            investigation_path=investigation_path,
            hypothesis_id=hypothesis_id,
            test_id=test_id,
            parameters=parameters,
            reservation=prepared.get("reservation"),
        )
    except (OSError, ValueError, RunIntegrityError) as exc:
        return _record_result(
            _error("verify", exc),
            operation="verify",
            investigation_path=investigation_path,
            hypothesis_id=hypothesis_id,
            test_id=test_id,
            parameters=parameters,
            reservation=prepared.get("reservation"),
        )
    except Exception as exc:
        return _record_result(
            _error("verify", exc),
            operation="verify",
            investigation_path=investigation_path,
            hypothesis_id=hypothesis_id,
            test_id=test_id,
            parameters=parameters,
            reservation=prepared.get("reservation"),
        )


def run(
    scenario: Union[Mapping[str, Any], str, Path],
    *,
    base_dir: Optional[Union[str, Path]] = None,
    platform: str = "",
    runtime: ScenarioRuntime = DEFAULT_RUNTIME,
    investigation_path: Optional[Union[str, Path]] = None,
    hypothesis_id: Optional[str] = None,
    test_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute a scenario and return the canonical Agent result envelope."""
    parameters: Dict[str, Any] = {
        "scenario": str(scenario) if not isinstance(scenario, Mapping) else "inline",
        "base_dir": str(base_dir) if base_dir else "",
        "platform": platform,
    }
    prepared = _prepare_linked(
        "run",
        investigation_path,
        budget_request={
            "executions": 1,
            # Scenario summaries are bounded to the same public evidence cap
            # as search; reserve that worst case before invoking an extension.
            "recorded_evidence_pointers": MAX_RESULT_EVIDENCE,
        },
        cache_enabled=False,
        cache_safe=False,
        cache_bypass_reason="scenario_not_cache_safe",
    )
    if prepared.get("budget_error") is not None:
        return prepared["budget_error"]
    try:
        spec_path: Optional[Path] = None
        if isinstance(scenario, Mapping):
            document = ScenarioDocument.from_dict(scenario)
            spec = document.to_dict()
            resolved_base = Path(base_dir or Path.cwd()).expanduser().resolve()
        else:
            spec_path = Path(scenario).expanduser().resolve()
            spec = load_spec(spec_path)
            resolved_base = Path(base_dir).expanduser().resolve() if base_dir else spec_path.parent
        summary = run_scenario(
            spec,
            base_dir=resolved_base,
            platform=platform,
            spec_path=spec_path,
            runtime=runtime,
        )
        return _record_result(
            AgentResult.from_scenario_summary(summary).to_dict(),
            operation="run",
            investigation_path=investigation_path,
            hypothesis_id=hypothesis_id,
            test_id=test_id,
            parameters={
                "scenario": str(spec_path) if spec_path else "inline",
                "base_dir": str(resolved_base),
                "platform": platform,
            },
            reservation=prepared.get("reservation"),
        )
    except Exception as exc:  # public tool boundary always returns a structured error
        return _record_result(
            _error("run", exc),
            operation="run",
            investigation_path=investigation_path,
            hypothesis_id=hypothesis_id,
            test_id=test_id,
            parameters=parameters,
            reservation=prepared.get("reservation"),
        )
