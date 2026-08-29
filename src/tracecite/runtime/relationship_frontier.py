"""Bounded extraction of reference-like facts from materialized Evidence.

This module does not create a retrieval frontier. It only reports key/value
references that are literally visible in an already-materialized Evidence
range. The Agent remains responsible for deciding whether any observed
reference matters and what, if anything, to do next.
"""

from __future__ import annotations

import copy
import re
from typing import Any

from .agent_api import RetrievalResult

_KEY_VALUE_RE = re.compile(
    r"(?:^|[\s{,\[])(?:-\s*)?"
    r"[\"']?(?P<key>[A-Za-z_][A-Za-z0-9_.-]{1,63})[\"']?\s*[:=]\s*"
    r"(?P<quote>[\"']?)"
    r"(?P<value>[A-Za-z0-9][A-Za-z0-9_.:@/+-]{2,159})"
    r"(?P=quote)",
    re.MULTILINE,
)
_LINE_PREFIX_RE = re.compile(r"^(?:[^:\s]+:)?(?P<line>[1-9][0-9]*)(?::|\s)")
_IGNORED_VALUES = frozenset(
    {
        "true",
        "false",
        "null",
        "none",
        "nil",
        "unknown",
        "unset",
        "info",
        "debug",
        "warning",
        "warn",
        "error",
    }
)


def _reference_like_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", str(key or "").casefold())
    if not normalized:
        return False
    if normalized.endswith(("uuid", "uid", "id", "ref", "reference", "key")):
        return True
    return any(
        token in normalized
        for token in (
            "target",
            "parent",
            "owner",
            "source",
            "subject",
            "entity",
            "resource",
            "request",
            "trace",
            "span",
        )
    )


def _line_for_offset(text: str, offset: int) -> int | None:
    start = text.rfind("\n", 0, offset) + 1
    end = text.find("\n", offset)
    if end < 0:
        end = len(text)
    match = _LINE_PREFIX_RE.match(text[start:end])
    if match is None:
        return None
    return int(match.group("line"))


def relationship_candidates(text: str, *, limit: int = 6) -> list[dict[str, Any]]:
    """Return bounded observed reference facts in source-occurrence order."""

    if limit < 1:
        raise ValueError("relationship candidate limit must be positive")
    if not isinstance(text, str) or not text:
        return []

    found: dict[tuple[str, str], dict[str, Any]] = {}
    order: list[tuple[str, str]] = []
    for match in _KEY_VALUE_RE.finditer(text):
        key = match.group("key")
        value = match.group("value").rstrip(".,;:)]}")
        if not _reference_like_key(key):
            continue
        if len(value) < 4 or value.casefold() in _IGNORED_VALUES or value.isdigit():
            continue
        identity = (key.casefold(), value)
        line = _line_for_offset(text, match.start())
        row = found.get(identity)
        if row is None:
            if len(order) >= limit:
                continue
            row = {
                "kind": "observed_reference",
                "key": key,
                "value": value,
                "visible_lines": [],
                "visible_occurrences": 0,
            }
            found[identity] = row
            order.append(identity)
        row["visible_occurrences"] = int(row["visible_occurrences"]) + 1
        if line is not None and line not in row["visible_lines"]:
            row["visible_lines"].append(line)

    return [found[key] for key in order]


def attach_relationship_frontier(
    result: RetrievalResult,
    *,
    limit: int = 6,
) -> RetrievalResult:
    """Compatibility name: attach observed references, never a next action."""

    if not isinstance(result, RetrievalResult):
        raise TypeError("attach_relationship_frontier requires RetrievalResult")
    if result.operation != "expand":
        return result
    canonical = copy.deepcopy(dict(result.canonical_result))
    data = copy.deepcopy(dict(canonical.get("data") or {}))
    text = data.get("text")
    observed = relationship_candidates(text, limit=limit) if isinstance(text, str) else []
    if not observed:
        return result

    data["observed_references"] = observed
    data["observed_references_note"] = (
        "Literal reference-like fields observed in this materialized Evidence range. "
        "They are evidence facts only: no identity, causality, importance, or next action "
        "is implied."
    )
    canonical["data"] = data
    return RetrievalResult(
        operation=result.operation,
        status=result.status,
        canonical_result=canonical,
        progress=result.progress,
        new_evidence=result.new_evidence,
        repeated_evidence=result.repeated_evidence,
        stop_reason=result.stop_reason,
    )


__all__ = ["attach_relationship_frontier", "relationship_candidates"]
