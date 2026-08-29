"""Bounded extraction of literal reference and structural relation facts.

This module never creates a retrieval plan. It reports fields and relationships
that are mechanically visible inside an already-materialized Evidence range.
Relationships describe textual structure only (for example, two fields in the
same structured block); they do not establish real-world identity, causality,
importance, or a next action.
"""

from __future__ import annotations

import copy
import hashlib
import json
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
_MATERIALIZED_LINE_RE = re.compile(r"^(?P<line>[1-9][0-9]*):(?P<body>.*)$")
_STRUCTURED_FIELD_RE = re.compile(
    r"^(?P<indent>\s*)(?P<bullet>-\s*)?"
    r"[\"']?(?P<key>[A-Za-z_][A-Za-z0-9_.-]{0,63})[\"']?\s*[:=]\s*"
    r"(?P<quote>[\"']?)"
    r"(?P<value>[A-Za-z0-9][A-Za-z0-9_.:@/+-]{1,255})"
    r"(?P=quote)(?:\s|$)"
)
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
_ANCHOR_KEYS = frozenset(
    {
        "name",
        "namespace",
        "entity",
        "resource",
        "resourcename",
        "pod",
        "podname",
        "container",
        "containername",
        "service",
        "servicename",
    }
)


def _normalize_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(key or "").casefold())


def _reference_like_key(key: str) -> bool:
    normalized = _normalize_key(key)
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


def _anchor_like_key(key: str) -> bool:
    return _normalize_key(key) in _ANCHOR_KEYS


def _line_for_offset(text: str, offset: int) -> int | None:
    start = text.rfind("\n", 0, offset) + 1
    end = text.find("\n", offset)
    if end < 0:
        end = len(text)
    match = _LINE_PREFIX_RE.match(text[start:end])
    if match is None:
        return None
    return int(match.group("line"))


def _clean_value(value: str) -> str:
    return str(value or "").rstrip(".,;:)]}")


def relationship_candidates(text: str, *, limit: int = 6) -> list[dict[str, Any]]:
    """Return bounded observed reference fields in source-occurrence order."""

    if limit < 1:
        raise ValueError("relationship candidate limit must be positive")
    if not isinstance(text, str) or not text:
        return []

    found: dict[tuple[str, str], dict[str, Any]] = {}
    order: list[tuple[str, str]] = []
    for match in _KEY_VALUE_RE.finditer(text):
        key = match.group("key")
        value = _clean_value(match.group("value"))
        if not _reference_like_key(key):
            continue
        if len(value) < 3 or value.casefold() in _IGNORED_VALUES or value.isdigit():
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


def _relation_id(payload: Mapping[str, Any]) -> str:
    stable = {
        "kind": payload.get("kind"),
        "relation": payload.get("relation"),
        "subject": payload.get("subject"),
        "object": payload.get("object"),
    }
    encoded = json.dumps(stable, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "rel:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:20]


def _relation(
    *,
    relation: str,
    subject: Mapping[str, str],
    object_: Mapping[str, str],
    lines: list[int],
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "kind": "observed_structural_relation",
        "relation": relation,
        "subject": dict(subject),
        "object": dict(object_),
        "visible_lines": list(dict.fromkeys(lines)),
    }
    row["relation_id"] = _relation_id(row)
    return row


def relationship_observations(text: str, *, limit: int = 8) -> list[dict[str, Any]]:
    """Return bounded, literal structural relationships from materialized text.

    Two conservative shapes are recognized:
    - multiple reference-like fields on the same materialized source line;
    - a reference-like field following a visible structured entity anchor such
      as ``name:``/``namespace:`` before another anchor starts.

    These are textual associations only. They intentionally do not claim that
    values identify the same real-world object or that one caused another.
    """

    if limit < 1:
        raise ValueError("relationship observation limit must be positive")
    if not isinstance(text, str) or not text:
        return []

    relations: list[dict[str, Any]] = []
    seen: set[str] = set()
    anchor: tuple[str, str, int] | None = None

    def add(row: dict[str, Any]) -> None:
        relation_id = str(row.get("relation_id") or "")
        if not relation_id or relation_id in seen or len(relations) >= limit:
            return
        seen.add(relation_id)
        relations.append(row)

    for raw_line in text.splitlines():
        line_match = _MATERIALIZED_LINE_RE.match(raw_line)
        if line_match is None:
            continue
        line_no = int(line_match.group("line"))
        body = line_match.group("body")
        fields: list[tuple[str, str]] = []
        for match in _KEY_VALUE_RE.finditer(body):
            key = match.group("key")
            value = _clean_value(match.group("value"))
            if len(value) < 2 or value.casefold() in _IGNORED_VALUES:
                continue
            fields.append((key, value))

        reference_fields = [(key, value) for key, value in fields if _reference_like_key(key)]
        if len(reference_fields) >= 2:
            left_key, left_value = reference_fields[0]
            for right_key, right_value in reference_fields[1:]:
                add(
                    _relation(
                        relation="co_observed_on_line",
                        subject={"key": left_key, "value": left_value},
                        object_={"key": right_key, "value": right_value},
                        lines=[line_no],
                    )
                )

        structured = _STRUCTURED_FIELD_RE.match(body)
        if structured is not None:
            key = structured.group("key")
            value = _clean_value(structured.group("value"))
            if _anchor_like_key(key) and value.casefold() not in _IGNORED_VALUES:
                anchor = (key, value, line_no)
            elif anchor is not None and _reference_like_key(key):
                anchor_key, anchor_value, anchor_line = anchor
                if not (anchor_key.casefold() == key.casefold() and anchor_value == value):
                    add(
                        _relation(
                            relation="field_in_same_structured_block",
                            subject={"key": anchor_key, "value": anchor_value},
                            object_={"key": key, "value": value},
                            lines=[anchor_line, line_no],
                        )
                    )

        stripped = body.strip()
        if not stripped or stripped in {"---", "------------------------------"}:
            anchor = None

    return relations


def attach_relationship_frontier(
    result: RetrievalResult,
    *,
    limit: int = 8,
) -> RetrievalResult:
    """Compatibility name: attach observed facts, never a next action."""

    if not isinstance(result, RetrievalResult):
        raise TypeError("attach_relationship_frontier requires RetrievalResult")
    if result.operation != "expand":
        return result
    canonical = copy.deepcopy(dict(result.canonical_result))
    data = copy.deepcopy(dict(canonical.get("data") or {}))
    text = data.get("text")
    observed = relationship_candidates(text, limit=min(limit, 6)) if isinstance(text, str) else []
    relations = relationship_observations(text, limit=limit) if isinstance(text, str) else []
    if not observed and not relations:
        return result

    if observed:
        data["observed_references"] = observed
        data["observed_references_note"] = (
            "Literal reference-like fields observed in this materialized Evidence range. "
            "They are evidence facts only: no identity, causality, importance, or next action "
            "is implied."
        )
    if relations:
        data["observed_relations"] = relations
        data["observed_relations_note"] = (
            "Literal textual-structure relationships observed in this materialized Evidence "
            "range. They describe co-observation or structured-block membership only; they "
            "do not establish real-world identity, causality, importance, or a next action."
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


__all__ = [
    "attach_relationship_frontier",
    "relationship_candidates",
    "relationship_observations",
]
