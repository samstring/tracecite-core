"""Public adaptive retrieve contract over the canonical Agent API.

The low-level Agent API remains deterministic and target-specific. This wrapper
owns product retrieval semantics:

1. adaptive DIRECT -> BOUNDED -> INVESTIGATE transport;
2. fidelity-first DIRECT raw access for small unseen sources;
3. bounded structured-context recovery for search results;
4. mechanical evidence-integrity observations and actionable evidence gaps;
5. bounded high-signal navigation for truncated searches.

Runtime owns retrieval/materialization/integrity. Integration projections must
not reopen source files or discover new Evidence. None of these mechanisms may
infer or rank a root cause.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

from tracecite_core.run import RunIntegrityError

from . import tools as _tools
from .agent_api import (
    EvidenceRequest,
    ProviderTarget,
    QueryTarget,
    RangeTarget,
    RetrievalResult,
    SourceTarget,
    _observe_tool_result,
    _restore_progress,
    _sha256,
    retrieve as _retrieve,
)
from .evidence_ambiguity import scoped_identity_fanout_hints, verify_scoped_identity_gaps
from .evidence_fidelity import enrich_search_leaf_context
from .evidence_identity import file_source_version
from .evidence_routing import (
    EvidenceRoute,
    EvidenceRoutingPolicy,
    RoutingDecision,
    decide_route,
    refine_route_after_result,
)
from .evidence_selection import select_signal_hints
from .investigation import InvestigationStore


_TRANSPORT_ONLY_OPERATIONS = frozenset({"probe", "sample", "search", "expand", "survey", "retrieve"})
_BOUNDED_SOURCE_SAMPLE_RECORDS = 64
_BOUNDED_SOURCE_SAMPLE_CHARS = 12_000


def _history(request: EvidenceRequest) -> tuple[Mapping[str, object], ...]:
    if request.investigation_path is None:
        return ()
    return tuple(InvestigationStore(request.investigation_path).load().executions)


def _decision(request: EvidenceRequest, policy: EvidenceRoutingPolicy) -> RoutingDecision:
    target = request.target
    source: Path | None = None
    kind = "provider"
    if isinstance(target, SourceTarget):
        kind = "source"
        source = Path(target.source).expanduser().resolve()
    elif isinstance(target, QueryTarget):
        kind = "query"
        source = Path(target.source).expanduser().resolve()
    elif isinstance(target, RangeTarget):
        kind = "range"
        source = Path(target.source).expanduser().resolve()
    elif isinstance(target, ProviderTarget):
        kind = "provider"
    return decide_route(
        target_kind=kind,
        source=source,
        policy=policy,
        executions=_history(request),
    )


def _with_routing(result: RetrievalResult, decision: RoutingDecision) -> RetrievalResult:
    canonical = dict(result.canonical_result)
    if result.operation in _TRANSPORT_ONLY_OPERATIONS:
        # Retrieval success means evidence was matched/materialized, not that a
        # hypothesis was epistemically supported. Proposition-level APIs own
        # supported/contradicted outcomes.
        canonical["outcome"] = "not_assessed"
    data = dict(canonical.get("data") or {})
    data["routing"] = decision.to_dict()
    canonical["data"] = data
    return RetrievalResult(
        operation=result.operation,
        status=result.status,
        canonical_result=canonical,
        progress=result.progress,
        new_evidence=result.new_evidence,
        repeated_evidence=result.repeated_evidence,
        acquisition_end_reason=result.acquisition_end_reason,
    )


def _replace_canonical(
    result: RetrievalResult,
    canonical: Mapping[str, Any],
    *,
    new_evidence: tuple[Mapping[str, Any], ...] | None = None,
) -> RetrievalResult:
    return RetrievalResult(
        operation=result.operation,
        status=result.status,
        canonical_result=canonical,
        progress=result.progress,
        new_evidence=result.new_evidence if new_evidence is None else new_evidence,
        repeated_evidence=result.repeated_evidence,
        acquisition_end_reason=result.acquisition_end_reason,
    )


def _with_actionable_gap_progress(result: RetrievalResult) -> RetrievalResult:
    """Expose the number of actionable evidence gaps without judging sufficiency."""

    gaps = [
        item
        for item in result.canonical_result.get("missing_evidence") or []
        if isinstance(item, Mapping) and item.get("actionable") is True
    ]
    if not gaps or result.progress.actionable_gaps >= len(gaps):
        return result

    progress = replace(result.progress, actionable_gaps=len(gaps))
    return RetrievalResult(
        operation=result.operation,
        status=result.status,
        canonical_result=result.canonical_result,
        progress=progress,
        new_evidence=result.new_evidence,
        repeated_evidence=result.repeated_evidence,
        acquisition_end_reason=result.acquisition_end_reason,
    )


def _bounded_decision(decision: RoutingDecision, reason: str) -> RoutingDecision:
    return RoutingDecision(
        route=EvidenceRoute.BOUNDED,
        reasons=(*decision.reasons, reason),
        source_bytes=decision.source_bytes,
        estimated_direct_chars=decision.estimated_direct_chars,
        aggregate_direct_chars=decision.aggregate_direct_chars,
        direct_char_budget=decision.direct_char_budget,
        previous_executions=decision.previous_executions,
        source_count=decision.source_count,
        max_match_records=decision.max_match_records,
        repeated_evidence_ratio=decision.repeated_evidence_ratio,
        next_route=decision.next_route,
    )


def _line_count(path: Path) -> int:
    count = 0
    last = b""
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(64 * 1024), b""):
            count += block.count(b"\n")
            last = block[-1:]
    if path.stat().st_size and last != b"\n":
        count += 1
    return count


def _direct_source(
    request: EvidenceRequest,
    decision: RoutingDecision,
    policy: EvidenceRoutingPolicy,
) -> RetrievalResult:
    assert isinstance(request.target, SourceTarget)
    target = request.target
    path = Path(target.source).expanduser().resolve()
    if not path.is_file() or path.stat().st_size == 0:
        return _with_routing(_retrieve(request), decision)

    tracker = _restore_progress(request.investigation_path)
    digest = _sha256(path)
    lines = _line_count(path)
    if lines < 1:
        return _with_routing(_retrieve(request), decision)
    result = _tools.expand(
        path,
        1,
        end_line=lines,
        before=0,
        after=0,
        expected_sha256=digest,
        max_chars=policy.direct_char_budget,
        investigation_path=request.investigation_path,
        hypothesis_id=request.hypothesis_id,
        test_id=request.test_id,
        cache=request.cache,
    )
    source_key = file_source_version(str(path), digest).key
    readiness, new_rows, repeated = _observe_tool_result(
        tracker,
        result,
        source_key=source_key,
        range_from_coverage=True,
    )
    resolved = RetrievalResult(
        operation="expand",
        status=str(result.get("status") or "unknown"),
        canonical_result=result,
        progress=readiness,
        new_evidence=new_rows,
        repeated_evidence=repeated,
    )
    coverage = result.get("coverage") or {}
    if isinstance(coverage, Mapping) and bool(coverage.get("truncated")):
        decision = _bounded_decision(decision, "direct_render_exceeded_budget")
    return _with_routing(resolved, decision)


def _qualify_raw_rows(rows: list[str], source_name: str) -> str:
    qualified: list[str] = []
    for row in rows:
        line, sep, text = row.partition(": ")
        if sep and line.isdigit():
            qualified.append(f"{source_name}:{line} {text}")
        else:
            qualified.append(row)
    return "".join(qualified)


def _direct_query(
    request: EvidenceRequest,
    decision: RoutingDecision,
    policy: EvidenceRoutingPolicy,
) -> RetrievalResult:
    """Preserve exact source context for a safe one-time DIRECT query."""

    assert isinstance(request.target, QueryTarget)
    path = Path(request.target.source).expanduser().resolve()
    result = _retrieve(request)
    if result.canonical_result.get("status") == "error" or not path.is_file():
        return _with_routing(result, decision)

    canonical = dict(result.canonical_result)
    data = dict(canonical.get("data") or {})
    expected = str(data.get("source_sha256") or "").strip().lower()
    lines = _line_count(path)
    if lines < 1:
        return _with_routing(result, decision)
    try:
        digest, rows, last_seen = _tools._read_hashed_context(
            path,
            context_start=1,
            context_end=lines,
        )
    except (OSError, ValueError, RunIntegrityError):
        return _with_routing(result, _bounded_decision(decision, "direct_raw_read_unavailable"))
    if expected and digest.lower() != expected:
        return _with_routing(result, _bounded_decision(decision, "source_changed_after_search"))

    text = _qualify_raw_rows(rows, path.name)
    if len(text) > policy.direct_char_budget:
        return _with_routing(result, _bounded_decision(decision, "direct_raw_exceeded_budget"))

    data["text"] = text
    data["direct_raw"] = {
        "fidelity": "lossless_line_addressable",
        "source": path.name,
        "sha256": digest,
    }
    canonical["data"] = data
    coverage = dict(canonical.get("coverage") or {})
    coverage["direct_raw_lines"] = last_seen
    coverage["direct_raw_chars"] = len(text)
    canonical["coverage"] = coverage
    resolved = _replace_canonical(result, canonical)
    decision = refine_route_after_result(decision, canonical, policy=policy)
    return _with_routing(resolved, decision)


def _bounded_source(
    request: EvidenceRequest,
    decision: RoutingDecision,
) -> RetrievalResult:
    """Return deterministic representative context for a bounded source inspection.

    A metadata-only probe leaves the Agent blind on sources just above the
    direct-context budget. Uniform bounded sampling exposes source structure and
    navigation landmarks without diagnosing, ranking, or dumping the source.
    ``snapshot=False`` keeps this a cheap navigation observation; exact evidence
    remains recoverable through RangeTarget materialization.
    """

    assert isinstance(request.target, SourceTarget)
    target = request.target
    path = Path(target.source).expanduser().resolve()
    if not path.is_file() or path.stat().st_size == 0:
        return _with_routing(_retrieve(request), decision)

    tracker = _restore_progress(request.investigation_path)
    result = _tools.sample(
        path,
        strategy="uniform",
        count=_BOUNDED_SOURCE_SAMPLE_RECORDS,
        max_chars=_BOUNDED_SOURCE_SAMPLE_CHARS,
        snapshot=False,
        segmenter=target.segmenter,
        investigation_path=request.investigation_path,
        hypothesis_id=request.hypothesis_id,
        test_id=request.test_id,
        cache=request.cache,
    )
    readiness, new_rows, repeated = _observe_tool_result(tracker, result)
    canonical = dict(result)
    data = dict(canonical.get("data") or {})
    data["navigation_only"] = True
    data["navigation_note"] = (
        "Uniform bounded source samples are navigation landmarks only; materialize "
        "the relevant line range before treating it as cited Evidence."
    )
    canonical["data"] = data
    resolved = RetrievalResult(
        operation="sample",
        status=str(canonical.get("status") or "unknown"),
        canonical_result=canonical,
        progress=readiness,
        new_evidence=new_rows,
        repeated_evidence=repeated,
    )
    return _with_routing(resolved, decision)


def _investigate_source(
    request: EvidenceRequest,
    decision: RoutingDecision,
    policy: EvidenceRoutingPolicy,
) -> RetrievalResult:
    """Use bounded descriptive survey for a large/deep local source."""

    assert isinstance(request.target, SourceTarget)
    target = request.target
    tracker = _restore_progress(request.investigation_path)
    result = _tools.survey(
        target.source,
        snapshot=True,
        segmenter=target.segmenter,
        max_templates=policy.survey_max_templates,
        samples_per_template=policy.survey_samples_per_template,
        investigation_path=request.investigation_path,
        hypothesis_id=request.hypothesis_id,
        test_id=request.test_id,
        cache=request.cache,
    )
    readiness, new_rows, repeated = _observe_tool_result(tracker, result)
    resolved = RetrievalResult(
        operation="survey",
        status=str(result.get("status") or "unknown"),
        canonical_result=result,
        progress=readiness,
        new_evidence=new_rows,
        repeated_evidence=repeated,
    )
    return _with_routing(resolved, decision)


def _bounded_query(
    request: EvidenceRequest,
    policy: EvidenceRoutingPolicy,
    *,
    route: EvidenceRoute,
) -> EvidenceRequest:
    assert isinstance(request.target, QueryTarget)
    target = request.target
    if route == EvidenceRoute.FOCUSED:
        evidence_cap = policy.focused_max_evidence
        line_cap = policy.focused_max_line_chars
    else:
        evidence_cap = policy.bounded_max_evidence
        line_cap = policy.bounded_max_line_chars
    max_evidence = evidence_cap if target.max_evidence is None else min(target.max_evidence, evidence_cap)
    max_line_chars = line_cap if target.max_line_chars is None else min(target.max_line_chars, line_cap)
    return EvidenceRequest(
        QueryTarget(
            target.source,
            target.query,
            regex=target.regex,
            snapshot=target.snapshot,
            segmenter=target.segmenter,
            last=target.last,
            since=target.since,
            until=target.until,
            fold=target.fold,
            max_evidence=max_evidence,
            max_line_chars=max_line_chars,
        ),
        investigation_path=request.investigation_path,
        hypothesis_id=request.hypothesis_id,
        test_id=request.test_id,
        cache=request.cache,
        providers=request.providers,
    )


def _matched_records_path(result: Mapping[str, object]) -> Path | None:
    for item in result.get("artifacts") or []:
        if not isinstance(item, Mapping) or item.get("role") != "matched_records":
            continue
        value = str(item.get("path") or "").strip()
        if value:
            return Path(value)
    return None


def _attach_search_fidelity(
    result: RetrievalResult,
    request: EvidenceRequest,
) -> RetrievalResult:
    """Materialize tiny structured neighborhoods inside canonical search output."""

    if not isinstance(request.target, QueryTarget):
        return result
    if str(result.canonical_result.get("status") or "").lower() in {"error", "no_match"}:
        return result
    enriched = enrich_search_leaf_context(result.canonical_result)
    if enriched == result.canonical_result:
        return result

    enriched_by_uri = {
        str(item.get("uri") or ""): dict(item)
        for item in enriched.get("evidence") or []
        if isinstance(item, Mapping) and item.get("uri")
    }
    new_rows: list[Mapping[str, Any]] = []
    for item in result.new_evidence:
        uri = str(item.get("uri") or "")
        new_rows.append(enriched_by_uri.get(uri, dict(item)))
    resolved = _replace_canonical(result, enriched, new_evidence=tuple(new_rows))
    return _with_actionable_gap_progress(resolved)


def _attach_signal_hints(
    result: RetrievalResult,
    request: EvidenceRequest,
    policy: EvidenceRoutingPolicy,
) -> RetrievalResult:
    """Attach bounded high-signal navigation hints to a truncated search.

    Hints stay out of Evidence/new_evidence. They are line-addressable
    candidates only; callers must materialize the referenced range before
    treating them as covered Evidence.
    """

    if not isinstance(request.target, QueryTarget):
        return result
    canonical = dict(result.canonical_result)
    coverage = dict(canonical.get("coverage") or {})
    if not bool(coverage.get("evidence_truncated")):
        return result
    records_path = _matched_records_path(canonical)
    if records_path is None:
        return result
    try:
        hints = select_signal_hints(
            records_path,
            limit=policy.signal_hint_limit,
            signature_cap=policy.signal_signature_cap,
        )
    except (OSError, ValueError):
        return result
    if not hints:
        return result

    inline_ranges: list[tuple[int, int]] = []
    for item in canonical.get("evidence") or []:
        if not isinstance(item, Mapping):
            continue
        start = item.get("start_line")
        end = item.get("end_line")
        if not isinstance(start, int) or isinstance(start, bool):
            continue
        if not isinstance(end, int) or isinstance(end, bool):
            end = start
        inline_ranges.append((start, max(start, end)))

    source_name = Path(request.target.source).name
    retained = []
    for hint in hints:
        line = int(hint["line"])
        if any(start <= line <= end for start, end in inline_ranges):
            continue
        retained.append(
            {
                "ref": f"{source_name}:{line}",
                "line": line,
                "end_line": int(hint.get("end_line") or line),
                "severity": int(hint["severity"]),
                "count": int(hint["count"]),
                "label": str(hint["label"]),
            }
        )
    if not retained:
        return result

    data = dict(canonical.get("data") or {})
    data["signal_hints"] = retained
    data["signal_hint_note"] = (
        "Truncated-search high-signal candidates; materialize the referenced line before citing."
    )
    canonical["data"] = data
    coverage["signal_hints_returned"] = len(retained)
    canonical["coverage"] = coverage
    return _replace_canonical(result, canonical)


def _correct_range_novelty(result: RetrievalResult, request: EvidenceRequest) -> RetrievalResult:
    if not isinstance(request.target, RangeTarget):
        return result
    if result.status != "no_new_evidence" or result.progress.delta.new_lines <= 0:
        return result

    canonical_evidence = tuple(
        dict(item)
        for item in result.canonical_result.get("evidence") or []
        if isinstance(item, Mapping)
    )
    status = str(result.canonical_result.get("status") or "ok")
    if status == "error":
        return result
    return RetrievalResult(
        operation=result.operation,
        status=status,
        canonical_result=result.canonical_result,
        progress=result.progress,
        new_evidence=canonical_evidence,
        repeated_evidence=result.repeated_evidence,
        acquisition_end_reason=result.acquisition_end_reason,
    )


def _append_gap(
    canonical: dict[str, Any],
    *,
    identifier_key: str,
    identifier_value: str,
    source: str,
) -> None:
    rows = [
        dict(item)
        for item in canonical.get("missing_evidence") or []
        if isinstance(item, Mapping)
    ]
    identity = ("scope_uniqueness_unverified", identifier_key, identifier_value, source)
    for item in rows:
        current = (
            str(item.get("kind") or ""),
            str(item.get("identifier_key") or ""),
            str(item.get("identifier_value") or ""),
            str(item.get("source") or ""),
        )
        if current == identity:
            return
    rows.append(
        {
            "kind": "scope_uniqueness_unverified",
            "detail": (
                f"{identifier_key}={identifier_value} is visible inside a scoped entity, "
                "but uniqueness across the relevant identity domain remains unverified."
            ),
            "actionable": True,
            "identifier_key": identifier_key,
            "identifier_value": identifier_value,
            "source": source,
            "recommended_action": {
                "operation": "search",
                "query": identifier_value,
                "purpose": "verify_identifier_uniqueness_across_scopes",
            },
        }
    )
    canonical["missing_evidence"] = rows
    next_queries = [str(item) for item in canonical.get("next_queries") or [] if str(item).strip()]
    if identifier_value not in next_queries:
        next_queries.append(identifier_value)
    canonical["next_queries"] = next_queries


def _attach_identity_verification(
    result: RetrievalResult,
    request: EvidenceRequest,
) -> RetrievalResult:
    """Attach canonical scoped-ID integrity observations to a Range retrieval."""

    if not isinstance(request.target, RangeTarget):
        return result
    canonical = dict(result.canonical_result)
    if str(canonical.get("status") or "").lower() == "error":
        return result
    data = dict(canonical.get("data") or {})
    text = data.get("text")
    if not isinstance(text, str) or not text:
        return result

    hints = scoped_identity_fanout_hints(text)
    expected = str(request.target.expected_sha256 or "").strip().lower()
    if not expected:
        for item in canonical.get("evidence") or []:
            if not isinstance(item, Mapping):
                continue
            candidate = str(item.get("sha256") or "").strip().lower()
            if candidate:
                expected = candidate
                break
    try:
        verification = verify_scoped_identity_gaps(
            request.target.source,
            text,
            expected_sha256=expected or None,
        )
    except (OSError, ValueError):
        verification = []
    if not hints and not verification:
        return result

    source_name = Path(request.target.source).name
    integrity = dict(data.get("evidence_integrity") or {})
    integrity["scoped_identity"] = [
        {
            "source": source_name,
            "scoped_identity_hints": hints,
            "identity_verification": verification,
        }
    ]
    integrity["note"] = (
        "Evidence-integrity navigation only. Scoped identity observations constrain "
        "correlation; they do not identify a root cause."
    )
    data["evidence_integrity"] = integrity
    canonical["data"] = data

    verified_keys: set[tuple[str, str]] = set()
    for item in verification:
        key = str(item.get("identifier_key") or "").strip()
        value = str(item.get("identifier_value") or "").strip()
        if not key or not value:
            continue
        verified_keys.add((key.lower(), value))
        if str(item.get("status") or "") != "multiple_scoped_entities_observed":
            _append_gap(
                canonical,
                identifier_key=key,
                identifier_value=value,
                source=source_name,
            )

    for hint in hints:
        if hint.get("kind") != "scope_uniqueness_unverified":
            continue
        key = str(hint.get("identifier_key") or "").strip()
        value = str(hint.get("identifier_value") or "").strip()
        if not key or not value or (key.lower(), value) in verified_keys:
            continue
        _append_gap(
            canonical,
            identifier_key=key,
            identifier_value=value,
            source=source_name,
        )

    resolved = _replace_canonical(result, canonical)
    return _with_actionable_gap_progress(resolved)


def retrieve(
    request: EvidenceRequest,
    *,
    routing_policy: EvidenceRoutingPolicy | None = None,
) -> RetrievalResult:
    """Execute the stable retrieval contract with adaptive transport routing."""

    if not isinstance(request, EvidenceRequest):
        raise TypeError("retrieve requires EvidenceRequest")
    policy = routing_policy or EvidenceRoutingPolicy()
    if not isinstance(policy, EvidenceRoutingPolicy):
        raise TypeError("routing_policy must be EvidenceRoutingPolicy")
    decision = _decision(request, policy)

    if isinstance(request.target, SourceTarget):
        if decision.route == EvidenceRoute.DIRECT:
            return _direct_source(request, decision, policy)
        if decision.route == EvidenceRoute.FOCUSED:
            return _investigate_source(request, decision, policy)
        return _bounded_source(request, decision)

    if isinstance(request.target, QueryTarget) and decision.route == EvidenceRoute.DIRECT:
        return _direct_query(request, decision, policy)

    routed_request = request
    if isinstance(request.target, QueryTarget):
        routed_request = _bounded_query(request, policy, route=decision.route)
    result = _correct_range_novelty(_retrieve(routed_request), routed_request)
    result = _attach_search_fidelity(result, routed_request)
    result = _attach_identity_verification(result, routed_request)
    result = _attach_signal_hints(result, routed_request, policy)
    decision = refine_route_after_result(decision, result.canonical_result, policy=policy)
    return _with_routing(result, decision)


__all__ = ["retrieve"]
