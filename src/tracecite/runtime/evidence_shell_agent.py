"""Agent-facing Evidence Shell contract.

The canonical Runtime remains responsible for SourceVersion, Record recovery,
Evidence budgets and RetrievalSession novelty.  This thin layer improves the
Agent transport contract only: familiar pipeline rewrites, structured program
errors, and compact receipts for Evidence already seen in the same session.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from .evidence_shell_agent_compat import normalize_agent_evidence_shell_program
from .evidence_shell_public import (
    DEFAULT_MAX_EVIDENCE_BYTES,
    DEFAULT_MAX_EVIDENCE_TOKENS,
    EvidenceShellPolicy,
    EvidenceShellRequest,
    run_evidence_shell as _run_evidence_shell,
)
from .retrieval_session import RetrievalSessionStore
from .schema import AgentResult


_EVIDENCE_URI_RE = re.compile(
    r"^evidence://sha256/(?P<digest>[0-9a-fA-F]{64})"
    r"#L(?P<start>[1-9][0-9]*)(?:-L(?P<end>[1-9][0-9]*))?$"
)


def _program_error(request: EvidenceShellRequest, exc: ValueError) -> dict[str, Any]:
    message = str(exc).strip() or "unsupported Evidence Shell program"
    payload = AgentResult(
        operation="evidence_shell",
        status="error",
        outcome="unknown",
        evidence=[],
        warnings=[
            "The requested read-only Evidence Shell program could not be normalized or executed. "
            "Rewrite only the unsupported stage; do not switch to native shell access for a TraceCite-only source."
        ],
        coverage={"complete": False, "evidence_returned": 0},
        data={
            "program": request.program,
            "supported_hint": (
                "Use search/regex/where, sort before project, count/group/distinct, "
                "or an explicit head/tail selection."
            ),
        },
    ).to_dict()
    payload["error_code"] = "unsupported_program"
    payload["error"] = message
    return payload


def _pointer_receipt(item: Mapping[str, Any], source: str) -> dict[str, Any]:
    uri = str(item.get("uri") or "").strip()
    row: dict[str, Any] = {"uri": uri} if uri else {}
    start = item.get("start_line")
    end = item.get("end_line")
    sha = str(item.get("sha256") or "").strip()
    if uri:
        match = _EVIDENCE_URI_RE.fullmatch(uri)
        if match is not None:
            if not sha:
                sha = match.group("digest").lower()
            if not isinstance(start, int) or isinstance(start, bool):
                start = int(match.group("start"))
            if not isinstance(end, int) or isinstance(end, bool):
                end = int(match.group("end") or match.group("start"))
    if sha:
        row["sha256"] = sha
    if isinstance(start, int) and not isinstance(start, bool) and start > 0:
        row["start_line"] = start
        if not isinstance(end, int) or isinstance(end, bool) or end < start:
            end = start
        row["end_line"] = end
    row["source"] = source
    return row


def _representatives(rows: list[Mapping[str, Any]], source: str) -> list[dict[str, Any]]:
    if not rows:
        return []
    selected = [rows[0]]
    if len(rows) > 1:
        selected.append(rows[-1])
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in selected:
        receipt = _pointer_receipt(item, source)
        key = str(receipt.get("uri") or receipt)
        if key in seen:
            continue
        seen.add(key)
        result.append(receipt)
    return result


def _compact_repeated_evidence(
    payload: Mapping[str, Any],
    *,
    request: EvidenceShellRequest,
    session: RetrievalSessionStore | None,
    requested_program: str,
) -> dict[str, Any]:
    result = dict(payload)
    data = dict(result.get("data") or {})
    repeated_raw = data.pop("matched_existing_evidence", None)
    repeated = [item for item in repeated_raw or [] if isinstance(item, Mapping)]

    novelty_raw = data.get("novelty")
    novelty = dict(novelty_raw) if isinstance(novelty_raw, Mapping) else {}
    new_count = int(novelty.get("new_evidence") or 0)
    repeated_count = int(novelty.get("repeated_evidence") or len(repeated))
    if novelty:
        novelty["matched_evidence"] = new_count + repeated_count
        if session is not None:
            state = session.load()
            if state.recent_operations:
                latest = state.recent_operations[-1]
                if latest.operation == "evidence_shell":
                    novelty["query_repeated"] = bool(latest.exact_duplicate_request)
        if novelty.get("state") == "no_new_evidence":
            novelty["guidance"] = (
                "This query produced no Evidence identity not already seen in this RetrievalSession. "
                "Do not repeat the same query; change investigation direction, use a compact aggregate, "
                "or conclude at the evidence boundary if the remaining mechanism is not observable."
            )
        data["novelty"] = novelty

    if repeated_count:
        data["existing_evidence_summary"] = {
            "count": repeated_count,
            "all_matches_previously_seen": bool(new_count == 0),
            "representative": _representatives(repeated, str(request.source)),
            "replay_hint": (
                "Previously seen Evidence remains recoverable with tracecite_materialize/tracecite_replay "
                "using its source, line range and SHA when another look is actually needed."
            ),
        }

    normalized_program = str(data.get("program") or request.program)
    if requested_program != normalized_program:
        data["requested_program"] = requested_program
        data["normalized_program"] = normalized_program
    result["data"] = data
    return result


def run_evidence_shell(
    request: EvidenceShellRequest,
    *,
    policy: EvidenceShellPolicy,
    session: RetrievalSessionStore | None = None,
) -> dict[str, Any]:
    """Execute Evidence Shell with compact, actionable Agent-facing feedback."""

    if not isinstance(request, EvidenceShellRequest):
        raise TypeError("run_evidence_shell requires EvidenceShellRequest")
    if not isinstance(policy, EvidenceShellPolicy):
        raise TypeError("policy must be EvidenceShellPolicy")

    requested_program = request.program
    try:
        preprocessed = normalize_agent_evidence_shell_program(request.program)
        prepared = request
        if preprocessed != request.program:
            prepared = EvidenceShellRequest(
                source=request.source,
                program=preprocessed,
                segmenter=request.segmenter,
                last=request.last,
                since=request.since,
                until=request.until,
                fold=request.fold,
            )
        payload = _run_evidence_shell(prepared, policy=policy, session=session)
    except ValueError as exc:
        return _program_error(request, exc)

    return _compact_repeated_evidence(
        payload,
        request=request,
        session=session,
        requested_program=requested_program,
    )


__all__ = [
    "DEFAULT_MAX_EVIDENCE_BYTES",
    "DEFAULT_MAX_EVIDENCE_TOKENS",
    "EvidenceShellPolicy",
    "EvidenceShellRequest",
    "run_evidence_shell",
]
