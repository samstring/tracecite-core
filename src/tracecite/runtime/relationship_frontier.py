from __future__ import annotations

import copy
import re
from typing import Any, Mapping

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


def _key_score(key: str) -> int:
    normalized = re.sub(r"[^a-z0-9]", "", str(key or "").casefold())
    if not normalized:
        return 0
    if normalized.endswith(("uuid", "uid")):
        return 6
    if normalized.endswith("id"):
        return 5
    if normalized.endswith(("ref", "reference")):
        return 4
    if normalized.endswith("key"):
        return 3
    if any(
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
    ):
        return 2
    return 0


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
    """Extract bounded reference-like key/value candidates from visible Evidence.

    This is lexical navigation only. It does not decide that a field is an
    identity key, that two records refer to the same entity, or that a relation
    is causal. The returned values are merely good exact-search frontiers.
    """

    if limit < 1:
        raise ValueError("relationship candidate limit must be positive")
    if not isinstance(text, str) or not text:
        return []

    found: dict[tuple[str, str], dict[str, Any]] = {}
    for ordinal, match in enumerate(_KEY_VALUE_RE.finditer(text), start=1):
        key = match.group("key")
        value = match.group("value").rstrip(".,;:)]}")
        score = _key_score(key)
        if score <= 0:
            continue
        if len(value) < 4 or value.casefold() in _IGNORED_VALUES or value.isdigit():
            continue
        identity = (key.casefold(), value)
        row = found.get(identity)
        line = _line_for_offset(text, match.start())
        if row is None:
            found[identity] = {
                "kind": "reference_candidate",
                "key": key,
                "value": value,
                "visible_lines": [line] if line is not None else [],
                "visible_occurrences": 1,
                "navigation_score": score,
                "ordinal": ordinal,
            }
        else:
            row["visible_occurrences"] = int(row["visible_occurrences"]) + 1
            if line is not None and line not in row["visible_lines"]:
                row["visible_lines"].append(line)

    ordered = sorted(
        found.values(),
        key=lambda item: (
            -int(item["navigation_score"]),
            -int(item["visible_occurrences"]),
            int(item["ordinal"]),
            str(item["key"]),
            str(item["value"]),
        ),
    )[:limit]
    for item in ordered:
        item.pop("ordinal", None)
        item["recommended_action"] = {
            "operation": "search",
            "query": item["value"],
            "purpose": "resolve_reference_occurrences",
            "reference_key": item["key"],
        }
        item["note"] = (
            "Lexical relationship frontier only. Search this exact observed value to resolve "
            "where else it occurs; do not treat the field name or co-occurrence as identity or causality proof."
        )
    return ordered


def attach_relationship_frontier(
    result: RetrievalResult,
    *,
    limit: int = 6,
) -> RetrievalResult:
    """Attach relation-navigation candidates to materialized expand results."""

    if not isinstance(result, RetrievalResult):
        raise TypeError("attach_relationship_frontier requires RetrievalResult")
    if result.operation != "expand":
        return result
    canonical = copy.deepcopy(dict(result.canonical_result))
    data = copy.deepcopy(dict(canonical.get("data") or {}))
    text = data.get("text")
    candidates = relationship_candidates(text, limit=limit) if isinstance(text, str) else []
    if not candidates:
        return result

    data["relationship_frontier"] = candidates
    data["relationship_frontier_note"] = (
        "Mechanical reference navigation only. These observed key/value pairs are candidates "
        "for exact occurrence resolution, not semantic or causal conclusions."
    )
    data["relationship_action"] = dict(candidates[0]["recommended_action"])
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
