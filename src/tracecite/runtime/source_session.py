"""Reusable source-recognition state for long-running investigations.

A SourceSession records what TraceCite already knows about one logical input
source so an Agent can decide whether to reuse that recognition or perform
additional orientation.  TraceCite stores and validates state; it does not
automatically run probe/sample/survey or choose an investigation strategy.

``source_sessions`` is an additive InvestigationState v1 field.  Older v1
state documents remain readable and are interpreted as having no sessions.
"""

from __future__ import annotations

import copy
import json
import math
import uuid
from typing import Any, Dict, List, Mapping, Optional

from . import investigation as _investigation
from .investigation import InvestigationError, InvestigationState, InvestigationStore


SOURCE_SESSION_STATUSES = frozenset(
    {"unknown", "known", "changed", "needs_revalidation"}
)
MAX_SOURCE_SESSIONS = 100


def _now_iso() -> str:
    return _investigation._now_iso()


def _required_text(value: Any, *, field_name: str, limit: int = 4096) -> str:
    return _investigation._required_text(value, field_name=field_name, limit=limit)


def _optional_text(value: Any, *, field_name: str, limit: int = 4096) -> str:
    return _investigation._optional_text(value, field_name=field_name, limit=limit)


def _json_object(value: Any, *, field_name: str) -> Dict[str, Any]:
    return _investigation._json_object(value, field_name=field_name)


def _validate_id(value: Any, *, field_name: str) -> str:
    return _investigation._validate_id(value, field_name=field_name)


def _canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _confidence(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvestigationError("source_session.confidence 必须是 0 到 1 之间的数字")
    resolved = float(value)
    if not math.isfinite(resolved) or resolved < 0.0 or resolved > 1.0:
        raise InvestigationError("source_session.confidence 必须是 0 到 1 之间的数字")
    return resolved


def _normalize_session(item: Mapping[str, Any], *, index: int = 0) -> Dict[str, Any]:
    if not isinstance(item, Mapping):
        raise InvestigationError(f"source_sessions[{index}] 必须是对象")
    allowed = {
        "id",
        "source_id",
        "identity",
        "fingerprint",
        "source_type",
        "format",
        "segmenter",
        "extension",
        "recognition_status",
        "confidence",
        "coverage",
        "invalidation_reason",
        "created_at",
        "updated_at",
    }
    unsupported = set(item) - allowed
    if unsupported:
        raise InvestigationError(
            f"source_sessions[{index}] 含有不支持的字段: "
            + ", ".join(sorted(str(value) for value in unsupported))
        )
    status = str(item.get("recognition_status") or "unknown").strip().lower()
    if status not in SOURCE_SESSION_STATUSES:
        raise InvestigationError(f"未知 source session status: {status!r}")
    return {
        "id": _validate_id(item.get("id"), field_name="source_session.id"),
        "source_id": _required_text(
            item.get("source_id"), field_name="source_session.source_id", limit=512
        ),
        "identity": _json_object(
            item.get("identity") or {}, field_name="source_session.identity"
        ),
        "fingerprint": _optional_text(
            item.get("fingerprint"), field_name="source_session.fingerprint", limit=512
        ),
        "source_type": _optional_text(
            item.get("source_type"), field_name="source_session.source_type", limit=256
        ),
        "format": _optional_text(
            item.get("format"), field_name="source_session.format", limit=256
        ),
        "segmenter": _optional_text(
            item.get("segmenter"), field_name="source_session.segmenter", limit=256
        ),
        "extension": _optional_text(
            item.get("extension"), field_name="source_session.extension", limit=256
        ),
        "recognition_status": status,
        "confidence": _confidence(item.get("confidence")),
        "coverage": _json_object(
            item.get("coverage") or {}, field_name="source_session.coverage"
        ),
        "invalidation_reason": _optional_text(
            item.get("invalidation_reason"),
            field_name="source_session.invalidation_reason",
        ),
        "created_at": _required_text(
            item.get("created_at"), field_name="source_session.created_at", limit=128
        ),
        "updated_at": _required_text(
            item.get("updated_at"), field_name="source_session.updated_at", limit=128
        ),
    }


def _normalize_sessions(raw: Any) -> List[Dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise InvestigationError("source_sessions 必须是数组")
    if len(raw) > MAX_SOURCE_SESSIONS:
        raise InvestigationError("source_sessions 数量超过限制")
    result: List[Dict[str, Any]] = []
    ids = set()
    source_ids = set()
    for index, item in enumerate(raw):
        normalized = _normalize_session(item, index=index)
        if normalized["id"] in ids:
            raise InvestigationError(f"source session id 重复: {normalized['id']}")
        if normalized["source_id"] in source_ids:
            raise InvestigationError(
                f"source session source_id 重复: {normalized['source_id']}"
            )
        ids.add(normalized["id"])
        source_ids.add(normalized["source_id"])
        result.append(normalized)
    return result


# Additive InvestigationState v1 persistence.  Keep the base state validator
# unchanged so old v1 fixtures remain authoritative for all existing fields.
_ORIGINAL_TO_DICT = InvestigationState.to_dict
_ORIGINAL_FROM_DICT = InvestigationState.from_dict.__func__


def _to_dict_with_source_sessions(self: InvestigationState) -> Dict[str, Any]:
    payload = _ORIGINAL_TO_DICT(self)
    payload["source_sessions"] = copy.deepcopy(
        _normalize_sessions(getattr(self, "source_sessions", []))
    )
    return payload


@classmethod
def _from_dict_with_source_sessions(
    cls: type[InvestigationState], raw: Mapping[str, Any]
) -> InvestigationState:
    sessions = _normalize_sessions(raw.get("source_sessions"))
    state = _ORIGINAL_FROM_DICT(cls, raw)
    state.source_sessions = copy.deepcopy(sessions)  # type: ignore[attr-defined]
    return state


InvestigationState.to_dict = _to_dict_with_source_sessions  # type: ignore[assignment]
InvestigationState.from_dict = _from_dict_with_source_sessions  # type: ignore[assignment]


def _sessions(state: InvestigationState) -> List[Dict[str, Any]]:
    sessions = getattr(state, "source_sessions", None)
    if sessions is None:
        sessions = []
        state.source_sessions = sessions  # type: ignore[attr-defined]
    return sessions


def _find_session(state: InvestigationState, session_id: str) -> Dict[str, Any]:
    for item in _sessions(state):
        if item["id"] == session_id:
            return item
    raise InvestigationError(f"未知 source session: {session_id}")


def register_source_session(
    self: InvestigationStore,
    source_id: str,
    *,
    identity: Optional[Mapping[str, Any]] = None,
    fingerprint: str = "",
    source_type: str = "",
    format: str = "",
    segmenter: str = "",
    extension: str = "",
    recognition_status: str = "known",
    confidence: Optional[float] = None,
    coverage: Optional[Mapping[str, Any]] = None,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Register recognition for one logical source within this investigation."""

    status = str(recognition_status or "").strip().lower()
    now = _now_iso()
    session = _normalize_session(
        {
            "id": session_id or f"S{uuid.uuid4().hex[:12]}",
            "source_id": source_id,
            "identity": dict(identity or {}),
            "fingerprint": fingerprint,
            "source_type": source_type,
            "format": format,
            "segmenter": segmenter,
            "extension": extension,
            "recognition_status": status,
            "confidence": confidence,
            "coverage": dict(coverage or {}),
            "invalidation_reason": "",
            "created_at": now,
            "updated_at": now,
        }
    )

    def mutate(state: InvestigationState) -> None:
        self._require_active(state)
        existing = _sessions(state)
        if len(existing) >= MAX_SOURCE_SESSIONS:
            raise InvestigationError("source_sessions 数量超过限制")
        if any(item["id"] == session["id"] for item in existing):
            raise InvestigationError(f"source session id 已存在: {session['id']}")
        if any(item["source_id"] == session["source_id"] for item in existing):
            raise InvestigationError(
                f"source session source_id 已存在: {session['source_id']}"
            )
        existing.append(copy.deepcopy(session))

    self._update(mutate)
    return copy.deepcopy(session)


def get_source_session(self: InvestigationStore, session_id: str) -> Dict[str, Any]:
    resolved = _validate_id(session_id, field_name="source_session.id")
    return copy.deepcopy(_find_session(self.load(), resolved))


def list_source_sessions(self: InvestigationStore) -> List[Dict[str, Any]]:
    return copy.deepcopy(_sessions(self.load()))


def inspect_source_session(
    self: InvestigationStore,
    session_id: str,
    *,
    identity: Optional[Mapping[str, Any]] = None,
    fingerprint: Optional[str] = None,
) -> Dict[str, Any]:
    """Return reusable/changed state without choosing an Agent strategy.

    ``identity`` should contain stable logical-source identity such as device,
    app, process/launch and stream type.  A growing live-log content digest
    should not be used as this identity.  ``fingerprint`` is optional and is
    compared only when the caller supplies one.
    """

    session = get_source_session(self, session_id)
    reasons: List[str] = []
    if identity is not None:
        current_identity = _json_object(identity, field_name="source_session.identity")
        if _canonical(current_identity) != _canonical(session["identity"]):
            reasons.append("identity_changed")
    if fingerprint is not None:
        current_fingerprint = _optional_text(
            fingerprint, field_name="source_session.fingerprint", limit=512
        )
        if current_fingerprint != session["fingerprint"]:
            reasons.append("fingerprint_changed")
    persisted_status = session["recognition_status"]
    changed = bool(reasons) or persisted_status in {"changed", "needs_revalidation"}
    reusable = persisted_status == "known" and not changed
    effective_status = "changed" if reasons else persisted_status
    return {
        "session_id": session["id"],
        "source_id": session["source_id"],
        "status": effective_status,
        "source_changed": changed,
        "reuse": reusable,
        "reasons": reasons
        or ([session["invalidation_reason"]] if session["invalidation_reason"] else []),
        "format": session["format"],
        "segmenter": session["segmenter"],
        "extension": session["extension"],
        "confidence": session["confidence"],
        "coverage": copy.deepcopy(session["coverage"]),
    }


def update_source_session_coverage(
    self: InvestigationStore,
    session_id: str,
    coverage: Mapping[str, Any],
) -> Dict[str, Any]:
    """Advance live-source coverage without invalidating recognition."""

    resolved = _validate_id(session_id, field_name="source_session.id")
    resolved_coverage = _json_object(coverage, field_name="source_session.coverage")

    def mutate(state: InvestigationState) -> Dict[str, Any]:
        self._require_active(state)
        session = _find_session(state, resolved)
        session["coverage"] = copy.deepcopy(resolved_coverage)
        session["updated_at"] = _now_iso()
        return copy.deepcopy(session)

    _, result = self._update(mutate)
    return result


def invalidate_source_session(
    self: InvestigationStore,
    session_id: str,
    reason: str,
    *,
    status: str = "needs_revalidation",
) -> Dict[str, Any]:
    resolved = _validate_id(session_id, field_name="source_session.id")
    resolved_status = str(status or "").strip().lower()
    if resolved_status not in {"changed", "needs_revalidation"}:
        raise InvestigationError(
            "invalidate_source_session status 必须是 changed / needs_revalidation"
        )
    resolved_reason = _required_text(
        reason, field_name="source_session.invalidation_reason"
    )

    def mutate(state: InvestigationState) -> Dict[str, Any]:
        self._require_active(state)
        session = _find_session(state, resolved)
        session["recognition_status"] = resolved_status
        session["invalidation_reason"] = resolved_reason
        session["updated_at"] = _now_iso()
        return copy.deepcopy(session)

    _, result = self._update(mutate)
    return result


def refresh_source_session(
    self: InvestigationStore,
    session_id: str,
    *,
    identity: Optional[Mapping[str, Any]] = None,
    fingerprint: Optional[str] = None,
    source_type: Optional[str] = None,
    format: Optional[str] = None,
    segmenter: Optional[str] = None,
    extension: Optional[str] = None,
    confidence: Optional[float] = None,
    coverage: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Record successful re-recognition and make a session reusable again."""

    resolved = _validate_id(session_id, field_name="source_session.id")

    def mutate(state: InvestigationState) -> Dict[str, Any]:
        self._require_active(state)
        session = _find_session(state, resolved)
        if identity is not None:
            session["identity"] = _json_object(
                identity, field_name="source_session.identity"
            )
        if fingerprint is not None:
            session["fingerprint"] = _optional_text(
                fingerprint, field_name="source_session.fingerprint", limit=512
            )
        for key, value in (
            ("source_type", source_type),
            ("format", format),
            ("segmenter", segmenter),
            ("extension", extension),
        ):
            if value is not None:
                session[key] = _optional_text(
                    value, field_name=f"source_session.{key}", limit=256
                )
        if confidence is not None:
            session["confidence"] = _confidence(confidence)
        if coverage is not None:
            session["coverage"] = _json_object(
                coverage, field_name="source_session.coverage"
            )
        session["recognition_status"] = "known"
        session["invalidation_reason"] = ""
        session["updated_at"] = _now_iso()
        return copy.deepcopy(session)

    _, result = self._update(mutate)
    return result


InvestigationStore.register_source_session = register_source_session  # type: ignore[attr-defined]
InvestigationStore.get_source_session = get_source_session  # type: ignore[attr-defined]
InvestigationStore.list_source_sessions = list_source_sessions  # type: ignore[attr-defined]
InvestigationStore.inspect_source_session = inspect_source_session  # type: ignore[attr-defined]
InvestigationStore.update_source_session_coverage = update_source_session_coverage  # type: ignore[attr-defined]
InvestigationStore.invalidate_source_session = invalidate_source_session  # type: ignore[attr-defined]
InvestigationStore.refresh_source_session = refresh_source_session  # type: ignore[attr-defined]


__all__ = [
    "SOURCE_SESSION_STATUSES",
    "register_source_session",
    "get_source_session",
    "list_source_sessions",
    "inspect_source_session",
    "update_source_session_coverage",
    "invalidate_source_session",
    "refresh_source_session",
]
