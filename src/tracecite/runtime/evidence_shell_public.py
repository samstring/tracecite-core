"""Canonical public Evidence Shell execution.

This layer owns the final Agent transport gate. It reuses the artifact-free
parser/search helpers but admits nothing to RetrievalSession until both the
complete matched-record payload and the final EvidencePointer projection fit
the user/host Evidence policy.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

from tracecite_core.records import estimate_tokens
from tracecite_core.segmenter import detect_segmenter_kind

from .evidence_shell import (
    DEFAULT_MAX_EVIDENCE_BYTES,
    DEFAULT_MAX_EVIDENCE_TOKENS,
    EvidenceShellPolicy,
    EvidenceShellRequest,
    _aggregate,
    _apply_session,
    _budget_data,
    _budgeted,
    _execute_pipeline,
    _initial_rows,
    _payload_fits,
    _simple_first_search,
    _tokenize_program,
    _too_broad,
)
from .evidence_shell_compat import normalize_evidence_shell_program
from .retrieval_session import RetrievalSessionStore
from .schema import AgentResult, EvidencePointer
from .source_versions import SourceVersionStore


_EVIDENCE_URI_RE = re.compile(
    r"^evidence://sha256/(?P<digest>[0-9a-fA-F]{64})"
    r"#L(?P<start>[1-9][0-9]*)(?:-L(?P<end>[1-9][0-9]*))?$"
)


def _pointer_from_uri(item: Mapping[str, Any]) -> dict[str, Any]:
    row = dict(item)
    uri = str(row.get("uri") or "").strip()
    match = _EVIDENCE_URI_RE.fullmatch(uri)
    if match is None:
        return row
    start = int(match.group("start"))
    end = int(match.group("end") or match.group("start"))
    row.setdefault("sha256", match.group("digest").lower())
    row.setdefault("start_line", start)
    row.setdefault("end_line", end)
    return row


def _transport_size(value: Any) -> tuple[int, int]:
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    byte_count = len(text.encode("utf-8"))
    token_count = max(1, estimate_tokens(text)) if text else 0
    return token_count, byte_count


def _pointers_fit(
    evidence: list[dict[str, Any]],
    policy: EvidenceShellPolicy,
) -> tuple[bool, int, int]:
    """Bound pointer transport without charging pointer metadata as Evidence body tokens.

    ``max_evidence_tokens`` governs the matched record bodies selected by the
    Agent program. Pointer metadata is unavoidable transport overhead and is
    instead protected by the hard byte cap. This keeps tiny exact results usable
    under small body-token budgets while still preventing a high-cardinality
    locator list from recreating the old EvidenceIndex context explosion.
    """

    tokens, bytes_used = _transport_size({"evidence": evidence})
    return bytes_used <= policy.max_evidence_bytes, tokens, bytes_used


def _normalize_repeated(payload: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    data = dict(result.get("data") or {})
    repeated = data.get("matched_existing_evidence")
    if isinstance(repeated, list):
        data["matched_existing_evidence"] = [
            _pointer_from_uri(item)
            for item in repeated
            if isinstance(item, Mapping)
        ]
    result["data"] = data
    return result


def _normalized_request(request: EvidenceShellRequest) -> EvidenceShellRequest:
    normalized = normalize_evidence_shell_program(request.program)
    if normalized == request.program:
        return request
    return EvidenceShellRequest(
        source=request.source,
        program=normalized,
        segmenter=request.segmenter,
        last=request.last,
        since=request.since,
        until=request.until,
        fold=request.fold,
    )


def run_evidence_shell(
    request: EvidenceShellRequest,
    *,
    policy: EvidenceShellPolicy,
    session: RetrievalSessionStore | None = None,
) -> dict[str, Any]:
    """Execute one safe search program under a fixed user/host Evidence budget."""

    if not isinstance(request, EvidenceShellRequest):
        raise TypeError("run_evidence_shell requires EvidenceShellRequest")
    if not isinstance(policy, EvidenceShellPolicy):
        raise TypeError("policy must be EvidenceShellPolicy")
    request = _normalized_request(request)
    if request.fold:
        raise ValueError(
            "fold is not part of artifact-free Evidence Shell; use group/distinct explicitly"
        )

    source = Path(request.source).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)

    stages = _tokenize_program(request.program)
    query, regex, remaining = _simple_first_search(stages)
    kind = detect_segmenter_kind(source) if request.segmenter == "auto" else request.segmenter

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

    rows = _initial_rows(
        view,
        query=query,
        regex=regex,
        kind=kind,
        request=request,
    )
    final_rows, aggregate, matched, selected_subset = _execute_pipeline(rows, remaining)

    if aggregate is not None:
        # Count is a single scalar and admits no Evidence body. It may summarize
        # an arbitrarily broad Runtime-internal set even when the Evidence body
        # budget is tiny. Group/distinct remain transport-gated because their
        # own projection can become high-cardinality.
        if "count" not in aggregate:
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
            },
        ).to_dict()

    assert final_rows is not None
    selected, record_tokens, record_bytes, exceeded = _budgeted(final_rows, policy)
    if exceeded:
        return _too_broad(
            request=request,
            policy=policy,
            view=view,
            reason="MATCHED_EVIDENCE_BUDGET_EXCEEDED",
            tokens=record_tokens,
            bytes_used=record_bytes,
        )

    if not selected:
        payload = AgentResult(
            operation="evidence_shell",
            status="no_match",
            outcome="not_assessed",
            coverage={
                "complete": not selected_subset,
                "selection_explicit": selected_subset,
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
    for row in selected:
        start = row.start_line or None
        end = row.end_line or start
        fragment = f"#L{start}" if start is not None else ""
        if start is not None and end is not None and end != start:
            fragment += f"-L{end}"
        label = next(
            (line.strip() for line in row.text.splitlines() if line.strip()),
            "",
        )[:240]
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
            "complete": not selected_subset,
            "selection_explicit": selected_subset,
            "match_records": len(selected),
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


__all__ = [
    "DEFAULT_MAX_EVIDENCE_BYTES",
    "DEFAULT_MAX_EVIDENCE_TOKENS",
    "EvidenceShellPolicy",
    "EvidenceShellRequest",
    "run_evidence_shell",
]
