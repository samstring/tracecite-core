"""Domain-neutral scoped-identity navigation and verification.

This module performs mechanical evidence-integrity checks only. It may surface
that a local-looking identifier is attached to a scoped entity and that sibling
entities from the same scope/family coexist in the same source. It never claims
that siblings reuse the identifier and never declares a root cause.
"""

from __future__ import annotations

import hashlib
import io
import os
import re
from collections import defaultdict, deque
from pathlib import Path
from typing import Any


_SCOPED_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9_.:-])"
    r"(?P<scope>[A-Za-z0-9][A-Za-z0-9_.:-]{1,79})/"
    r"(?P<member>[A-Za-z0-9][A-Za-z0-9_.:@-]{1,159})"
)
_STRUCTURED_SCOPED_ENTITY_RE = re.compile(
    r"(?:^|[\s{,\[])(?:-\s*)?"
    r"[\"']?(?:name|entity|resource|target|subject)[\"']?\s*[:=]\s*"
    r"(?P<quote>[\"']?)"
    r"(?P<scope>[A-Za-z0-9][A-Za-z0-9_.:-]{1,79})/"
    r"(?P<member>[A-Za-z0-9][A-Za-z0-9_.:@-]{1,159})"
    r"(?P=quote)",
    re.IGNORECASE,
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
DEFAULT_VERIFICATION_ENTITY_LIMIT = 8
DEFAULT_VERIFICATION_REFERENCE_LIMIT = 4
_INTERNAL_ENTITY_SCAN_CAP = 64
_IGNORED_IDENTIFIER_VALUES = frozenset(
    {"true", "false", "null", "none", "nil", "unknown", "unset", "n/a"}
)


def _family(member: str) -> str:
    value = str(member or "").strip()
    if not value:
        return ""
    for pattern in (_UUID_SUFFIX_RE, _TRAILING_HEX_RE, _TRAILING_NUMBER_RE):
        reduced = pattern.sub("", value)
        if reduced != value and len(reduced) >= 3:
            return reduced
    return ""


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _local_identifier(key: str, value: str) -> bool:
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


def _structured_entities(text: str) -> list[tuple[int, str, str, str]]:
    rows: list[tuple[int, str, str, str]] = []
    for match in _STRUCTURED_SCOPED_ENTITY_RE.finditer(text):
        scope = match.group("scope")
        member = match.group("member").rstrip(".,;:)]}")
        rows.append(
            (
                _line_number(text, match.start()),
                scope,
                member,
                f"{scope}/{member}",
            )
        )
    return rows


def _scope_uniqueness_hints(
    text: str,
    *,
    member_limit: int,
    proximity_lines: int,
) -> list[dict[str, Any]]:
    """Find local IDs near structured scoped entities in visible evidence."""

    scoped = _structured_entities(text)
    identifiers: list[tuple[int, str, str]] = []
    for match in _IDENTIFIER_PAIR_RE.finditer(text):
        key = match.group("key")
        value = match.group("value").rstrip(".,;:)]}")
        if _local_identifier(key, value):
            identifiers.append((_line_number(text, match.start()), key, value))

    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for id_line, key, value in identifiers:
        nearby = [row for row in scoped if abs(row[0] - id_line) <= proximity_lines]
        if not nearby:
            continue
        slot = grouped.setdefault(
            (key.lower(), value),
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
                "verification": (
                    "Verify this identifier across the source and compare nearby scoped "
                    "entities. Do not correlate records by this identifier alone until "
                    "uniqueness across relevant scopes/entities is established."
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
    """Find scoped-identity navigation risks in already-visible raw text."""

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
        if family:
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


def _fingerprint(stat: os.stat_result) -> tuple[int, int, int, int, int]:
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)


def _target_families(hint: dict[str, Any]) -> set[tuple[str, str]]:
    families: set[tuple[str, str]] = set()
    for entity in hint.get("scoped_entities") or []:
        value = str(entity)
        if "/" not in value:
            continue
        scope, member = value.split("/", 1)
        family = _family(member)
        if scope and family:
            families.add((scope, family))
    return families


def verify_scoped_identity_gaps(
    source_path: str | Path,
    visible_text: str,
    *,
    expected_sha256: str | None = None,
    limit: int = 2,
    proximity_lines: int = DEFAULT_IDENTITY_PROXIMITY_LINES,
    entity_limit: int = DEFAULT_VERIFICATION_ENTITY_LIMIT,
    reference_limit: int = DEFAULT_VERIFICATION_REFERENCE_LIMIT,
) -> list[dict[str, Any]]:
    """Verify scoped-ID correlation constraints from one stable local source.

    The scan reports direct identifier-to-entity associations when visible. It
    also reports sibling entities in the same scope/name family as the visible
    entity. Sibling fan-out is an evidence gap, not proof of identifier reuse.
    """

    if limit < 1 or proximity_lines < 0 or entity_limit < 1 or reference_limit < 1:
        raise ValueError("identity verification bounds are invalid")
    hints = [
        item
        for item in scoped_identity_fanout_hints(visible_text, limit=max(limit, 3))
        if item.get("kind") == "scope_uniqueness_unverified"
    ][:limit]
    if not hints:
        return []

    targets = {
        (str(item["identifier_key"]).lower(), str(item["identifier_value"])): item
        for item in hints
    }
    path = Path(source_path).expanduser().resolve()
    digest = hashlib.sha256()
    recent_entities: deque[tuple[int, str, str]] = deque()
    state: dict[tuple[str, str], dict[str, Any]] = {}
    for key, hint in targets.items():
        state[key] = {
            "identifier_key": hint["identifier_key"],
            "identifier_value": hint["identifier_value"],
            "identifier_occurrences_seen": 0,
            "associated_occurrences": 0,
            "entities": {},
            "entity_overflow": False,
            "families": _target_families(hint),
            "siblings": {},
            "sibling_overflow": False,
        }

    with path.open("rb") as binary:
        opened = os.fstat(binary.fileno())
        for block in iter(lambda: binary.read(1024 * 1024), b""):
            digest.update(block)
        observed_sha = digest.hexdigest()
        if expected_sha256 and observed_sha.lower() != str(expected_sha256).lower():
            raise ValueError("source changed before scoped-identity verification")
        binary.seek(0)
        handle = io.TextIOWrapper(binary, encoding="utf-8", errors="replace", newline=None)
        try:
            for number, line in enumerate(handle, start=1):
                while recent_entities and number - recent_entities[0][0] > proximity_lines:
                    recent_entities.popleft()

                for match in _STRUCTURED_SCOPED_ENTITY_RE.finditer(line):
                    scope = match.group("scope")
                    member = match.group("member").rstrip(".,;:)]}")
                    recent_entities.append((number, f"{scope}/{member}", f"{scope}/"))

                scoped_tokens: list[tuple[str, str]] = []
                for match in _SCOPED_TOKEN_RE.finditer(line):
                    scope = match.group("scope")
                    member = match.group("member").rstrip(".,;:)]}")
                    scoped_tokens.append((scope, member))
                for slot in state.values():
                    families = slot["families"]
                    siblings = slot["siblings"]
                    for scope, member in scoped_tokens:
                        family = _family(member)
                        if (scope, family) not in families:
                            continue
                        entity = f"{scope}/{member}"
                        if entity not in siblings:
                            if len(siblings) >= _INTERNAL_ENTITY_SCAN_CAP:
                                slot["sibling_overflow"] = True
                                continue
                            siblings[entity] = {
                                "entity": entity,
                                "scope": f"{scope}/",
                                "occurrence_count": 0,
                                "references": [],
                                "first_line": number,
                                "last_line": number,
                            }
                        row = siblings[entity]
                        row["occurrence_count"] += 1
                        row["last_line"] = number
                        if len(row["references"]) < reference_limit:
                            row["references"].append(f"{path.name}:{number}")
                        elif reference_limit > 1:
                            # Preserve early provenance plus the most recent
                            # occurrence so bounded selection can retain nearby
                            # late-stage siblings without storing every match.
                            row["references"][-1] = f"{path.name}:{number}"

                for match in _IDENTIFIER_PAIR_RE.finditer(line):
                    key = match.group("key")
                    value = match.group("value").rstrip(".,;:)]}")
                    slot = state.get((key.lower(), value))
                    if slot is None:
                        continue
                    slot["identifier_occurrences_seen"] += 1
                    if not recent_entities:
                        continue
                    entity_line, entity, scope = recent_entities[-1]
                    slot["associated_occurrences"] += 1
                    entities = slot["entities"]
                    if entity not in entities:
                        if len(entities) >= _INTERNAL_ENTITY_SCAN_CAP:
                            slot["entity_overflow"] = True
                            continue
                        entities[entity] = {
                            "entity": entity,
                            "scope": scope,
                            "occurrence_count": 0,
                            "references": [],
                            "first_line": entity_line,
                            "last_line": entity_line,
                        }
                    row = entities[entity]
                    row["occurrence_count"] += 1
                    row["last_line"] = entity_line
                    reference = {
                        "entity_ref": f"{path.name}:{entity_line}",
                        "identifier_ref": f"{path.name}:{number}",
                    }
                    if len(row["references"]) < reference_limit:
                        row["references"].append(reference)
                    elif reference_limit > 1:
                        row["references"][-1] = reference
            read_complete = os.fstat(binary.fileno())
            current_path = path.stat()
        finally:
            handle.detach()

    if _fingerprint(opened) != _fingerprint(read_complete) or _fingerprint(opened) != _fingerprint(current_path):
        raise OSError("source changed during scoped-identity verification")

    verified: list[dict[str, Any]] = []
    for slot in state.values():
        ordered = sorted(
            slot["entities"].values(),
            key=lambda row: (int(row["first_line"]), str(row["entity"])),
        )
        anchor_lines = [
            line
            for row in ordered
            for line in (int(row["first_line"]), int(row.get("last_line") or row["first_line"]))
        ]
        def _sibling_distance(row: dict[str, Any]) -> tuple[int, int, str]:
            first = int(row["first_line"])
            last = int(row.get("last_line") or first)
            if not anchor_lines:
                return (0, first, str(row["entity"]))
            distance = min(
                abs(candidate - anchor)
                for candidate in (first, last)
                for anchor in anchor_lines
            )
            return (distance, first, str(row["entity"]))

        siblings = sorted(slot["siblings"].values(), key=_sibling_distance)
        entity_count = len(ordered)
        sibling_count = len(siblings)
        if entity_count >= 2:
            status = "multiple_scoped_entities_observed"
            finding = (
                "The same identifier value is directly associated with multiple scoped "
                "entities in this source. The identifier alone is not source-unique; "
                "preserve the relevant scope/entity when correlating records."
            )
        elif sibling_count >= 2:
            status = "uniqueness_unverified_with_sibling_scope_fanout"
            finding = (
                "This local identifier is observed inside a scoped entity, while multiple "
                "sibling entities from the same scope/name family coexist in the source. "
                "The scan does not prove that those siblings reuse the identifier, so "
                "identifier-only correlation remains unverified rather than safe."
            )
        elif entity_count == 1:
            status = "single_scoped_entity_observed"
            finding = (
                "Only one direct scoped-entity association was observed for this identifier "
                "and no sibling family fan-out was found in this source. This still does not "
                "prove global uniqueness outside the source."
            )
        else:
            status = "unresolved"
            finding = "The identifier could not be bound to a structured scoped entity during verification."

        verified.append(
            {
                "kind": "scoped_identifier_verification",
                "identifier_key": slot["identifier_key"],
                "identifier_value": slot["identifier_value"],
                "status": status,
                "source": path.name,
                "sha256": observed_sha,
                "identifier_occurrences_seen": int(slot["identifier_occurrences_seen"]),
                "associated_occurrences": int(slot["associated_occurrences"]),
                "entity_count_observed": entity_count,
                "entities": [
                    {key: value for key, value in row.items() if key not in {"first_line", "last_line"}}
                    for row in ordered[:entity_limit]
                ],
                "sibling_entity_count_observed": sibling_count,
                "sibling_selection_basis": "nearest_to_direct_identifier_association",
                "sibling_entities": [
                    {key: value for key, value in row.items() if key not in {"first_line", "last_line"}}
                    for row in siblings[:entity_limit]
                ],
                "truncated": bool(
                    slot["entity_overflow"]
                    or slot["sibling_overflow"]
                    or entity_count > entity_limit
                    or sibling_count > entity_limit
                ),
                "finding": finding,
                "correlation_requirement": (
                    "Until uniqueness is established, any lookup/correlation using this "
                    "identifier should be checked for the relevant scope/entity key instead "
                    "of assuming the identifier is sufficient by itself."
                ),
                "causal_note": (
                    "Identity/correlation verification only; sibling fan-out does not prove "
                    "identifier reuse and this observation does not by itself identify a root cause."
                ),
            }
        )
    return verified


__all__ = [
    "DEFAULT_AMBIGUITY_HINT_LIMIT",
    "DEFAULT_AMBIGUITY_MEMBER_LIMIT",
    "DEFAULT_IDENTITY_PROXIMITY_LINES",
    "DEFAULT_VERIFICATION_ENTITY_LIMIT",
    "DEFAULT_VERIFICATION_REFERENCE_LIMIT",
    "scoped_identity_fanout_hints",
    "verify_scoped_identity_gaps",
]
