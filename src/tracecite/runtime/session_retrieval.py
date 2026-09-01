from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

from tracecite_core.state_file import state_lock

from .agent_api import EvidenceRequest, ProviderTarget, QueryTarget, RangeTarget, RetrievalResult, SourceTarget
from .evidence_coordinates import attach_seen_range_distances
from .evidence_identity import SourceVersion, file_source_version, pointer_source_key
from .evidence_progress import EvidenceProgressTracker
from .evidence_routing import EvidenceRoutingPolicy
from .provider_identity import namespace_provider_request
from .relationship_frontier import attach_relationship_frontier
from .retrieval_guidance import prioritize_actionable_retrieval
from .retrieval_session import (
    DEFAULT_MAX_SEEN_EVIDENCE,
    DEFAULT_MAX_SEEN_RELATIONS,
    RetrievalOperation,
    RetrievalSessionState,
    RetrievalSessionStore,
)
from .retrieve_contract import retrieve as _retrieve_contract


_LINE_PREFIX_RE = re.compile(r"^\s*(\d+):(?:\s|$)")


def _request_operation(request: EvidenceRequest) -> tuple[str, str]:
    target = request.target
    if isinstance(target, QueryTarget):
        operation = "search"
        identity = {
            "source": str(Path(target.source).expanduser().resolve()),
            "query": target.query,
            "regex": target.regex,
            "last": target.last,
            "since": target.since,
            "until": target.until,
            "fold": target.fold,
        }
    elif isinstance(target, RangeTarget):
        operation = "expand"
        identity = {
            "source": str(Path(target.source).expanduser().resolve()),
            "start_line": target.start_line,
            "end_line": target.end_line,
            "before": target.before,
            "after": target.after,
            "expected_sha256": target.expected_sha256,
        }
    elif isinstance(target, SourceTarget):
        operation = "probe"
        identity = {
            "source": str(Path(target.source).expanduser().resolve()),
            "glob": target.glob,
            "recursive": target.recursive,
            "segmenter": target.segmenter,
        }
    elif isinstance(target, ProviderTarget):
        operation = "retrieve"
        identity = {"provider_request": target.request.to_dict()}
    else:
        operation = "retrieve"
        identity = {"target_type": type(target).__name__}
    encoded = json.dumps(
        {"operation": operation, "identity": identity},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return operation, hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _operation_record(
    request: EvidenceRequest,
    *,
    status: str,
    new_evidence: int,
    repeated_evidence: int,
    new_relations: int,
    new_lines: int,
    source_version: str | None,
) -> RetrievalOperation:
    operation, fingerprint = _request_operation(request)
    return RetrievalOperation(
        operation=operation,
        status=status,
        request_fingerprint=fingerprint,
        new_evidence=new_evidence,
        repeated_evidence=repeated_evidence,
        new_relations=new_relations,
        new_lines=new_lines,
        source_version=source_version or "",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _pointer_ids(evidence: tuple[Mapping[str, Any], ...]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            str(item.get("uri") or "").strip()
            for item in evidence
            if str(item.get("uri") or "").strip()
        )
    )


def _matched_existing_evidence_refs(
    evidence: tuple[Mapping[str, Any], ...],
    new_rows: tuple[Mapping[str, Any], ...],
) -> tuple[dict[str, Any], ...]:
    """Project repeated matches as lightweight identities, never repeated bodies.

    A repeated match only means the current retrieval matched evidence that was
    delivered earlier in this RetrievalSession. It does not imply that the
    Agent understood, used, or should ignore that evidence now.
    """

    new_ids = set(_pointer_ids(new_rows))
    refs: list[dict[str, Any]] = []
    for item in evidence:
        uri = str(item.get("uri") or "").strip()
        if not uri or uri in new_ids:
            continue
        ref: dict[str, Any] = {"uri": uri}
        source_path = str(item.get("source_path") or "").strip()
        if source_path:
            ref["source_path"] = source_path
        start = item.get("start_line")
        end = item.get("end_line")
        if isinstance(start, int) and not isinstance(start, bool) and start > 0:
            ref["start_line"] = start
        if isinstance(end, int) and not isinstance(end, bool) and end > 0:
            ref["end_line"] = end
        sha256 = str(item.get("sha256") or "").strip().lower()
        if re.fullmatch(r"[0-9a-f]{64}", sha256):
            ref["sha256"] = sha256
        position = item.get("position")
        if isinstance(position, Mapping):
            ref["position"] = dict(position)
        refs.append(ref)
    return tuple(refs)


def _relation_ids(canonical: Mapping[str, Any]) -> tuple[str, ...]:
    data = canonical.get("data") or {}
    if not isinstance(data, Mapping):
        return ()
    rows = data.get("observed_relations") or []
    if not isinstance(rows, list):
        return ()
    return tuple(
        dict.fromkeys(
            str(item.get("relation_id") or "").strip()
            for item in rows
            if isinstance(item, Mapping) and str(item.get("relation_id") or "").strip()
        )
    )


def _restore_tracker(state: RetrievalSessionState) -> EvidenceProgressTracker:
    tracker = EvidenceProgressTracker()
    tracker.restore(evidence_ids=state.seen_evidence)
    for source, ranges in state.covered_ranges.items():
        tracker.restore(source=source, line_ranges=ranges)
    return tracker


def _visible_line_ranges(canonical: Mapping[str, Any]) -> tuple[tuple[int, int], ...]:
    data = canonical.get("data") or {}
    if not isinstance(data, Mapping):
        return ()
    text = data.get("text")
    if not isinstance(text, str) or not text:
        return ()
    numbers: list[int] = []
    for raw in text.splitlines():
        match = _LINE_PREFIX_RE.match(raw)
        if match is not None:
            numbers.append(int(match.group(1)))
    if not numbers:
        return ()
    ordered = sorted(set(numbers))
    ranges: list[tuple[int, int]] = []
    start = previous = ordered[0]
    for number in ordered[1:]:
        if number == previous + 1:
            previous = number
            continue
        ranges.append((start, previous))
        start = previous = number
    ranges.append((start, previous))
    return tuple(ranges)


def _filter_numbered_text(text: str, ranges: tuple[tuple[int, int], ...]) -> str:
    if not text or not ranges:
        return ""

    def included(number: int) -> bool:
        return any(start <= number <= end for start, end in ranges)

    kept: list[str] = []
    keep_continuation = False
    for raw in text.splitlines():
        match = _LINE_PREFIX_RE.match(raw)
        if match is not None:
            keep_continuation = included(int(match.group(1)))
        if keep_continuation:
            kept.append(raw)
    return "\n".join(kept) + ("\n" if kept else "")


def _new_generation(path: Path, *, stat: Any, revision: int) -> str:
    raw = (
        f"{path}|{int(stat.st_dev)}|{int(stat.st_ino)}|{int(stat.st_size)}|"
        f"{int(stat.st_mtime_ns)}|{revision}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _observe_append_source(
    path: Path,
    state: RetrievalSessionState,
) -> tuple[str, dict[str, Any], bool]:
    """Return a stable generation for an unchanged or append-grown local file.

    A generation is preserved only when the same filesystem object is observed
    with non-decreasing size. Inode replacement, truncation, or same-size
    modification creates a new generation. This is mechanical source lifecycle
    bookkeeping; it does not infer anything about the evidence semantics.
    """

    resolved = path.expanduser().resolve()
    stat = resolved.stat()
    source = str(resolved)
    previous = state.source_observations.get(source)
    append_compatible = False
    generation = ""
    if isinstance(previous, Mapping):
        same_object = (
            int(previous.get("device") or 0) == int(stat.st_dev)
            and int(previous.get("inode") or 0) == int(stat.st_ino)
        )
        previous_size = int(previous.get("size") or 0)
        previous_mtime = int(previous.get("mtime_ns") or 0)
        append_compatible = bool(
            same_object
            and int(stat.st_size) >= previous_size
            and (
                int(stat.st_size) > previous_size
                or int(stat.st_mtime_ns) == previous_mtime
            )
        )
        if append_compatible:
            generation = str(previous.get("generation") or "").strip()
    if not generation:
        generation = _new_generation(resolved, stat=stat, revision=state.revision)
    observation = {
        "generation": generation,
        "device": int(stat.st_dev),
        "inode": int(stat.st_ino),
        "size": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
    }
    source_key = SourceVersion(
        namespace="file",
        source=source,
        kind="generation",
        value=generation,
    ).key
    return source_key, observation, append_compatible


def _range_source_identity(
    request: EvidenceRequest,
    state: RetrievalSessionState,
) -> tuple[str, dict[str, Any] | None] | None:
    target = request.target
    if not isinstance(target, RangeTarget):
        return None
    path = Path(target.source).expanduser().resolve()
    if not path.is_file():
        return None
    if target.expected_sha256:
        expected = str(target.expected_sha256).strip().lower()
        if _sha256(path).lower() != expected:
            return None
        return file_source_version(str(path), expected).key, None
    source_key, observation, _ = _observe_append_source(path, state)
    return source_key, observation


def _already_covered_range(
    request: EvidenceRequest,
    tracker: EvidenceProgressTracker,
    state: RetrievalSessionState,
) -> tuple[str, int, int, dict[str, Any] | None] | None:
    target = request.target
    identity = _range_source_identity(request, state)
    if not isinstance(target, RangeTarget) or identity is None:
        return None
    source_key, observation = identity
    selected_end = target.end_line or target.start_line
    start = max(1, target.start_line - max(0, target.before))
    end = selected_end + max(0, target.after)
    if tracker.range_is_covered(source_key, start, end):
        return source_key, start, end, observation
    return None


def _commit_observation(
    store: RetrievalSessionStore,
    *,
    request: EvidenceRequest,
    canonical_status: str,
    truncated: bool,
    evidence: tuple[Mapping[str, Any], ...],
    relation_ids: tuple[str, ...],
    source_key: str | None,
    source_observation: tuple[str, Mapping[str, Any]] | None,
    line_ranges: tuple[tuple[int, int], ...],
) -> tuple[
    EvidenceProgressTracker,
    object,
    tuple[Mapping[str, Any], ...],
    int,
    tuple[str, ...],
    tuple[tuple[int, int], ...],
    str,
    dict[str, Any],
]:
    """Atomically merge one retrieval result with the latest session state."""

    with state_lock(store.path):
        state = store.load()
        tracker = _restore_tracker(state)
        prior = set(state.seen_evidence)
        evidence_ids = _pointer_ids(evidence)
        new_rows = tuple(
            item
            for item in evidence
            if str(item.get("uri") or "").strip() not in prior
        )
        repeated = max(0, len(evidence) - len(new_rows))

        prior_relations = set(state.seen_relations)
        new_relation_ids = tuple(item for item in relation_ids if item not in prior_relations)

        unseen_ranges: tuple[tuple[int, int], ...] = ()
        if source_key and line_ranges:
            unseen: list[tuple[int, int]] = []
            for start, end in line_ranges:
                unseen.extend(tracker.unseen_ranges(source_key, start, end))
            unseen_ranges = tuple(unseen)

        readiness = tracker.observe(
            source=source_key,
            evidence_ids=evidence_ids,
            line_ranges=line_ranges,
            new_relations=len(new_relation_ids),
        )

        operation_status = str(canonical_status or "unknown")
        if (
            operation_status.lower() not in {"error", "no_match"}
            and evidence
            and not new_rows
            and not new_relation_ids
            and readiness.delta.new_lines == 0
            and not truncated
        ):
            operation_status = "no_new_evidence"

        evidence_limit = max(
            DEFAULT_MAX_SEEN_EVIDENCE,
            len(state.seen_evidence) + len(evidence_ids) + 1,
        )
        relation_limit = max(
            DEFAULT_MAX_SEEN_RELATIONS,
            len(state.seen_relations) + len(relation_ids) + 1,
        )
        observations = None
        if source_observation is not None:
            observations = {source_observation[0]: source_observation[1]}
        next_state, _ = state.advance(
            evidence=evidence_ids,
            relations=relation_ids,
            covered_ranges={source_key: line_ranges} if source_key and line_ranges else None,
            source_observations=observations,
            operation=_operation_record(
                request,
                status=operation_status,
                new_evidence=len(new_rows),
                repeated_evidence=repeated,
                new_relations=len(new_relation_ids),
                new_lines=readiness.delta.new_lines,
                source_version=source_key,
            ),
            max_seen_evidence=evidence_limit,
            max_seen_relations=relation_limit,
        )
        store.save(next_state)
        session_progress = next_state.retrieval_summary()

    return (
        tracker,
        readiness,
        new_rows,
        repeated,
        new_relation_ids,
        unseen_ranges,
        operation_status,
        session_progress,
    )


def retrieve_with_session(
    request: EvidenceRequest,
    session: RetrievalSessionStore,
    *,
    routing_policy: EvidenceRoutingPolicy | None = None,
) -> RetrievalResult:
    """Execute canonical retrieval with independent mechanical session memory."""

    if not isinstance(request, EvidenceRequest):
        raise TypeError("retrieve_with_session requires EvidenceRequest")
    if not isinstance(session, RetrievalSessionStore):
        raise TypeError("retrieve_with_session requires RetrievalSessionStore")
    if request.investigation_path is not None:
        raise ValueError("independent retrieval session cannot also use investigation_path")
    if request.hypothesis_id is not None or request.test_id is not None:
        raise ValueError("hypothesis_id/test_id require optional InvestigationState, not RetrievalSession")

    with state_lock(session.path):
        state = session.load()
        tracker = _restore_tracker(state)
        covered = _already_covered_range(request, tracker, state)
    if covered is not None:
        source_key, _start, _end, observation = covered
        with state_lock(session.path):
            latest = session.load()
            tracker = _restore_tracker(latest)
            readiness = tracker.observe(source=source_key)
            observations = None
            if observation is not None:
                observations = {
                    str(Path(request.target.source).expanduser().resolve()): observation
                }
            next_state, _ = latest.advance(
                source_observations=observations,
                operation=_operation_record(
                    request,
                    status="no_new_evidence",
                    new_evidence=0,
                    repeated_evidence=0,
                    new_relations=0,
                    new_lines=0,
                    source_version=source_key,
                ),
            )
            session.save(next_state)
            session_progress = next_state.retrieval_summary()
        return RetrievalResult(
            operation="expand",
            status="no_new_evidence",
            canonical_result={
                "operation": "expand",
                "status": "ok",
                "outcome": "not_assessed",
                "evidence": [],
                "coverage": {},
                "data": {
                    "new_text": "",
                    "unseen_ranges": [],
                    "source_version": source_key,
                    "session_progress": session_progress,
                    "novelty": {
                        "state": "no_new_evidence",
                        "basis": ["source_generation", "requested_context_already_covered"],
                        "source_version": source_key,
                    },
                },
            },
            progress=readiness,
        )

    normalized = namespace_provider_request(request)
    base = attach_relationship_frontier(
        prioritize_actionable_retrieval(
            _retrieve_contract(normalized, routing_policy=routing_policy)
        )
    )
    canonical = dict(base.canonical_result)
    evidence = tuple(
        item for item in canonical.get("evidence") or [] if isinstance(item, Mapping)
    )
    relation_ids = _relation_ids(canonical)

    source_key: str | None = None
    source_observation: tuple[str, Mapping[str, Any]] | None = None
    line_ranges: tuple[tuple[int, int], ...] = ()
    coverage = canonical.get("coverage") or {}
    truncated = (
        bool(coverage.get("truncated") or coverage.get("evidence_truncated"))
        if isinstance(coverage, Mapping)
        else False
    )
    if isinstance(request.target, RangeTarget) and evidence:
        if request.target.expected_sha256:
            source_key = pointer_source_key(evidence[0])
        else:
            with state_lock(session.path):
                latest = session.load()
                identity = _range_source_identity(request, latest)
            if identity is not None:
                source_key, observation = identity
                if observation is not None:
                    source_observation = (
                        str(Path(request.target.source).expanduser().resolve()),
                        observation,
                    )
        line_ranges = _visible_line_ranges(canonical)

    (
        _tracker,
        readiness,
        new_rows,
        repeated,
        new_relation_ids,
        unseen_ranges,
        operation_status,
        session_progress,
    ) = _commit_observation(
        session,
        request=request,
        canonical_status=str(canonical.get("status") or base.status or "unknown"),
        truncated=truncated,
        evidence=evidence,
        relation_ids=relation_ids,
        source_key=source_key,
        source_observation=source_observation,
        line_ranges=line_ranges,
    )

    # Query candidates are compared only to ranges the Agent has actually
    # materialized earlier in this RetrievalSession. Query retrieval itself does
    # not add covered ranges, so reading the post-commit state cannot turn a
    # candidate into its own historical neighbor.
    if isinstance(request.target, QueryTarget) and evidence:
        with state_lock(session.path):
            coordinate_state = session.load()
        annotated = tuple(
            attach_seen_range_distances(evidence, coordinate_state.covered_ranges)
        )
        by_uri = {
            str(item.get("uri") or "").strip(): item
            for item in annotated
            if str(item.get("uri") or "").strip()
        }
        new_rows = tuple(
            by_uri.get(str(item.get("uri") or "").strip(), dict(item))
            for item in new_rows
        )
        evidence = annotated
        canonical["evidence"] = [dict(item) for item in annotated]

    data = dict(canonical.get("data") or {})
    data["session_progress"] = session_progress
    canonical["data"] = data

    if repeated:
        matched_existing = _matched_existing_evidence_refs(evidence, new_rows)
        if matched_existing:
            data = dict(canonical.get("data") or {})
            data["matched_existing_evidence"] = [dict(item) for item in matched_existing]
            canonical["data"] = data

    if isinstance(request.target, RangeTarget):
        data = dict(canonical.get("data") or {})
        full_text = data.get("text") if isinstance(data.get("text"), str) else ""
        data["new_text"] = _filter_numbered_text(full_text, unseen_ranges)
        data["unseen_ranges"] = [[start, end] for start, end in unseen_ranges]
        data["repeated_text_suppressed"] = bool(full_text and not data["new_text"])
        if source_key:
            data["source_version"] = source_key
        canonical["data"] = data

    status = operation_status
    acquisition_end_reason = base.acquisition_end_reason
    if status == "no_new_evidence":
        data = dict(canonical.get("data") or {})
        data["novelty"] = {
            "state": "no_new_evidence",
            "basis": ["all_returned_evidence_already_seen"],
        }
        canonical["data"] = data

    return RetrievalResult(
        operation=base.operation,
        status=status,
        canonical_result=canonical,
        progress=readiness,
        new_evidence=new_rows,
        repeated_evidence=repeated,
        acquisition_end_reason=acquisition_end_reason,
    )


__all__ = ["retrieve_with_session"]
