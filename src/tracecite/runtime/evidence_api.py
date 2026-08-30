"""Canonical Agent-facing Evidence Runtime operations.

The public contract is intentionally small and mechanical:
``retrieve``, ``materialize``, ``replay``, ``aggregate``, ``traverse`` and
``verify``.  These operations acquire, recover, summarize, or validate evidence;
they never choose hypotheses, causal explanations, investigation order, evidence
sufficiency, or stopping decisions.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Mapping

from .agent_api import EvidenceRequest, RangeTarget, RetrievalResult
from .evidence_routing import EvidenceRoutingPolicy
from .provider_identity import namespace_provider_request
from .relationship_frontier import attach_relationship_frontier
from .retrieval_guidance import prioritize_actionable_retrieval
from .retrieval_session import RetrievalOperation, RetrievalSessionStore
from .retrieve_contract import retrieve as _retrieve_contract
from .session_retrieval import retrieve_with_session
from .tools import verify


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


def retrieve(
    request: EvidenceRequest,
    *,
    session: RetrievalSessionStore | None = None,
    routing_policy: EvidenceRoutingPolicy | None = None,
) -> RetrievalResult:
    """Retrieve evidence selected by the caller.

    Supplying ``session`` enables canonical novelty, repeated-evidence refs,
    covered ranges, replay history, and bounded operation history.  Without a
    session the operation is stateless but retains canonical provenance.
    """

    if session is not None:
        return retrieve_with_session(request, session, routing_policy=routing_policy)
    normalized = namespace_provider_request(request)
    return attach_relationship_frontier(
        prioritize_actionable_retrieval(
            _retrieve_contract(normalized, routing_policy=routing_policy)
        )
    )


def materialize(
    target: RangeTarget,
    *,
    session: RetrievalSessionStore | None = None,
    routing_policy: EvidenceRoutingPolicy | None = None,
) -> RetrievalResult:
    """Materialize one exact caller-selected source range."""

    if not isinstance(target, RangeTarget):
        raise TypeError("materialize requires RangeTarget")
    return retrieve(EvidenceRequest(target), session=session, routing_policy=routing_policy)


def replay(
    target: RangeTarget,
    *,
    session: RetrievalSessionStore,
    routing_policy: EvidenceRoutingPolicy | None = None,
) -> RetrievalResult:
    """Re-read an already covered immutable range without changing novelty.

    Replay is intentionally explicit. The caller supplies the exact source,
    range and immutable digest. The requested context must already be covered by
    this ``RetrievalSession``; otherwise the caller should use ``materialize``.
    """

    if not isinstance(target, RangeTarget):
        raise TypeError("replay requires RangeTarget")
    if not isinstance(session, RetrievalSessionStore):
        raise TypeError("replay requires RetrievalSessionStore")
    if not target.expected_sha256:
        raise ValueError("replay requires expected_sha256 for immutable identity")

    path = Path(target.source).expanduser().resolve()
    digest = _sha256(path)
    if digest.lower() != str(target.expected_sha256).lower():
        raise ValueError("replay source digest does not match expected_sha256")

    from .evidence_identity import file_source_version

    source_key = file_source_version(str(path), digest).key
    selected_end = target.end_line or target.start_line
    start = max(1, target.start_line - max(0, target.before))
    end = selected_end + max(0, target.after)
    state = session.load()
    covered = any(left <= start and right >= end for left, right in state.covered_ranges.get(source_key, ()))
    if not covered:
        raise ValueError("replay range has not been materialized in this RetrievalSession")

    # Deliberately bypass session dedup for body recovery, then record only a
    # replay operation. No Evidence identity/range is newly admitted.
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

    fingerprint = hashlib.sha256(
        f"replay\0{source_key}\0{start}\0{end}".encode("utf-8")
    ).hexdigest()
    from tracecite_core.state_file import state_lock

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
        progress=base.progress,
        new_evidence=(),
        repeated_evidence=len(canonical.get("evidence") or ()),
        acquisition_end_reason=base.acquisition_end_reason,
    )


def aggregate(request: AggregateRequest) -> dict[str, Any]:
    """Compute a bounded deterministic aggregate over explicit text matches.

    This is a convenience for counts/distinct/grouping that Agents otherwise
    tend to implement with shell pipelines. It returns mechanical values and
    source provenance only; no result is ranked as causal or important.
    """

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
