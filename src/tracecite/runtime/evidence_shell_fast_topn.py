"""Bounded top-N fast path for Evidence Shell terminal sort/select programs.

This is a semantics-preserving execution optimization, not a new query surface.
It recognizes programs whose final work is ``sort ... | head/take/first N`` and
keeps only the best N rows while scanning instead of materializing and sorting
the entire matched set. SourceVersion, Segmenter, Evidence budgets, provenance
and RetrievalSession novelty remain owned by the canonical Runtime.
"""

from __future__ import annotations

import heapq
from pathlib import Path
from typing import Any, Callable, Iterable

from tracecite_core.segmenter import detect_segmenter_kind

from .evidence_shell import (
    _PREDICATES,
    _Stage,
    _apply_session,
    _budget_data,
    _budgeted,
    _field_value,
    _filter,
    _initial_rows,
    _simple_first_search,
    _too_broad,
    _tokenize_program,
)
from .evidence_shell_compat import normalize_evidence_shell_program
from .evidence_shell_public import (
    EvidenceShellPolicy,
    EvidenceShellRequest,
    _normalize_repeated,
    _pointers_fit,
)
from .retrieval_session import RetrievalSessionStore
from .schema import AgentResult, EvidencePointer
from .source_versions import SourceVersionStore


_HEAD_COMMANDS = {"head", "take", "first"}


def _sort_key(stage: _Stage) -> tuple[Callable[[Any], tuple[int, float | str]], bool] | None:
    if not stage.args:
        return None
    field = stage.args[0]
    direction = stage.args[1].lower() if len(stage.args) > 1 else "asc"
    numeric = len(stage.args) > 2 and stage.args[2].lower() == "numeric"
    if direction not in {"asc", "desc"}:
        return None
    if len(stage.args) > 2 and not numeric:
        return None
    if len(stage.args) > 3:
        return None

    def key(row: Any) -> tuple[int, float | str]:
        value = _field_value(row, field)
        if value is None:
            return (1, 0.0 if numeric else "")
        if numeric:
            try:
                return (0, float(str(value).strip()))
            except ValueError:
                return (1, 0.0)
        return (0, str(value))

    return key, direction == "desc"


def _terminal_topn(stages: list[_Stage]) -> tuple[list[_Stage], _Stage, int] | None:
    material = [stage for stage in stages if stage.command != "emit"]
    if len(material) < 2:
        return None
    sort_stage, select_stage = material[-2], material[-1]
    if sort_stage.command != "sort" or select_stage.command not in _HEAD_COMMANDS:
        return None
    if len(select_stage.args) != 1:
        return None
    try:
        n = int(select_stage.args[0])
    except ValueError:
        return None
    if n < 1 or _sort_key(sort_stage) is None:
        return None
    prefix = material[:-2]
    if any(stage.command not in _PREDICATES and stage.command != "all" for stage in prefix):
        return None
    return prefix, sort_stage, n


def _bounded_topn(rows: Iterable[Any], sort_stage: _Stage, n: int) -> list[Any]:
    parsed = _sort_key(sort_stage)
    if parsed is None:
        raise ValueError("invalid top-N sort stage")
    key, descending = parsed
    enumerated = enumerate(rows)
    if descending:
        selected = heapq.nlargest(
            n,
            enumerated,
            key=lambda pair: (key(pair[1]), -pair[0]),
        )
    else:
        selected = heapq.nsmallest(
            n,
            enumerated,
            key=lambda pair: (key(pair[1]), pair[0]),
        )
    return [row for _, row in selected]


def _request_with_program(request: EvidenceShellRequest, program: str) -> EvidenceShellRequest:
    if program == request.program:
        return request
    return EvidenceShellRequest(
        source=request.source,
        program=program,
        segmenter=request.segmenter,
        last=request.last,
        since=request.since,
        until=request.until,
        fold=request.fold,
    )


def _evidence_payload(
    *,
    request: EvidenceShellRequest,
    policy: EvidenceShellPolicy,
    session: RetrievalSessionStore | None,
    view: Any,
    kind: Any,
    selected: list[Any],
) -> dict[str, Any]:
    admitted, record_tokens, record_bytes, exceeded = _budgeted(selected, policy)
    if exceeded:
        return _too_broad(
            request=request,
            policy=policy,
            view=view,
            reason="MATCHED_EVIDENCE_BUDGET_EXCEEDED",
            tokens=record_tokens,
            bytes_used=record_bytes,
        )

    if not admitted:
        payload = AgentResult(
            operation="evidence_shell",
            status="no_match",
            outcome="not_assessed",
            coverage={
                "complete": False,
                "selection_explicit": True,
                "match_records": 0,
                "evidence_returned": 0,
                "evidence_tokens": 0,
                "evidence_bytes": 0,
                "too_broad": False,
            },
            data={
                "program": request.program,
                "segmenter": str(kind),
                "source_view": view.to_dict(),
                "source_version": view.key,
                "evidence_budget": _budget_data(policy),
                "execution_engine": "bounded_terminal_topn",
            },
        ).to_dict()
        return _normalize_repeated(
            _apply_session(
                payload,
                session=session,
                source_version=view.key,
                program=request.program,
            )
        )

    evidence: list[dict[str, Any]] = []
    for row in admitted:
        start = row.start_line or None
        end = row.end_line or start
        fragment = f"#L{start}" if start is not None else ""
        if start is not None and end is not None and end != start:
            fragment += f"-L{end}"
        label = next((line.strip() for line in row.text.splitlines() if line.strip()), "")[:240]
        evidence.append(
            EvidencePointer(
                uri=f"evidence://sha256/{row.sha256}{fragment}",
                source_path=row.source_path,
                sha256=row.sha256,
                start_line=start,
                end_line=end,
                timestamp=str(row.metadata.get("timestamp") or "") or None,
                label=label or None,
                metadata={
                    "shell_program": request.program,
                    "source_view": view.key,
                    "global_start_line": row.global_start_line,
                    "global_end_line": row.global_end_line,
                },
            ).to_dict()
        )

    pointers_fit, pointer_tokens, pointer_bytes = _pointers_fit(evidence, policy)
    if not pointers_fit:
        return _too_broad(
            request=request,
            policy=policy,
            view=view,
            reason="MATCHED_EVIDENCE_BUDGET_EXCEEDED",
            tokens=max(record_tokens, pointer_tokens),
            bytes_used=max(record_bytes, pointer_bytes),
        )

    payload = AgentResult(
        operation="evidence_shell",
        status="ok",
        outcome="not_assessed",
        evidence=evidence,
        coverage={
            "complete": False,
            "selection_explicit": True,
            "match_records": len(admitted),
            "evidence_returned": len(evidence),
            "evidence_tokens": record_tokens,
            "evidence_bytes": max(record_bytes, pointer_bytes),
            "record_tokens": record_tokens,
            "record_bytes": record_bytes,
            "pointer_tokens": pointer_tokens,
            "pointer_bytes": pointer_bytes,
            "too_broad": False,
        },
        data={
            "program": request.program,
            "segmenter": str(kind),
            "source_view": view.to_dict(),
            "source_version": view.key,
            "evidence_budget": _budget_data(policy),
            "execution_engine": "bounded_terminal_topn",
        },
    ).to_dict()
    return _normalize_repeated(
        _apply_session(
            payload,
            session=session,
            source_version=view.key,
            program=request.program,
        )
    )


def try_run_fast_topn(
    request: EvidenceShellRequest,
    *,
    policy: EvidenceShellPolicy,
    session: RetrievalSessionStore | None = None,
) -> dict[str, Any] | None:
    """Return a bounded top-N payload, or ``None`` for canonical fallback."""

    # The fast path must consume the same compatibility language as canonical
    # Evidence Shell. If compatibility normalization cannot represent a program,
    # leave it untouched for the canonical path to report the normal structured
    # result instead of letting an optimization steal parser semantics.
    try:
        normalized_program = normalize_evidence_shell_program(request.program)
        effective = _request_with_program(request, normalized_program)
        stages = _tokenize_program(effective.program)
    except ValueError:
        return None

    query, regex, remaining = _simple_first_search(stages)
    parsed = _terminal_topn(list(remaining))
    if parsed is None:
        return None
    prefix, sort_stage, n = parsed

    source = Path(effective.source).expanduser().resolve()
    if not source.is_file():
        return None
    kind = detect_segmenter_kind(source) if effective.segmenter == "auto" else effective.segmenter
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
    rows: Iterable[Any] = _initial_rows(
        view,
        query=query,
        regex=regex,
        kind=kind,
        request=effective,
    )
    for stage in prefix:
        if stage.command == "all":
            continue
        rows = _filter(rows, stage)
    selected = _bounded_topn(rows, sort_stage, n)
    return _evidence_payload(
        request=effective,
        policy=policy,
        session=session,
        view=view,
        kind=kind,
        selected=selected,
    )


__all__ = ["try_run_fast_topn"]
