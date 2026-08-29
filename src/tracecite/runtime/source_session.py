"""Compatibility functions for the formal InvestigationState SourceSession contract.

SourceSession persistence and validation are owned by ``investigation.py``.
This module keeps the historical function-style API without mutating
``InvestigationState`` or ``InvestigationStore`` at import time.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from .investigation import (
    SOURCE_SESSION_STATUSES,
    InvestigationStore,
)


def register_source_session(store: InvestigationStore, source_id: str, **kwargs: Any) -> Dict[str, Any]:
    return store.register_source_session(source_id, **kwargs)


def get_source_session(store: InvestigationStore, session_id: str) -> Dict[str, Any]:
    return store.get_source_session(session_id)


def list_source_sessions(store: InvestigationStore) -> list[Dict[str, Any]]:
    return store.list_source_sessions()


def inspect_source_session(
    store: InvestigationStore,
    session_id: str,
    *,
    identity: Optional[Mapping[str, Any]] = None,
    fingerprint: Optional[str] = None,
) -> Dict[str, Any]:
    return store.inspect_source_session(
        session_id, identity=identity, fingerprint=fingerprint
    )


def update_source_session_coverage(
    store: InvestigationStore, session_id: str, coverage: Mapping[str, Any]
) -> Dict[str, Any]:
    return store.update_source_session_coverage(session_id, coverage)


def invalidate_source_session(
    store: InvestigationStore, session_id: str, reason: str, *, status: str = "needs_revalidation"
) -> Dict[str, Any]:
    return store.invalidate_source_session(session_id, reason, status=status)


def refresh_source_session(store: InvestigationStore, session_id: str, **kwargs: Any) -> Dict[str, Any]:
    return store.refresh_source_session(session_id, **kwargs)


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
