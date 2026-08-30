"""Mechanical retrieval-session telemetry for Agent observability.

This module records only retrieval history: call counts, evidence novelty, exact
query repetition, and a bounded recent search window.  It deliberately does not
infer evidence sufficiency, root cause, investigation completeness, or whether
an Agent should stop.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from tracecite_core.state_file import state_lock

from .retrieval_session import RetrievalSessionStore


_SCHEMA_VERSION = 1
_RECENT_WINDOW = 10
_MAX_QUERY_FINGERPRINTS = 512


def _fingerprint(*, source: str, query: str, regex: bool) -> str:
    raw = f"{source}\0{int(regex)}\0{query}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _atomic_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.stem}.", suffix=".tmp", dir=path.parent, text=True
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@dataclass(frozen=True)
class RetrievalSessionTelemetry:
    """Persist bounded mechanical retrieval history beside RetrievalSession."""

    session: RetrievalSessionStore

    @property
    def path(self) -> Path:
        return self.session.path.with_name(f"{self.session.path.stem}.telemetry.json")

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {
                "schema_version": _SCHEMA_VERSION,
                "search_calls": 0,
                "expand_calls": 0,
                "exact_duplicate_queries": 0,
                "query_fingerprints": [],
                "recent_searches": [],
            }
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if int(payload.get("schema_version") or 0) != _SCHEMA_VERSION:
            raise ValueError("unsupported RetrievalSessionTelemetry schema version")
        return dict(payload)

    def record_search(
        self,
        *,
        source: str,
        query: str,
        regex: bool,
        result: Mapping[str, Any],
    ) -> dict[str, int]:
        coverage = result.get("coverage") or {}
        coverage = coverage if isinstance(coverage, Mapping) else {}
        status = str(result.get("status") or "").strip().lower()
        new_evidence = int(coverage.get("new_evidence") or 0)
        repeated_evidence = int(coverage.get("repeated_evidence") or 0)
        if new_evidence > 0:
            outcome = "new"
        elif repeated_evidence > 0:
            outcome = "repeated_only"
        elif status == "no_match":
            outcome = "no_match"
        else:
            outcome = "other"

        fingerprint = _fingerprint(source=source, query=query, regex=regex)
        with state_lock(self.path):
            payload = self._load()
            seen = [str(item) for item in payload.get("query_fingerprints") or []]
            duplicate = fingerprint in set(seen)
            if not duplicate:
                seen.append(fingerprint)
                seen = seen[-_MAX_QUERY_FINGERPRINTS:]
            recent = [str(item) for item in payload.get("recent_searches") or []]
            recent.append(outcome)
            recent = recent[-_RECENT_WINDOW:]
            payload.update(
                search_calls=int(payload.get("search_calls") or 0) + 1,
                exact_duplicate_queries=int(payload.get("exact_duplicate_queries") or 0)
                + int(duplicate),
                query_fingerprints=seen,
                recent_searches=recent,
            )
            _atomic_write(self.path, payload)
            return self._summary(payload)

    def record_expand(self) -> dict[str, int]:
        with state_lock(self.path):
            payload = self._load()
            payload["expand_calls"] = int(payload.get("expand_calls") or 0) + 1
            _atomic_write(self.path, payload)
            return self._summary(payload)

    def summary(self) -> dict[str, int]:
        with state_lock(self.path):
            return self._summary(self._load())

    def _summary(self, payload: Mapping[str, Any]) -> dict[str, int]:
        recent = [str(item) for item in payload.get("recent_searches") or []]
        # RetrievalSession remains the source of truth for unique Evidence identities.
        unique_evidence_seen = len(self.session.load().seen_evidence)
        return {
            "search_calls": int(payload.get("search_calls") or 0),
            "expand_calls": int(payload.get("expand_calls") or 0),
            "unique_evidence_seen": unique_evidence_seen,
            "exact_duplicate_queries": int(payload.get("exact_duplicate_queries") or 0),
            "recent_window": len(recent),
            "recent_searches_with_new_evidence": sum(item == "new" for item in recent),
            "recent_repeated_only_searches": sum(item == "repeated_only" for item in recent),
            "recent_no_match_searches": sum(item == "no_match" for item in recent),
        }


__all__ = ["RetrievalSessionTelemetry"]
