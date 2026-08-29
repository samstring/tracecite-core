"""Deterministic grouping and representative selection for evidence nodes."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .correlation import EvidenceNode


_UUID_RE = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F-]{27,36}\b")
_HEX_RE = re.compile(r"\b(?:0x)?[0-9a-fA-F]{12,}\b")
_NUMBER_RE = re.compile(r"(?<![A-Za-z_])\d+(?:\.\d+)?(?![A-Za-z_])")
_SPACE_RE = re.compile(r"\s+")
_SEVERITY = {"fatal": 6, "critical": 5, "error": 4, "warning": 3, "warn": 3, "info": 2, "debug": 1, "trace": 0, "": 0}


def normalize_template(text: str) -> str:
    """Remove common high-cardinality identifiers without semantic parsing."""

    value = str(text or "").strip().lower()
    value = _UUID_RE.sub("<uuid>", value)
    value = _HEX_RE.sub("<hex>", value)
    value = _NUMBER_RE.sub("<n>", value)
    return _SPACE_RE.sub(" ", value)[:2048]


def _node_text(node: EvidenceNode) -> str:
    for key in ("template", "message", "text"):
        value = node.attributes.get(key)
        if value:
            return str(value)
    return node.label or node.kind


def _entity_signature(node: EvidenceNode) -> tuple[tuple[str, str, str], ...]:
    """Return exact entity identity that grouping is forbidden to normalize away.

    Message payloads may contain high-cardinality UUIDs/numbers that are safe to
    normalize for repetition detection. EntityRef keys are correlation identity,
    however, so evidence from different exact entities must never be collapsed
    into one group merely because their message templates match.
    """

    return tuple(sorted(entity.key for entity in node.entities))


def _timestamp_key(value: str) -> tuple[int, str]:
    return (0 if value else 1, value or "")


@dataclass(frozen=True)
class EvidenceGroup:
    id: str
    key: str
    member_ids: tuple[str, ...]
    representative_ids: tuple[str, ...]
    count: int
    source: str
    kind: str
    template: str
    first_timestamp: str = ""
    last_timestamp: str = ""

    def __post_init__(self) -> None:
        if self.count != len(self.member_ids):
            raise ValueError("group count must match member_ids")
        if not self.member_ids:
            raise ValueError("group must contain at least one member")
        if any(item not in self.member_ids for item in self.representative_ids):
            raise ValueError("group representative must be a member")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "key": self.key,
            "member_ids": list(self.member_ids),
            "representative_ids": list(self.representative_ids),
            "count": self.count,
            "source": self.source,
            "kind": self.kind,
            "template": self.template,
            "first_timestamp": self.first_timestamp,
            "last_timestamp": self.last_timestamp,
        }


@dataclass(frozen=True)
class GroupingResult:
    groups: tuple[EvidenceGroup, ...]
    node_to_group: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "node_to_group", dict(self.node_to_group))

    @property
    def collapsed_count(self) -> int:
        return sum(max(0, group.count - len(group.representative_ids)) for group in self.groups)


def _representatives(nodes: Sequence[EvidenceNode], limit: int) -> tuple[str, ...]:
    if limit < 1:
        raise ValueError("max_representatives must be at least 1")
    ordered = sorted(nodes, key=lambda item: (_timestamp_key(item.timestamp), item.id))
    selected: list[str] = []

    def add(node: EvidenceNode) -> None:
        if node.id not in selected and len(selected) < limit:
            selected.append(node.id)

    add(ordered[0])
    if len(selected) < limit:
        severe = max(
            nodes,
            key=lambda item: (_SEVERITY.get(item.severity, 0), item.timestamp, item.id),
        )
        add(severe)
    if len(selected) < limit:
        add(ordered[-1])
    return tuple(selected)


def _encoded_group_key(
    source: str,
    kind: str,
    template: str,
    entity_signature: tuple[tuple[str, str, str], ...],
) -> str:
    # Preserve the historical key/id for evidence with no entity identity.
    encoded = f"{source}\0{kind}\0{template}"
    if not entity_signature:
        return encoded
    entity_part = "\x1e".join("\x1f".join(parts) for parts in entity_signature)
    return f"{encoded}\0entities:{entity_part}"


def group_evidence(
    nodes: Sequence[EvidenceNode],
    *,
    max_representatives: int = 3,
) -> GroupingResult:
    """Group repetition while preserving exact correlation-entity diversity."""

    buckets: dict[
        tuple[str, str, str, tuple[tuple[str, str, str], ...]],
        list[EvidenceNode],
    ] = {}
    for node in nodes:
        template = normalize_template(_node_text(node))
        entity_signature = _entity_signature(node)
        key = (node.source, node.kind, template, entity_signature)
        buckets.setdefault(key, []).append(node)

    groups: list[EvidenceGroup] = []
    node_to_group: dict[str, str] = {}
    for source, kind, template, entity_signature in sorted(buckets):
        members = sorted(
            buckets[(source, kind, template, entity_signature)],
            key=lambda item: (_timestamp_key(item.timestamp), item.id),
        )
        member_ids = tuple(item.id for item in members)
        encoded_key = _encoded_group_key(source, kind, template, entity_signature)
        group_id = "g-" + hashlib.sha256(encoded_key.encode("utf-8")).hexdigest()[:16]
        timestamps = [item.timestamp for item in members if item.timestamp]
        group = EvidenceGroup(
            id=group_id,
            key=encoded_key,
            member_ids=member_ids,
            representative_ids=_representatives(members, max_representatives),
            count=len(members),
            source=source,
            kind=kind,
            template=template,
            first_timestamp=min(timestamps) if timestamps else "",
            last_timestamp=max(timestamps) if timestamps else "",
        )
        groups.append(group)
        for node_id in member_ids:
            node_to_group[node_id] = group_id
    return GroupingResult(groups=tuple(groups), node_to_group=node_to_group)


__all__ = ["EvidenceGroup", "GroupingResult", "group_evidence", "normalize_template"]
