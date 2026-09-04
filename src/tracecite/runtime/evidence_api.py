"""Canonical Agent-facing Evidence Runtime operations.

Text QueryTarget retrieval now reduces to the same artifact-free Evidence Shell
contract used by ``tracecite_run``. Large match sets never become EvidenceIndex
locator dumps: they either fit user policy in full or return ``too_broad``.
"""

from __future__ import annotations

import hashlib
import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Mapping

from tracecite_core.state_file import state_lock

from .agent_api import EvidenceRequest, QueryTarget, RangeTarget, RetrievalResult
from .evidence_identity import file_source_version
from .evidence_progress import EvidenceProgressTracker
from .evidence_routing import EvidenceRoutingPolicy
from .evidence_shell import EvidenceShellPolicy, EvidenceShellRequest, run_evidence_shell
from .provider_identity import namespace_provider_request
from .relationship_frontier import attach_relationship_frontier
from .retrieval_guidance import prioritize_actionable_retrieval
from .retrieval_session import RetrievalOperation, RetrievalSessionState, RetrievalSessionStore
from .retrieve_contract import retrieve as _retrieve_contract
from .session_retrieval import retrieve_with_session
from .source_version_lookup import managed_segment_sha
from .schema import AgentResult, EvidencePointer
from .acquisition import verify


AggregateOperation = Literal["count", "distinct", "group"]


@dataclass(frozen=True)
class AggregateRequest:
    """Mechanical aggregation over caller-selected local text evidence."""

    source: str | Path
    query: str
    regex: bool = False
    operation: AggregateOperation = "count"
    group_regex: str | None = None
    max_groups: int = 100

    def __post_init__(self) -> None:
        if not str(self.query or ""):
            raise ValueError("aggregate query must be non-empty")
        if self.operation not in {"count", "distinct", "group"}:
            raise ValueError("aggregate operation must be count/distinct/group")
        if isinstance(self.max_groups, bool) or not isinstance(self.max_groups, int) or self.max_groups < 1:
            raise ValueError("max_groups must be a positive integer")
        if self.operation == "group" and not str(self.group_regex or ""):
            raise ValueError("group operation requires group_regex")
        if self.regex:
            re.compile(self.query)
        if self.group_regex:
            re.compile(self.group_regex)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _tracker(state: RetrievalSessionState | None = None) -> EvidenceProgressTracker:
    tracker = EvidenceProgressTracker()
    if state is None:
        return tracker
    tracker.restore(evidence_ids=state.seen_evidence)
    for source, ranges in state.covered_ranges.items():
        tracker.restore(source=source, line_ranges=ranges)
    return tracker


def _pointer_ids(rows: list[Mapping[str, Any]]) -> tuple[str, ...]:
    return tuple(
        str(item.get("uri") or "").strip()
        for item in rows
        if str(item.get("uri") or "").strip()
    )


def _query_via_shell(
    request: EvidenceRequest,
    *,
    session: RetrievalSessionStore | None,
) -> RetrievalResult:
    target = request.target
    assert isinstance(target, QueryTarget)
    before = session.load() if session is not None else None
    program = (
        f"regex {shlex.quote(target.query)}"
        if target.regex
        else f"search {shlex.quote(target.query)}"
    )
    payload = run_evidence_shell(
        EvidenceShellRequest(
            source=target.source,
            program=program,
            segmenter=target.segmenter,
            last=target.last,
            since=target.since,
            until=target.until,
            fold=target.fold,
        ),
        policy=EvidenceShellPolicy(),
        session=session,
    )
    rows = [
        dict(item)
        for item in payload.get("evidence") or []
        if isinstance(item, Mapping)
    ]
    tracker = _tracker(before)
    progress = tracker.observe(evidence_ids=_pointer_ids(rows))
    coverage = payload.get("coverage") or {}
    repeated = (
        int(coverage.get("repeated_evidence") or 0)
        if isinstance(coverage, Mapping)
        else 0
    )
    return RetrievalResult(
        operation="search",
        status=str(payload.get("status") or "unknown"),
        canonical_result=payload,
        progress=progress,
        new_evidence=tuple(rows),
        repeated_evidence=max(0, repeated),
    )


def retrieve(
    request: EvidenceRequest,
    *,
    session: RetrievalSessionStore | None = None,
    routing_policy: EvidenceRoutingPolicy | None = None,
) -> RetrievalResult:
    """Retrieve caller-selected evidence under canonical SourceVersion semantics."""

    if not isinstance(request, EvidenceRequest):
        raise TypeError("retrieve requires EvidenceRequest")

    if isinstance(request.target, QueryTarget):
        return _query_via_shell(request, session=session)

    if session is not None:
        return retrieve_with_session(request, session, routing_policy=routing_policy)

    normalized = namespace_provider_request(request)
    return attach_relationship_frontier(
        prioritize_actionable_retrieval(
            _retrieve_contract(normalized, routing_policy=routing_policy)
        )
    )


def _read_context(
    path: Path,
    *,
    context_start: int,
    context_end: int,
) -> tuple[list[str], int]:
    rows: list[str] = []
    last_seen = 0
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for number, line in enumerate(handle, start=1):
            last_seen = number
            if number < context_start:
                continue
            if number > context_end:
                break
            rows.append(f"{number}: {line}")
    return rows, last_seen


def _evidence_uri(sha256: str, start: int, end: int) -> str:
    fragment = f"#L{start}"
    if end != start:
        fragment += f"-L{end}"
    return f"evidence://sha256/{sha256}{fragment}"


def _managed_materialize(
    target: RangeTarget,
    *,
    session: RetrievalSessionStore,
    digest: str,
) -> RetrievalResult:
    path = Path(target.source).expanduser().resolve()
    selected_end = target.end_line or target.start_line
    context_start = max(1, target.start_line - max(0, target.before))
    context_end = selected_end + max(0, target.after)
    source_key = file_source_version(str(path), digest).key

    with state_lock(session.path):
        before = session.load()
        tracker = _tracker(before)
        covered = any(
            left <= context_start and right >= context_end
            for left, right in before.covered_ranges.get(source_key, ())
        )
        if covered:
            progress = tracker.observe(source=source_key)
            canonical = AgentResult(
                operation="expand",
                status="ok",
                outcome="not_assessed",
                evidence=[],
                coverage={
                    "context_start_line": context_start,
                    "context_end_line": context_end,
                    "new_evidence": 0,
                },
                data={
                    "novelty": {
                        "state": "no_new_evidence",
                        "basis": [
                            "managed_source_version",
                            "requested_context_already_covered",
                        ],
                        "source_version": source_key,
                    }
                },
            ).to_dict()
            return RetrievalResult(
                operation="expand",
                status="no_new_evidence",
                canonical_result=canonical,
                progress=progress,
                new_evidence=(),
            )

        lines, last_seen = _read_context(
            path,
            context_start=context_start,
            context_end=context_end,
        )
        if last_seen < selected_end:
            raise ValueError(
                f"referenced line exceeds evidence source: {selected_end} > {last_seen}"
            )
        text = "".join(lines)
        truncated = len(text) > target.max_chars
        if truncated:
            text = text[: target.max_chars]

        pointer = EvidencePointer(
            uri=_evidence_uri(digest, target.start_line, selected_end),
            source_path=str(path),
            sha256=digest,
            start_line=target.start_line,
            end_line=selected_end,
        ).to_dict()
        identity = str(pointer.get("uri") or "")
        repeated = int(identity in set(before.seen_evidence))
        new_rows = () if repeated else (pointer,)

        progress = tracker.observe(
            source=source_key,
            evidence_ids=(identity,),
            line_ranges=((context_start, context_end),) if not truncated else (),
        )
        next_state, _ = before.advance(
            evidence=(identity,),
            covered_ranges=(
                {source_key: ((context_start, context_end),)}
                if not truncated
                else None
            ),
            operation=RetrievalOperation(
                operation="materialize",
                status="ok",
                new_evidence=0 if repeated else 1,
                repeated_evidence=repeated,
                new_lines=0 if truncated else context_end - context_start + 1,
                source_version=source_key,
            ),
        )
        session.save(next_state)

    canonical = AgentResult(
        operation="expand",
        status="ok",
        outcome="supported",
        evidence=[pointer],
        coverage={
            "context_start_line": context_start,
            "context_end_line": context_end,
            "truncated": truncated,
            "new_evidence": len(new_rows),
            "repeated_evidence": repeated,
        },
        data={
            "text": text,
            "source_version": source_key,
            "sha256_reused": True,
            "novelty": {
                "state": "new_evidence" if new_rows else "no_new_evidence",
                "new_evidence": len(new_rows),
                "repeated_evidence": repeated,
                "source_version": source_key,
            },
        },
    ).to_dict()
    return RetrievalResult(
        operation="expand",
        status="ok" if new_rows or truncated else "no_new_evidence",
        canonical_result=canonical,
        progress=progress,
        new_evidence=(
            tuple([pointer]) if truncated else tuple(new_rows)
        ),
        repeated_evidence=repeated,
    )


def materialize(
    target: RangeTarget,
    *,
    session: RetrievalSessionStore | None = None,
    routing_policy: EvidenceRoutingPolicy | None = None,
) -> RetrievalResult:
    """Materialize exact context; managed snapshots reuse their cached SHA."""

    if not isinstance(target, RangeTarget):
        raise TypeError("materialize requires RangeTarget")

    path = Path(target.source).expanduser().resolve()
    if session is not None and path.is_file():
        cached = managed_segment_sha(path, root=session.root)
        expected = str(target.expected_sha256 or "").strip().lower()
        if cached and (not expected or cached == expected):
            return _managed_materialize(target, session=session, digest=cached)

    return retrieve(
        EvidenceRequest(target),
        session=session,
        routing_policy=routing_policy,
    )


def replay(
    target: RangeTarget,
    *,
    session: RetrievalSessionStore,
    routing_policy: EvidenceRoutingPolicy | None = None,
) -> RetrievalResult:
    """Re-read already covered immutable context without admitting new Evidence."""

    if not isinstance(target, RangeTarget):
        raise TypeError("replay requires RangeTarget")
    if not isinstance(session, RetrievalSessionStore):
        raise TypeError("replay requires RetrievalSessionStore")
    if not target.expected_sha256:
        raise ValueError("replay requires expected_sha256 for immutable identity")

    path = Path(target.source).expanduser().resolve()
    expected = str(target.expected_sha256).lower()
    cached = managed_segment_sha(path, root=session.root)
    digest = cached if cached == expected else _sha256(path)
    if digest.lower() != expected:
        raise ValueError("replay source digest does not match expected_sha256")

    source_key = file_source_version(str(path), digest).key
    selected_end = target.end_line or target.start_line
    start = max(1, target.start_line - max(0, target.before))
    end = selected_end + max(0, target.after)
    state = session.load()
    covered = any(
        left <= start and right >= end
        for left, right in state.covered_ranges.get(source_key, ())
    )
    if not covered:
        raise ValueError("replay range has not been materialized in this RetrievalSession")

    if cached == digest:
        lines, last_seen = _read_context(path, context_start=start, context_end=end)
        if last_seen < selected_end:
            raise ValueError("replay range exceeds managed evidence source")
        text = "".join(lines)
        truncated = len(text) > target.max_chars
        if truncated:
            text = text[: target.max_chars]
        pointer = EvidencePointer(
            uri=_evidence_uri(digest, target.start_line, selected_end),
            source_path=str(path),
            sha256=digest,
            start_line=target.start_line,
            end_line=selected_end,
        ).to_dict()
        canonical = AgentResult(
            operation="expand",
            status="ok",
            outcome="supported",
            evidence=[pointer],
            coverage={
                "context_start_line": start,
                "context_end_line": end,
                "truncated": truncated,
                "new_evidence": 0,
            },
            data={
                "text": text,
                "replayed": True,
                "sha256_reused": True,
                "novelty": {
                    "state": "replay",
                    "new_evidence": 0,
                    "source_version": source_key,
                },
            },
        ).to_dict()
        progress = _tracker(state).observe(source=source_key)
    else:
        normalized = namespace_provider_request(EvidenceRequest(target))
        base = attach_relationship_frontier(
            prioritize_actionable_retrieval(
                _retrieve_contract(normalized, routing_policy=routing_policy)
            )
        )
        canonical = dict(base.canonical_result)
        data = dict(canonical.get("data") or {})
        data["replayed"] = True
        data["novelty"] = {
            "state": "replay",
            "new_evidence": 0,
            "source_version": source_key,
        }
        canonical["data"] = data
        coverage = dict(canonical.get("coverage") or {})
        coverage["new_evidence"] = 0
        canonical["coverage"] = coverage
        progress = base.progress

    fingerprint = hashlib.sha256(
        f"replay\0{source_key}\0{start}\0{end}".encode("utf-8")
    ).hexdigest()
    with state_lock(session.path):
        latest = session.load()
        next_state, _ = latest.advance(
            operation=RetrievalOperation(
                operation="replay",
                status=str(canonical.get("status") or "ok"),
                request_fingerprint=fingerprint,
                replayed=True,
                source_version=source_key,
            )
        )
        session.save(next_state)

    return RetrievalResult(
        operation="replay",
        status=str(canonical.get("status") or "ok"),
        canonical_result=canonical,
        progress=progress,
        new_evidence=(),
        repeated_evidence=len(canonical.get("evidence") or ()),
    )


def aggregate(request: AggregateRequest) -> dict[str, Any]:
    """Legacy standalone aggregate; Evidence Shell is preferred for Agent search."""

    if not isinstance(request, AggregateRequest):
        raise TypeError("aggregate requires AggregateRequest")
    path = Path(request.source).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    pattern = re.compile(request.query) if request.regex else None
    group_pattern = re.compile(request.group_regex) if request.group_regex else None
    matched = 0
    distinct: dict[str, int] = {}
    groups: dict[str, int] = {}
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            text = raw.rstrip("\r\n")
            is_match = bool(pattern.search(text)) if pattern else request.query in text
            if not is_match:
                continue
            matched += 1
            if request.operation == "distinct":
                distinct[text] = distinct.get(text, 0) + 1
            elif request.operation == "group" and group_pattern is not None:
                match = group_pattern.search(text)
                if match is None:
                    key = "<unmatched>"
                elif match.groups():
                    key = "|".join(value or "" for value in match.groups())
                else:
                    key = match.group(0)
                groups[key] = groups.get(key, 0) + 1

    data: dict[str, Any] = {"count": matched}
    if request.operation == "distinct":
        ordered = sorted(distinct.items(), key=lambda item: (-item[1], item[0]))[: request.max_groups]
        data["distinct"] = [{"value": key, "count": count} for key, count in ordered]
        data["distinct_total"] = len(distinct)
        data["truncated"] = len(distinct) > len(ordered)
    elif request.operation == "group":
        ordered = sorted(groups.items(), key=lambda item: (-item[1], item[0]))[: request.max_groups]
        data["groups"] = [{"key": key, "count": count} for key, count in ordered]
        data["groups_total"] = len(groups)
        data["truncated"] = len(groups) > len(ordered)

    return {
        "operation": "aggregate",
        "status": "ok",
        "outcome": "not_assessed",
        "source": str(path),
        "sha256": _sha256(path),
        "query": request.query,
        "regex": request.regex,
        "aggregate": request.operation,
        "data": data,
        "coverage": {"complete": True},
    }


__all__ = [
    "AggregateOperation",
    "AggregateRequest",
    "aggregate",
    "materialize",
    "replay",
    "retrieve",
    "verify",
]
