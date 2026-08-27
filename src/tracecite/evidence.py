"""Domain-neutral evidence relationship contracts.

These objects deliberately describe identity and observable relationships only.
They do not encode relevance, token priority, causality, or root-cause claims.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


class EvidenceContractError(ValueError):
    """An evidence intelligence public value object is malformed."""


def _text(value: Any, name: str, *, limit: int = 512, lower: bool = False) -> str:
    text = str(value or "").strip()
    if not text:
        raise EvidenceContractError(f"{name} must be non-empty")
    if len(text) > limit:
        raise EvidenceContractError(f"{name} exceeds {limit} characters")
    return text.lower() if lower else text


@dataclass(frozen=True, order=True)
class EntityRef:
    """Stable reference to one correlation entity supplied by a domain.

    ``kind`` is intentionally open (for example ``session``, ``request`` or
    ``trace``). ``namespace`` avoids accidental joins when independent systems
    reuse the same identifier vocabulary.
    """

    kind: str
    value: str
    namespace: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.attributes, Mapping):
            raise EvidenceContractError("entity.attributes must be a mapping")
        object.__setattr__(self, "kind", _text(self.kind, "entity.kind", limit=128, lower=True))
        object.__setattr__(self, "value", _text(self.value, "entity.value", limit=1024))
        namespace = str(self.namespace or "").strip().lower()
        if len(namespace) > 256:
            raise EvidenceContractError("entity.namespace exceeds 256 characters")
        object.__setattr__(self, "namespace", namespace)
        object.__setattr__(self, "attributes", dict(self.attributes))

    @property
    def key(self) -> tuple[str, str, str]:
        """Canonical equality/join key, excluding descriptive attributes."""

        return (self.namespace, self.kind, self.value)

    @property
    def identity(self) -> str:
        namespace = f"{self.namespace}:" if self.namespace else ""
        return f"{namespace}{self.kind}:{self.value}"

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"kind": self.kind, "value": self.value}
        if self.namespace:
            payload["namespace"] = self.namespace
        if self.attributes:
            payload["attributes"] = dict(self.attributes)
        return payload

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "EntityRef":
        if not isinstance(value, Mapping):
            raise EvidenceContractError("entity must be a mapping")
        return cls(
            kind=value.get("kind", ""),
            value=value.get("value", ""),
            namespace=value.get("namespace", ""),
            attributes=value.get("attributes") or {},
        )


@dataclass(frozen=True)
class EvidenceRelation:
    """Observable or inferred relationship between two evidence identities.

    A relation says why two evidence items are connected. It must not be used
    to smuggle a causal Finding into the fact layer. ``basis`` should name the
    deterministic rule or domain declaration that produced the edge.
    """

    source_id: str
    target_id: str
    kind: str
    basis: str
    confidence: float = 1.0
    entity: EntityRef | None = None
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.attributes, Mapping):
            raise EvidenceContractError("relation.attributes must be a mapping")
        confidence = self.confidence
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            raise EvidenceContractError("relation.confidence must be numeric")
        confidence = float(confidence)
        if confidence < 0.0 or confidence > 1.0:
            raise EvidenceContractError("relation.confidence must be between 0 and 1")
        if self.entity is not None and not isinstance(self.entity, EntityRef):
            raise EvidenceContractError("relation.entity must be EntityRef or None")
        object.__setattr__(self, "source_id", _text(self.source_id, "relation.source_id", limit=256))
        object.__setattr__(self, "target_id", _text(self.target_id, "relation.target_id", limit=256))
        object.__setattr__(self, "kind", _text(self.kind, "relation.kind", limit=128, lower=True))
        object.__setattr__(self, "basis", _text(self.basis, "relation.basis", limit=128, lower=True))
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "attributes", dict(self.attributes))

    @property
    def identity(self) -> tuple[str, str, str, str, str]:
        """Stable identity independent from confidence/diagnostic attributes."""

        entity_id = self.entity.identity if self.entity is not None else ""
        return (self.source_id, self.target_id, self.kind, self.basis, entity_id)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "kind": self.kind,
            "basis": self.basis,
            "confidence": self.confidence,
        }
        if self.entity is not None:
            payload["entity"] = self.entity.to_dict()
        if self.attributes:
            payload["attributes"] = dict(self.attributes)
        return payload

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "EvidenceRelation":
        if not isinstance(value, Mapping):
            raise EvidenceContractError("relation must be a mapping")
        entity = value.get("entity")
        return cls(
            source_id=value.get("source_id", ""),
            target_id=value.get("target_id", ""),
            kind=value.get("kind", ""),
            basis=value.get("basis", ""),
            confidence=value.get("confidence", 1.0),
            entity=EntityRef.from_mapping(entity) if isinstance(entity, Mapping) else None,
            attributes=value.get("attributes") or {},
        )


__all__ = ["EvidenceContractError", "EntityRef", "EvidenceRelation"]
