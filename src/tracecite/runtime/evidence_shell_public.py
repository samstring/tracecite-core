"""Public Evidence Shell adapter over the artifact-free implementation.

The core implementation owns search execution and Evidence admission. This
adapter preserves two public contract details:

* scalar ``count`` can summarize an arbitrarily broad internal match set even
  when the Evidence-body budget is tiny, because it admits no Evidence body;
* repeated Evidence is projected as lightweight line-addressable pointers, not
  just opaque URIs, so callers can still reason about/query the matched range.
"""

from __future__ import annotations

import re
import shlex
from typing import Any, Mapping

from .evidence_shell import (
    DEFAULT_MAX_EVIDENCE_BYTES,
    DEFAULT_MAX_EVIDENCE_TOKENS,
    EvidenceShellPolicy,
    EvidenceShellRequest,
    run_evidence_shell as _run_evidence_shell,
)
from .retrieval_session import RetrievalSessionStore


_EVIDENCE_URI_RE = re.compile(
    r"^evidence://sha256/(?P<digest>[0-9a-fA-F]{64})"
    r"#L(?P<start>[1-9][0-9]*)(?:-L(?P<end>[1-9][0-9]*))?$"
)


def _terminal_command(program: str) -> str:
    lexer = shlex.shlex(str(program or ""), posix=True, punctuation_chars="|")
    lexer.whitespace_split = True
    lexer.commenters = ""
    groups: list[list[str]] = [[]]
    for token in lexer:
        if token == "|":
            if groups[-1]:
                groups.append([])
            continue
        groups[-1].append(token)
    commands = [group[0].lower() for group in groups if group]
    while commands and commands[-1] == "emit":
        commands.pop()
    return commands[-1] if commands else ""


def _policy_for_execution(
    request: EvidenceShellRequest,
    policy: EvidenceShellPolicy,
) -> EvidenceShellPolicy:
    # ``count`` returns one scalar and never admits Evidence bodies. Let the
    # Runtime scan the broad internal set even when the Evidence-body policy is
    # deliberately tiny. Group/distinct still use the normal transport guard
    # because their projection itself can become high-cardinality.
    if _terminal_command(request.program) != "count":
        return policy
    return EvidenceShellPolicy(
        max_evidence_tokens=max(policy.max_evidence_tokens, 1 << 30),
        max_evidence_bytes=max(policy.max_evidence_bytes, 1 << 30),
        source_mode=policy.source_mode,
        live_cut_timeout_seconds=policy.live_cut_timeout_seconds,
    )


def _budget_projection(policy: EvidenceShellPolicy) -> dict[str, Any]:
    return {
        "max_tokens": policy.max_evidence_tokens,
        "max_bytes": policy.max_evidence_bytes,
        "owner": "user_policy",
    }


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


def run_evidence_shell(
    request: EvidenceShellRequest,
    *,
    policy: EvidenceShellPolicy,
    session: RetrievalSessionStore | None = None,
) -> dict[str, Any]:
    execution_policy = _policy_for_execution(request, policy)
    payload = _run_evidence_shell(
        request,
        policy=execution_policy,
        session=session,
    )

    result = dict(payload)
    data = dict(result.get("data") or {})
    # Never leak an internally relaxed scalar-count policy as the user's real
    # configured Evidence policy.
    data["evidence_budget"] = _budget_projection(policy)

    repeated = data.get("matched_existing_evidence")
    if isinstance(repeated, list):
        data["matched_existing_evidence"] = [
            _pointer_from_uri(item)
            for item in repeated
            if isinstance(item, Mapping)
        ]
    result["data"] = data
    return result


__all__ = [
    "DEFAULT_MAX_EVIDENCE_BYTES",
    "DEFAULT_MAX_EVIDENCE_TOKENS",
    "EvidenceShellPolicy",
    "EvidenceShellRequest",
    "run_evidence_shell",
]
