"""Domain-neutral navigation hints for scoped-identity ambiguity.

The detector is deliberately mechanical and conservative.  It only observes
already-visible raw evidence and reports two kinds of navigation risk:

1. several sibling entity names share the same scope and generated-name family;
2. a locally-shaped ``...ID`` value appears near a scoped entity, but uniqueness
   across sibling scopes/entities has not been established in the visible text.

Neither observation claims that an identifier is duplicated, that correlation
is wrong, or that a particular root cause follows.  These hints are intended
for Agent transport only: they make potentially important scope distinctions
and the smallest useful verification action visible without converting them
into canonical Evidence or causal inference.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any


_SCOPED_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9_.:-])"
    r"(?P<scope>[A-Za-z0-9][A-Za-z0-9_.:-]{1,79})/"
    r"(?P<member>[A-Za-z0-9][A-Za-z0-9_.:@-]{1,159})"
)
_IDENTIFIER_PAIR_RE = re.compile(
    r"(?<![A-Za-z0-9_.-])"
    r"(?P<key>[A-Za-z_][A-Za-z0-9_.-]{1,63})"
    r"\s*[:=]\s*"
    r"(?P<quote>[\"']?)"
    r"(?P<value>[A-Za-z0-9][A-Za-z0-9_.:@/-]{1,159})"
    r"(?P=quote)"
)
_TRAILING_NUMBER_RE = re.compile(r"(?:[-_.])\d{2,}$")
_TRAILING_HEX_RE = re.compile(r"(?:[-_.])[0-9a-f]{8,}$", re.IGNORECASE)
_UUID_SUFFIX_RE = re.compile(
    r"(?:[-_.])[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_UUID_VALUE_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_LONG_HEX_VALUE_RE = re.compile(r"^(?:0x)?[0-9a-f]{16,}$", re.IGNORECASE)

DEFAULT_AMBIGUITY_HINT_LIMIT = 3
DEFAULT_AMBIGUITY_MEMBER_LIMIT = 6
DEFAULT_IDENTITY_PROXIMITY_LINES = 4
_IGNORED_IDENTIFIER_VALUES = frozenset(
    {"true", "false", "null", "none", "nil", "unknown", "unset", "n/a"}
)


def _family(member: str) -> str:
    """Return a conservative generated-name family, or an empty string."""

    value = str(member or "").strip()
    if not value:
        return ""
    for pattern in (_UUID_SUFFIX_RE, _TRAILING_HEX_RE, _TRAILING_NUMBER_RE):
        reduced = pattern.sub("", value)
        if reduced != value and len(reduced) >= 3:
            return reduced
    return ""


def _line_number(text: str, offset: int) -> int:
    """Return a 1-based line number for ``offset`` in an already-visible text."""

    return text.count("\n", 0, offset) + 1


def _local_identifier(key: str, value: str) -> bool:
    """Return whether a key/value is worth a scope-uniqueness verification.

    The detector intentionally recognises only identifier-shaped keys ending in
    ``id`` and skips values that are obviously absent, UUID-shaped, or long
    digest-like hex values.  Short strings and numeric IDs remain eligible
    because their uniqueness is commonly scope-dependent.
    """

    name = str(key or "").strip()
    candidate = str(value or "").strip().strip("\"'")
    if not name.lower().endswith("id"):
        return False
    if len(candidate) < 2 or len(candidate) > 96:
        return False
    if candidate.lower() in _IGNORED_IDENTIFIER_VALUES:
        return False
    if _UUID_VALUE_RE.fullmatch(candidate) or _LONG_HEX_VALUE_RE.fullmatch(candidate):
        return False
    return True


def _scope_uniqueness_hints(
    text: str,
    *,
    member_limit: int,
    proximity_lines: int,
) -> list[dict[str, Any]]:
    """Find local identifiers near scoped entities in the visible raw text.

    This is deliberately an *unverified evidence gap*.  Seeing ``taskID=17``
    near ``worker/a`` is not evidence that task 17 is duplicated.  It only
    means an Agent should not correlate records by ``17`` alone until it has
    searched the source and compared the nearby scoped entities.
    """

    scoped: list[tuple[int, str, str, str]] = []
    for match in _SCOPED_TOKEN_RE.finditer(text):
        scope = match.group("scope")
        member = match.group("member").rstrip(".,;:)]}")
        scoped.append(
            (
                _line_number(text, match.start()),
                scope,
                member,
                f"{scope}/{member}",
            )
        )

    identifiers: list[tuple[int, str, str]] = []
    for match in _IDENTIFIER_PAIR_RE.finditer(text):
        key = match.group("key")
        value = match.group("value").rstrip(".,;:)]}")
        if not _local_identifier(key, value):
            continue
        identifiers.append((_line_number(text, match.start()), key, value))

    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for id_line, key, value in identifiers:
        nearby = [
            row
            for row in scoped
            if abs(row[0] - id_line) <= proximity_lines
        ]
        if not nearby:
            continue
        identity = (key.lower(), value)
        slot = grouped.setdefault(
            identity,
            {
                "identifier_key": key,
                "identifier_value": value,
                "scoped_entities": set(),
                "scopes": set(),
                "lines": set(),
            },
        )
        slot["lines"].add(id_line)
        for entity_line, scope, _member, entity in nearby:
            slot["scoped_entities"].add(entity)
            slot["scopes"].add(f"{scope}/")
            slot["lines"].add(entity_line)

    hints: list[dict[str, Any]] = []
    for item in grouped.values():
        entities = sorted(item["scoped_entities"])
        scopes = sorted(item["scopes"])
        lines = sorted(item["lines"])
        value = str(item["identifier_value"])
        hints.append(
            {
                "kind": "scope_uniqueness_unverified",
                "identifier_key": str(item["identifier_key"]),
                "identifier_value": value,
                "scoped_entities": entities[:member_limit],
                "scopes": scopes[:member_limit],
                "visible_lines": lines[: member_limit * 2],
                "recommended_search": value,
                "recommended_action": {
                    "operation": "search",
                    "query": value,
                    "purpose": "verify_identifier_uniqueness_across_scopes",
                },
                "verification": (
                    "Search this identifier value across the source and compare nearby "
                    "scoped entities. Do not correlate records by this identifier alone "
                    "until uniqueness across relevant scopes/entities is verified."
                ),
            }
        )

    hints.sort(
        key=lambda item: (
            -len(item["scoped_entities"]),
            str(item["identifier_key"]),
            str(item["identifier_value"]),
        )
    )
    return hints


def scoped_identity_fanout_hints(
    text: str,
    *,
    limit: int = DEFAULT_AMBIGUITY_HINT_LIMIT,
    member_limit: int = DEFAULT_AMBIGUITY_MEMBER_LIMIT,
    minimum_siblings: int = 3,
    proximity_lines: int = DEFAULT_IDENTITY_PROXIMITY_LINES,
) -> list[dict[str, Any]]:
    """Find scoped-identity navigation risks in already-visible raw text.

    Actionable ``scope_uniqueness_unverified`` gaps are returned before the
    broader sibling-family fan-out hints so a bounded Agent view prioritises a
    concrete, cheap verification step when one is available.
    """

    if limit < 1 or member_limit < 1 or minimum_siblings < 2 or proximity_lines < 0:
        raise ValueError("ambiguity hint bounds are invalid")
    if not isinstance(text, str) or not text:
        return []

    identity_hints = _scope_uniqueness_hints(
        text,
        member_limit=member_limit,
        proximity_lines=proximity_lines,
    )

    groups: dict[tuple[str, str], set[str]] = defaultdict(set)
    for match in _SCOPED_TOKEN_RE.finditer(text):
        scope = match.group("scope")
        member = match.group("member").rstrip(".,;:)]}")
        family = _family(member)
        if not family:
            continue
        groups[(scope, family)].add(member)

    fanout_hints: list[dict[str, Any]] = []
    for (scope, family), members in groups.items():
        ordered = sorted(members)
        if len(ordered) < minimum_siblings:
            continue
        fanout_hints.append(
            {
                "kind": "sibling_scope_fanout",
                "scope": f"{scope}/",
                "family": f"{family}-*",
                "member_count": len(ordered),
                "members": ordered[:member_limit],
                "navigation_query": f"{scope}/{family}-",
            }
        )

    fanout_hints.sort(
        key=lambda item: (
            -int(item["member_count"]),
            str(item["scope"]),
            str(item["family"]),
        )
    )
    return (identity_hints + fanout_hints)[:limit]


__all__ = [
    "DEFAULT_AMBIGUITY_HINT_LIMIT",
    "DEFAULT_AMBIGUITY_MEMBER_LIMIT",
    "DEFAULT_IDENTITY_PROXIMITY_LINES",
    "scoped_identity_fanout_hints",
]
