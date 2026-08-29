"""Domain-neutral navigation hints for scoped-identity ambiguity.

The detector is deliberately mechanical and conservative.  It only observes
already-visible raw evidence and reports when several sibling entity names
share the same scope and generated-name family.  It does not claim that any
identifier is duplicated, that correlation is wrong, or that a particular
root cause follows from the fan-out.

These hints are intended for Agent transport only: they make a potentially
important scope distinction visible without converting it into canonical
Evidence or causal inference.
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
_TRAILING_NUMBER_RE = re.compile(r"(?:[-_.])\d{2,}$")
_TRAILING_HEX_RE = re.compile(r"(?:[-_.])[0-9a-f]{8,}$", re.IGNORECASE)
_UUID_SUFFIX_RE = re.compile(
    r"(?:[-_.])[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

DEFAULT_AMBIGUITY_HINT_LIMIT = 3
DEFAULT_AMBIGUITY_MEMBER_LIMIT = 6


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


def scoped_identity_fanout_hints(
    text: str,
    *,
    limit: int = DEFAULT_AMBIGUITY_HINT_LIMIT,
    member_limit: int = DEFAULT_AMBIGUITY_MEMBER_LIMIT,
    minimum_siblings: int = 3,
) -> list[dict[str, Any]]:
    """Find repeated sibling entity families in already-visible raw text.

    Example observation (domain-independent)::

        resource.example/widget-1001
        resource.example/widget-1002
        resource.example/widget-1003

    This is reported as a scope fan-out.  The caller may use it as a navigation
    cue to keep scope attached to identifiers while correlating evidence.  No
    assertion is made that the sibling entities share any local ID.
    """

    if limit < 1 or member_limit < 1 or minimum_siblings < 2:
        raise ValueError("ambiguity hint bounds are invalid")
    if not isinstance(text, str) or not text:
        return []

    groups: dict[tuple[str, str], set[str]] = defaultdict(set)
    for match in _SCOPED_TOKEN_RE.finditer(text):
        scope = match.group("scope")
        member = match.group("member").rstrip(".,;:)]}")
        family = _family(member)
        if not family:
            continue
        groups[(scope, family)].add(member)

    candidates: list[dict[str, Any]] = []
    for (scope, family), members in groups.items():
        ordered = sorted(members)
        if len(ordered) < minimum_siblings:
            continue
        candidates.append(
            {
                "kind": "sibling_scope_fanout",
                "scope": f"{scope}/",
                "family": f"{family}-*",
                "member_count": len(ordered),
                "members": ordered[:member_limit],
                "navigation_query": f"{scope}/{family}-",
            }
        )

    candidates.sort(
        key=lambda item: (
            -int(item["member_count"]),
            str(item["scope"]),
            str(item["family"]),
        )
    )
    return candidates[:limit]


__all__ = [
    "DEFAULT_AMBIGUITY_HINT_LIMIT",
    "DEFAULT_AMBIGUITY_MEMBER_LIMIT",
    "scoped_identity_fanout_hints",
]
