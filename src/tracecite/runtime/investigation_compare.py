"""Bounded, deterministic read-only Investigation timeline and comparison.

The primitives in this module are intentionally separate from the mutation and
tool modules.  They inspect a validated :class:`InvestigationState` (or a
bounded path/mapping/store source) and return structural control metadata only:
IDs, statuses, outcomes, counts, links, coverage-presence and recording flags.
They never copy claims, summaries, stop details, parameters, evidence URIs or
raw source bodies into the result.

No inference is performed.  A changed count or outcome is a structural delta,
not an anomaly or a causal explanation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

from tracecite_core.state_file import read_json

from .investigation import InvestigationError, InvestigationState, InvestigationStore


TIMELINE_SCHEMA_VERSION = 1
COMPARE_SCHEMA_VERSION = 1

MAX_TIMELINE_EVENTS = 128
MAX_COMPARE_ITEMS = 128
MAX_COMPARE_OUTPUT_CHARS = 24_000
MAX_COMPARE_SOURCE_BYTES = 1_048_576
MAX_COMPARE_TEXT_CHARS = 256

_ENTITY_NAMES = (
    "observations",
    "hypotheses",
    "tests",
    "executions",
    "findings",
    "knowledge_candidates",
)
_BUDGET_USAGE_NAMES = (
    "executions",
    "searches",
    "queries",
    "recorded_evidence_pointers",
    "expand_requested_chars",
    "expand_returned_chars",
    "elapsed_seconds",
)
_BUDGET_POLICY_NAMES = (
    "max_executions",
    "max_searches",
    "max_queries",
    "max_recorded_evidence_pointers",
    "max_expand_requested_chars",
    "max_expand_returned_chars",
    "max_elapsed_seconds",
)
_EVENT_RANK = {
    "investigation_created": 0,
    "hypothesis": 10,
    "test": 20,
    "execution": 30,
    "finding": 40,
    "knowledge_candidate": 50,
    "stop": 60,
}


class InvestigationCompareError(ValueError):
    """Stable input/limit error for strict callers."""


@dataclass(frozen=True)
class InvestigationCompareLimits:
    """Hard bounds for timeline/compare prompt-facing output.

    Positive requests above a hard ceiling are clamped.  Non-positive or
    non-integer values are invalid rather than silently becoming an unlimited
    request.
    """

    max_events: int = MAX_TIMELINE_EVENTS
    max_items: int = MAX_COMPARE_ITEMS
    max_output_chars: int = MAX_COMPARE_OUTPUT_CHARS
    max_source_bytes: int = MAX_COMPARE_SOURCE_BYTES

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "max_events",
            _limit(self.max_events, 1, MAX_TIMELINE_EVENTS, "max_events"),
        )
        object.__setattr__(
            self,
            "max_items",
            _limit(self.max_items, 1, MAX_COMPARE_ITEMS, "max_items"),
        )
        object.__setattr__(
            self,
            "max_output_chars",
            _limit(
                self.max_output_chars,
                512,
                MAX_COMPARE_OUTPUT_CHARS,
                "max_output_chars",
            ),
        )
        object.__setattr__(
            self,
            "max_source_bytes",
            _limit(
                self.max_source_bytes,
                4_096,
                MAX_COMPARE_SOURCE_BYTES,
                "max_source_bytes",
            ),
        )


def _limit(value: Any, lower: int, upper: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < lower:
        raise InvestigationCompareError("invalid_limit:" + name)
    return min(value, upper)


def _text(value: Any, *, limit: int = MAX_COMPARE_TEXT_CHARS) -> str:
    if value is None:
        return ""
    return str(value)[:limit]


def _id(value: Any) -> str:
    return _text(value, limit=128).strip()


def _truthy(value: Any) -> bool:
    if value is None or value is False:
        return False
    if isinstance(value, (str, bytes)):
        return bool(value)
    if isinstance(value, (Mapping, Sequence)):
        return len(value) > 0
    return bool(value)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _source_kind(source: Any) -> str:
    if isinstance(source, InvestigationState):
        return "state"
    if isinstance(source, InvestigationStore):
        return "store"
    if isinstance(source, Mapping):
        return "mapping"
    if isinstance(source, (str, Path)):
        return "path"
    return "unsupported"


def _check_mapping_size(value: Mapping[str, Any], *, limits: InvestigationCompareLimits) -> None:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise InvestigationCompareError("source_invalid") from exc
    if len(encoded) > limits.max_source_bytes:
        raise InvestigationCompareError("source_too_large")


def _check_path(path: Any, *, limits: InvestigationCompareLimits) -> Path:
    if not isinstance(path, (str, Path)):
        raise InvestigationCompareError("source_unreadable")
    resolved = Path(path).expanduser().resolve()
    try:
        if not resolved.is_file():
            raise InvestigationCompareError("source_missing")
        if resolved.stat().st_size > limits.max_source_bytes:
            raise InvestigationCompareError("source_too_large")
    except OSError as exc:
        raise InvestigationCompareError("source_unreadable") from exc
    return resolved


def _load_state(
    source: Union[InvestigationState, InvestigationStore, Mapping[str, Any], str, Path],
    *,
    limits: InvestigationCompareLimits,
) -> Tuple[InvestigationState, str]:
    """Load and validate one source without writing or retaining raw input."""

    kind = _source_kind(source)
    if isinstance(source, InvestigationState):
        raw = source.to_dict()
        _check_mapping_size(raw, limits=limits)
        return InvestigationState.from_dict(raw), kind
    if isinstance(source, InvestigationStore):
        path = _check_path(getattr(source, "path", None), limits=limits)
        try:
            return InvestigationStore(path).load(), kind
        except (OSError, ValueError, TypeError, KeyError, InvestigationError) as exc:
            raise InvestigationCompareError("source_invalid") from exc
    if isinstance(source, Mapping):
        _check_mapping_size(source, limits=limits)
        try:
            return InvestigationState.from_dict(source), kind
        except (ValueError, TypeError, KeyError, InvestigationError) as exc:
            raise InvestigationCompareError("source_invalid") from exc
    if isinstance(source, (str, Path)):
        path = _check_path(source, limits=limits)
        try:
            # read_json is used only to enforce the same top-level JSON
            # contract before canonical state validation; no raw field is
            # returned by this module.
            raw = read_json(path)
            _check_mapping_size(raw, limits=limits)
            return InvestigationState.from_dict(raw), kind
        except InvestigationCompareError:
            raise
        except (OSError, ValueError, TypeError, KeyError, InvestigationError) as exc:
            raise InvestigationCompareError("source_invalid") from exc
    raise InvestigationCompareError("unsupported_source")


def _encoded_size(value: Mapping[str, Any]) -> int:
    return len(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _error_envelope(
    kind: str,
    source_kind: str,
    code: str,
    *,
    limits: InvestigationCompareLimits,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "schema_version": TIMELINE_SCHEMA_VERSION if kind == "timeline" else COMPARE_SCHEMA_VERSION,
        "kind": kind,
        "status": "error",
        "valid": False,
        "source_kind": source_kind,
        "events": [] if kind == "timeline" else None,
        "omitted": {"events": 0, "items": 0, "transitions": 0},
        "truncated": False,
        "error": {"code": code},
    }
    return _fit_output(payload, limits=limits, kind=kind)


def _recording_metrics(executions: Sequence[Mapping[str, Any]]) -> Dict[str, int]:
    omissions = 0
    truncations = 0
    missing_evidence = 0
    for item in executions:
        recording = _mapping(item.get("recording"))
        for key, value in recording.items():
            if not _truthy(value):
                continue
            name = str(key).lower()
            if name.endswith("_omitted"):
                omissions += 1
            if name.endswith("_truncated"):
                truncations += 1
        if _truthy(item.get("missing_evidence")):
            missing_evidence += 1
    return {
        "omitted": omissions,
        "truncated": truncations,
        "missing_evidence": missing_evidence,
    }


def _coverage_metrics(state: InvestigationState) -> Dict[str, int]:
    declared = 0
    fields = 0
    for collection in (state.tests, state.executions, state.findings):
        for item in collection:
            coverage = _mapping(item.get("coverage"))
            if coverage:
                declared += 1
                fields += len(coverage)
    recording = _recording_metrics(state.executions)
    return {
        "declared_records": declared,
        "declared_fields": fields,
        "omitted": recording["omitted"],
        "truncated": recording["truncated"],
        "missing_evidence": recording["missing_evidence"],
    }


def _limitation_metrics(state: InvestigationState) -> Dict[str, int]:
    records = 0
    items = 0
    for finding in state.findings:
        limitations = finding.get("limitations") or ()
        if limitations:
            records += 1
            items += len(limitations)
    return {"declared_records": records, "items": items}


def _delta(left: Mapping[str, Any], right: Mapping[str, Any], names: Iterable[str]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for name in names:
        before = left.get(name)
        after = right.get(name)
        if before is None or after is None:
            result[name] = {"left": before, "right": after, "delta": None}
            continue
        try:
            difference = after - before
        except (TypeError, ValueError):
            difference = None
        result[name] = {"left": before, "right": after, "delta": difference}
    return result


def _entity_items(state: InvestigationState, name: str) -> Sequence[Mapping[str, Any]]:
    values = getattr(state, name, ())
    return [item for item in values if isinstance(item, Mapping)]


def _entity_map(state: InvestigationState, name: str) -> Dict[str, Mapping[str, Any]]:
    result: Dict[str, Mapping[str, Any]] = {}
    for item in _entity_items(state, name):
        identifier = _id(item.get("id") or item.get("candidate_id"))
        if identifier and identifier not in result:
            result[identifier] = item
    return result


def _ids(value: Any) -> Tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        return ()
    return tuple(sorted({identifier for identifier in (_id(item) for item in value) if identifier}))


def _signature(name: str, item: Mapping[str, Any]) -> Dict[str, Any]:
    """Return structural fields only; no user-authored values are copied."""

    if name == "observations":
        return {
            "evidence_ref_count": len(_ids(item.get("evidence_refs"))),
            "metadata_present": bool(_mapping(item.get("metadata"))),
        }
    if name == "hypotheses":
        return {
            "status": _text(item.get("status") or "open", limit=128).lower(),
            "test_count": len(_ids(item.get("test_ids") or item.get("tests"))),
        }
    if name == "tests":
        return {
            "hypothesis_id": _id(item.get("hypothesis_id")),
            "execution_count": len(_ids(item.get("execution_ids"))),
            "coverage_present": bool(_mapping(item.get("coverage"))),
        }
    if name == "executions":
        return {
            "hypothesis_id": _id(item.get("hypothesis_id")),
            "test_id": _id(item.get("test_id")),
            "status": _text(item.get("status") or "unknown", limit=128).lower(),
            "outcome": _text(item.get("outcome") or "unknown", limit=128).lower(),
            "evidence_count": len(item.get("evidence") or ()) + len(_ids(item.get("evidence_refs"))),
            "artifact_count": len(item.get("artifacts") or ()),
            "coverage_present": bool(_mapping(item.get("coverage"))),
            "recording_omitted": sum(
                1
                for key, value in _mapping(item.get("recording")).items()
                if _truthy(value) and str(key).lower().endswith("_omitted")
            ),
            "recording_truncated": sum(
                1
                for key, value in _mapping(item.get("recording")).items()
                if _truthy(value) and str(key).lower().endswith("_truncated")
            ),
        }
    if name == "findings":
        return {
            "hypothesis_id": _id(item.get("hypothesis_id")),
            "outcome": _text(item.get("outcome") or "unknown", limit=128).lower(),
            "coverage_present": bool(_mapping(item.get("coverage"))),
            "support_ref_count": len(_ids(item.get("supporting_evidence"))),
            "contradict_ref_count": len(_ids(item.get("contradicting_evidence"))),
        }
    return {
        "finding_id": _id(item.get("finding_id")),
        "status": _text(item.get("status") or "candidate", limit=128).lower(),
        "store_link_present": bool(_text(item.get("store_path") or item.get("link"))),
    }


def _append_capped(
    rows: List[Any], value: Any, *, limit: int, omitted: Dict[str, int], key: str
) -> None:
    if len(rows) < limit:
        rows.append(value)
    else:
        omitted[key] = int(omitted.get(key) or 0) + 1


def _fit_output(payload: Dict[str, Any], *, limits: InvestigationCompareLimits, kind: str) -> Dict[str, Any]:
    """Trim only deterministic lists, then fall back to a control envelope."""

    omitted = payload.setdefault("omitted", {})

    def trim(path: Sequence[Union[str, int]], key: str) -> bool:
        target: Any = payload
        for part in path[:-1]:
            target = target.get(part) if isinstance(target, Mapping) else None
            if target is None:
                return False
        name = path[-1]
        rows = target.get(name) if isinstance(target, Mapping) else None
        if not isinstance(rows, list) or not rows:
            return False
        rows.pop()
        omitted[key] = int(omitted.get(key) or 0) + 1
        payload["truncated"] = True
        if kind == "timeline" and path == ("events",):
            counts = payload.get("counts")
            if isinstance(counts, dict):
                counts["reported"] = len(rows)
                counts["omitted"] = int(counts.get("omitted") or 0) + 1
        return True

    while _encoded_size(payload) > limits.max_output_chars:
        removed = False
        if kind == "timeline":
            removed = trim(("events",), "events")
        else:
            for entity in _ENTITY_NAMES:
                for field in ("added", "removed", "changed"):
                    if trim(("ids", entity, field), "items"):
                        removed = True
                        break
                if removed:
                    break
            if not removed:
                removed = trim(("outcome_transitions",), "transitions")
            if not removed:
                removed = trim(("knowledge_links", "added"), "items")
            if not removed:
                removed = trim(("knowledge_links", "removed"), "items")
            if not removed:
                removed = trim(("knowledge_links", "changed"), "items")
        if removed:
            continue
        compact: Dict[str, Any] = {
            "schema_version": payload.get("schema_version"),
            "kind": payload.get("kind", kind),
            "status": payload.get("status", "error"),
            "valid": bool(payload.get("valid")),
            "truncated": True,
            "omitted": dict(omitted),
        }
        if payload.get("error"):
            compact["error"] = dict(payload["error"])
        if payload.get("investigation_id"):
            compact["investigation_id"] = payload["investigation_id"]
        if payload.get("revision") is not None:
            compact["revision"] = payload["revision"]
        if payload.get("left"):
            compact["left"] = dict(payload["left"])
        if payload.get("right"):
            compact["right"] = dict(payload["right"])
        if _encoded_size(compact) <= limits.max_output_chars:
            return compact
        minimal = {
            "schema_version": payload.get("schema_version"),
            "kind": kind,
            "status": payload.get("status", "error"),
            "valid": bool(payload.get("valid")),
            "truncated": True,
        }
        for name in ("error", "omitted", "investigation_id"):
            if name not in payload and name != "omitted":
                continue
            candidate = dict(minimal)
            candidate[name] = payload.get(name) if name != "omitted" else dict(omitted)
            if _encoded_size(candidate) <= limits.max_output_chars:
                minimal = candidate
        return minimal
    return payload


def _timeline_events(state: InvestigationState) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []

    def add(
        event_kind: str,
        identifier: str,
        timestamp: Any,
        *,
        status: str = "",
        outcome: str = "",
        links: Optional[Mapping[str, Any]] = None,
    ) -> None:
        row: Dict[str, Any] = {
            "kind": event_kind,
            "id": _id(identifier),
            "timestamp": _text(timestamp),
        }
        if status:
            row["status"] = _text(status, limit=128)
        if outcome:
            row["outcome"] = _text(outcome, limit=128)
        if links:
            bounded = {
                str(key): _id(value)
                for key, value in sorted(links.items())
                if _id(value)
            }
            if bounded:
                row["links"] = bounded
        events.append(row)

    add(
        "investigation_created",
        state.investigation_id,
        state.created_at,
    )
    for item in state.hypotheses:
        add(
            "hypothesis",
            _id(item.get("id")),
            item.get("created_at"),
            status=_text(item.get("status") or "open", limit=128),
        )
    for item in state.tests:
        add(
            "test",
            _id(item.get("id")),
            item.get("created_at"),
            links={"hypothesis_id": item.get("hypothesis_id")},
        )
    for item in state.executions:
        add(
            "execution",
            _id(item.get("id")),
            item.get("recorded_at"),
            status=_text(item.get("status") or "unknown", limit=128),
            outcome=_text(item.get("outcome") or "unknown", limit=128),
            links={
                "hypothesis_id": item.get("hypothesis_id"),
                "test_id": item.get("test_id"),
            },
        )
    for item in state.findings:
        add(
            "finding",
            _id(item.get("id")),
            item.get("created_at"),
            outcome=_text(item.get("outcome") or "unknown", limit=128),
            links={"hypothesis_id": item.get("hypothesis_id")},
        )
    for item in state.knowledge_candidates:
        add(
            "knowledge_candidate",
            _id(item.get("candidate_id")),
            item.get("created_at"),
            status=_text(item.get("status") or "candidate", limit=128),
            links={"finding_id": item.get("finding_id")},
        )
    stop = _mapping(state.stop_reason)
    if stop:
        add(
            "stop",
            state.investigation_id,
            stop.get("stopped_at"),
            status=state.status,
            links={"stop_kind": stop.get("kind")},
        )
    events.sort(
        key=lambda item: (
            not bool(_text(item.get("timestamp"))),
            _text(item.get("timestamp")),
            _EVENT_RANK.get(str(item.get("kind")), 999),
            _id(item.get("id")),
        )
    )
    return events


def timeline_investigation(
    source: Union[InvestigationState, InvestigationStore, Mapping[str, Any], str, Path],
    *,
    max_events: int = MAX_TIMELINE_EVENTS,
    max_output_chars: int = MAX_COMPARE_OUTPUT_CHARS,
    max_source_bytes: int = MAX_COMPARE_SOURCE_BYTES,
    strict: bool = False,
) -> Dict[str, Any]:
    """Return a bounded stable control-event timeline for one investigation."""

    source_kind = _source_kind(source)
    try:
        limits = InvestigationCompareLimits(
            max_events=max_events,
            max_output_chars=max_output_chars,
            max_source_bytes=max_source_bytes,
        )
        state, source_kind = _load_state(source, limits=limits)
        all_events = _timeline_events(state)
        events = all_events[: limits.max_events]
        omitted = max(0, len(all_events) - len(events))
        missing_timestamps = sum(1 for event in all_events if not event.get("timestamp"))
        payload: Dict[str, Any] = {
            "schema_version": TIMELINE_SCHEMA_VERSION,
            "kind": "timeline",
            "status": "ok",
            "valid": True,
            "source_kind": source_kind,
            "investigation_id": _id(state.investigation_id),
            "revision": state.revision,
            "events": events,
            "counts": {
                "total": len(all_events),
                "reported": len(events),
                "omitted": omitted,
            },
            "timestamps": {"missing": missing_timestamps},
            "omitted": {"events": omitted, "items": 0, "transitions": 0},
            "truncated": omitted > 0,
        }
        return _fit_output(payload, limits=limits, kind="timeline")
    except (InvestigationCompareError, InvestigationError, OSError, ValueError, TypeError, KeyError) as exc:
        code = str(exc) if isinstance(exc, InvestigationCompareError) else "source_invalid"
        try:
            limits = InvestigationCompareLimits(
                max_events=max_events,
                max_output_chars=max_output_chars,
                max_source_bytes=max_source_bytes,
            )
        except InvestigationCompareError as exc:
            code = str(exc)
            limits = InvestigationCompareLimits()
        if strict:
            raise InvestigationCompareError(code)
        return _error_envelope("timeline", source_kind, code, limits=limits)


def _compare_ids(
    left: InvestigationState,
    right: InvestigationState,
    *,
    limits: InvestigationCompareLimits,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for name in _ENTITY_NAMES:
        left_map = _entity_map(left, name)
        right_map = _entity_map(right, name)
        left_ids = set(left_map)
        right_ids = set(right_map)
        added_all = sorted(right_ids - left_ids)
        removed_all = sorted(left_ids - right_ids)
        changed_all: List[Dict[str, Any]] = []
        for identifier in sorted(left_ids & right_ids):
            before = _signature(name, left_map[identifier])
            after = _signature(name, right_map[identifier])
            fields = sorted(key for key in set(before) | set(after) if before.get(key) != after.get(key))
            if fields:
                changed_all.append({"id": identifier, "fields": fields})
        omitted: Dict[str, int] = {}
        added = added_all[: limits.max_items]
        removed = removed_all[: limits.max_items]
        changed = changed_all[: limits.max_items]
        omitted["added"] = max(0, len(added_all) - len(added))
        omitted["removed"] = max(0, len(removed_all) - len(removed))
        omitted["changed"] = max(0, len(changed_all) - len(changed))
        result[name] = {
            "left_count": len(left_map),
            "right_count": len(right_map),
            "delta": len(right_map) - len(left_map),
            "added": added,
            "removed": removed,
            "changed": changed,
            "omitted": omitted,
        }
    return result


def _outcome_transitions(left: InvestigationState, right: InvestigationState, *, limits: InvestigationCompareLimits) -> Tuple[List[Dict[str, Any]], int]:
    transitions: List[Dict[str, Any]] = []
    for name, event_kind, field, default in (
        ("hypotheses", "hypothesis", "status", "open"),
        ("executions", "execution", "outcome", "unknown"),
        ("findings", "finding", "outcome", "unknown"),
    ):
        before = _entity_map(left, name)
        after = _entity_map(right, name)
        for identifier in sorted(set(before) & set(after)):
            old = _text(before[identifier].get(field) or default, limit=128).lower()
            new = _text(after[identifier].get(field) or default, limit=128).lower()
            if old != new:
                _append_capped(
                    transitions,
                    {"kind": event_kind, "id": identifier, "from": old, "to": new},
                    limit=limits.max_items,
                    omitted={},
                    key="transitions",
                )
    total = sum(
        1
        for name, _event_kind, field, default in (
            ("hypotheses", "hypothesis", "status", "open"),
            ("executions", "execution", "outcome", "unknown"),
            ("findings", "finding", "outcome", "unknown"),
        )
        for identifier in set(_entity_map(left, name)) & set(_entity_map(right, name))
        if _text(_entity_map(left, name)[identifier].get(field) or default, limit=128).lower()
        != _text(_entity_map(right, name)[identifier].get(field) or default, limit=128).lower()
    )
    return transitions, max(0, total - len(transitions))


def _knowledge_links(left: InvestigationState, right: InvestigationState, *, limits: InvestigationCompareLimits) -> Dict[str, Any]:
    def links(state: InvestigationState) -> Dict[str, Mapping[str, Any]]:
        return _entity_map(state, "knowledge_candidates")

    before = links(left)
    after = links(right)
    added_all = sorted(set(after) - set(before))
    removed_all = sorted(set(before) - set(after))
    changed_all: List[Dict[str, Any]] = []
    for identifier in sorted(set(before) & set(after)):
        old = _signature("knowledge_candidates", before[identifier])
        new = _signature("knowledge_candidates", after[identifier])
        fields = sorted(key for key in set(old) | set(new) if old.get(key) != new.get(key))
        if fields:
            changed_all.append({"candidate_id": identifier, "fields": fields})
    return {
        "left_count": len(before),
        "right_count": len(after),
        "added": added_all[: limits.max_items],
        "removed": removed_all[: limits.max_items],
        "changed": changed_all[: limits.max_items],
        "omitted": {
            "added": max(0, len(added_all) - limits.max_items),
            "removed": max(0, len(removed_all) - limits.max_items),
            "changed": max(0, len(changed_all) - limits.max_items),
        },
    }


def compare_investigations(
    left_source: Union[InvestigationState, InvestigationStore, Mapping[str, Any], str, Path],
    right_source: Union[InvestigationState, InvestigationStore, Mapping[str, Any], str, Path],
    *,
    max_items: int = MAX_COMPARE_ITEMS,
    max_output_chars: int = MAX_COMPARE_OUTPUT_CHARS,
    max_source_bytes: int = MAX_COMPARE_SOURCE_BYTES,
    strict: bool = False,
) -> Dict[str, Any]:
    """Compare two validated investigations structurally and deterministically."""

    left_kind = _source_kind(left_source)
    right_kind = _source_kind(right_source)
    try:
        limits = InvestigationCompareLimits(
            max_items=max_items,
            max_output_chars=max_output_chars,
            max_source_bytes=max_source_bytes,
        )
        left, left_kind = _load_state(left_source, limits=limits)
        right, right_kind = _load_state(right_source, limits=limits)
        transitions, transition_omitted = _outcome_transitions(left, right, limits=limits)
        left_cov = _coverage_metrics(left)
        right_cov = _coverage_metrics(right)
        left_limits = _limitation_metrics(left)
        right_limits = _limitation_metrics(right)
        left_usage = {
            name: left.budget_usage.get(name, 0)
            for name in _BUDGET_USAGE_NAMES
        }
        right_usage = {
            name: right.budget_usage.get(name, 0)
            for name in _BUDGET_USAGE_NAMES
        }
        payload: Dict[str, Any] = {
            "schema_version": COMPARE_SCHEMA_VERSION,
            "kind": "compare",
            "status": "ok",
            "valid": True,
            "left": {
                "source_kind": left_kind,
                "investigation_id": _id(left.investigation_id),
                "revision": left.revision,
                "status": left.status,
            },
            "right": {
                "source_kind": right_kind,
                "investigation_id": _id(right.investigation_id),
                "revision": right.revision,
                "status": right.status,
            },
            "revision_delta": right.revision - left.revision,
            "status_changed": left.status != right.status,
            "counts": {
                name: {
                    "left": len(_entity_items(left, name)),
                    "right": len(_entity_items(right, name)),
                    "delta": len(_entity_items(right, name)) - len(_entity_items(left, name)),
                }
                for name in _ENTITY_NAMES
            },
            "ids": _compare_ids(left, right, limits=limits),
            "outcome_transitions": transitions,
            "coverage": {
                "left": left_cov,
                "right": right_cov,
                "delta": _delta(left_cov, right_cov, left_cov.keys()),
            },
            "limitations": {
                "left": left_limits,
                "right": right_limits,
                "delta": _delta(left_limits, right_limits, left_limits.keys()),
            },
            "omissions": _delta(left_cov, right_cov, ("omitted",)),
            "truncations": _delta(left_cov, right_cov, ("truncated",)),
            "budget": {
                "usage": _delta(left_usage, right_usage, _BUDGET_USAGE_NAMES),
                "policy_changed": {
                    name: left.budget_policy.get(name) != right.budget_policy.get(name)
                    for name in _BUDGET_POLICY_NAMES
                },
            },
            "stop": {
                "left": {
                    "present": bool(left.stop_reason),
                    "kind": _text(_mapping(left.stop_reason).get("kind"), limit=128),
                },
                "right": {
                    "present": bool(right.stop_reason),
                    "kind": _text(_mapping(right.stop_reason).get("kind"), limit=128),
                },
                "changed": (
                    bool(left.stop_reason) != bool(right.stop_reason)
                    or _mapping(left.stop_reason).get("kind")
                    != _mapping(right.stop_reason).get("kind")
                ),
            },
            "knowledge_links": _knowledge_links(left, right, limits=limits),
            "omitted": {"events": 0, "items": 0, "transitions": transition_omitted},
            "truncated": transition_omitted > 0,
        }
        # Carry per-collection omissions into one bounded top-level indicator.
        payload["omitted"]["items"] = sum(
            sum(int(value or 0) for value in item["omitted"].values())
            for item in payload["ids"].values()
        )
        payload["omitted"]["items"] += sum(
            int(value or 0)
            for value in payload["knowledge_links"]["omitted"].values()
        )
        payload["truncated"] = payload["truncated"] or payload["omitted"]["items"] > 0
        return _fit_output(payload, limits=limits, kind="compare")
    except (InvestigationCompareError, InvestigationError, OSError, ValueError, TypeError, KeyError) as exc:
        code = str(exc) if isinstance(exc, InvestigationCompareError) else "source_invalid"
        try:
            limits = InvestigationCompareLimits(
                max_items=max_items,
                max_output_chars=max_output_chars,
                max_source_bytes=max_source_bytes,
            )
        except InvestigationCompareError as limit_exc:
            code = str(limit_exc)
            limits = InvestigationCompareLimits()
        if strict:
            raise InvestigationCompareError(code)
        envelope = _error_envelope("compare", left_kind + ":" + right_kind, code, limits=limits)
        envelope["left_source_kind"] = left_kind
        envelope["right_source_kind"] = right_kind
        return _fit_output(envelope, limits=limits, kind="compare")


# Read-only aliases for hosts that use shorter operation names.
investigation_timeline = timeline_investigation
compare_investigation = compare_investigations


__all__ = [
    "COMPARE_SCHEMA_VERSION",
    "InvestigationCompareError",
    "InvestigationCompareLimits",
    "MAX_COMPARE_ITEMS",
    "MAX_COMPARE_OUTPUT_CHARS",
    "MAX_COMPARE_SOURCE_BYTES",
    "MAX_TIMELINE_EVENTS",
    "TIMELINE_SCHEMA_VERSION",
    "compare_investigation",
    "compare_investigations",
    "investigation_timeline",
    "timeline_investigation",
]
