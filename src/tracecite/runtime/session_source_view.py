"""Session-scoped immutable source-view contract.

A RetrievalSession is the stability boundary for Agent evidence access. The
first access to a logical source binds that session to one immutable source
version. Later calls in the same session reuse the exact version even if the
original mutable/live path changes.

The underlying persistence implementation historically used the
``QuestionSourceView`` name. ``SessionSourceView`` is the canonical public name;
the old class remains a compatibility alias until the internal persistence file
format is migrated.
"""

from __future__ import annotations

from pathlib import Path

from .retrieval_session import RetrievalSessionStore
from .source_versions import (
    QuestionSourceView,
    SourceFingerprint,
    SourceSegment,
    SourceVersionStore,
)


SessionSourceView = QuestionSourceView


class SessionSourceVersionStore(SourceVersionStore):
    """SourceVersionStore with RetrievalSession terminology at its public edge."""

    def __init__(self, root: str | Path, *, session_id: str = "") -> None:
        super().__init__(root, question_id=session_id)
        self.session_id = str(session_id or "").strip()

    @classmethod
    def for_session(cls, session: RetrievalSessionStore) -> "SessionSourceVersionStore":
        return cls(session.root, session_id=session.context_id)


__all__ = [
    "SessionSourceView",
    "SessionSourceVersionStore",
    "SourceFingerprint",
    "SourceSegment",
]
