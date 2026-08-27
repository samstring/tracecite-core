"""Domain-neutral provider contract for deterministic evidence retrieval.

Providers fetch facts. They do not rank evidence, decide root cause, or run an
Agent loop. Runtime may use this contract to expand stable Evidence IDs and
EntityRefs without importing a concrete observability or mobile integration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping, Protocol, runtime_checkable

from .evidence import EntityRef, EvidenceContractError, EvidenceRelation


ProviderStatus = Literal["ok", "partial", "unavailable", "error"]


def _bounded_text(value: Any, name: str, *, limit: int = 1024, lower: bool = False) -> str:
    text = str(value or "").strip()
    if not text:
        raise EvidenceContractError(f"{name} must be non-empty")
    if len(text) > limit:
        raise EvidenceContractError(f"{name} exceeds {limit} characters")
    return text.lower() if lower else text


@dataclass(frozen=True)
class ProviderEvidence:
    """One provider-returned fact before Runtime correlation/reduction."""

    id: str
    kind: str
    source: str
    timestamp: str = ""
    severity: str = ""
    label: str = ""
    entities: tuple[EntityRef, ...] = ()
    evidence_uri: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.attributes, Mapping):
            raise EvidenceContractError("provider evidence attributes must be a mapping")
        entities = tuple(self.entities)
        if any(not isinstance(item, EntityRef) for item in entities):
            raise EvidenceContractError("provider evidence entities must contain EntityRef values")
        deduped: list[EntityRef] = []
        seen: set[tuple[str, str, str]] = set()
        for entity in entities:
            if entity.key not in seen:
                seen.add(entity.key)
                deduped.append(entity)
        object.__setattr__(self, "id", _bounded_text(self.id, "provider evidence id", limit=256))
        object.__setattr__(self, "kind", _bounded_text(self.kind, "provider evidence kind", limit=128, lower=True))
        object.__setattr__(self, "source", _bounded_text(self.source, "provider evidence source", limit=256))
        object.__setattr__(self, "timestamp", str(self.timestamp or "").strip())
        object.__setattr__(self, "severity", str(self.severity or "").strip().lower())
        object.__setattr__(self, "label", str(self.label or "")[:1024])
        object.__setattr__(self, "entities", tuple(deduped))
        object.__setattr__(self, "evidence_uri", str(self.evidence_uri or "").strip())
        object.__setattr__(self, "attributes", dict(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "source": self.source,
            "entities": [item.to_dict() for item in self.entities],
        }
        for key in ("timestamp", "severity", "label", "evidence_uri"):
            value = getattr(self, key)
            if value:
                payload[key] = value
        if self.attributes:
            payload["attributes"] = dict(self.attributes)
        return payload

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ProviderEvidence":
        if not isinstance(value, Mapping):
            raise EvidenceContractError("provider evidence must be a mapping")
        raw_entities = value.get("entities") or []
        if not isinstance(raw_entities, (list, tuple)):
            raise EvidenceContractError("provider evidence entities must be an array")
        entities = tuple(
            item if isinstance(item, EntityRef) else EntityRef.from_mapping(item)
            for item in raw_entities
        )
        return cls(
            id=value.get("id", ""),
            kind=value.get("kind", ""),
            source=value.get("source", ""),
            timestamp=value.get("timestamp", ""),
            severity=value.get("severity", ""),
            label=value.get("label", ""),
            entities=entities,
            evidence_uri=value.get("evidence_uri", value.get("uri", "")),
            attributes=value.get("attributes") or {},
        )


@dataclass(frozen=True)
class RetrieveRequest:
    """Bounded provider query driven by stable IDs and/or correlation entities."""

    evidence_ids: tuple[str, ...] = ()
    entities: tuple[EntityRef, ...] = ()
    limit: int = 100
    depth: int = 0
    reason: str = "investigate"
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.limit, bool) or not isinstance(self.limit, int) or self.limit < 1:
            raise EvidenceContractError("retrieve request limit must be an integer >= 1")
        if isinstance(self.depth, bool) or not isinstance(self.depth, int) or self.depth < 0:
            raise EvidenceContractError("retrieve request depth must be a non-negative integer")
        if not isinstance(self.attributes, Mapping):
            raise EvidenceContractError("retrieve request attributes must be a mapping")
        evidence_ids = tuple(dict.fromkeys(str(item).strip() for item in self.evidence_ids if str(item).strip()))
        entities = tuple(self.entities)
        if any(not isinstance(item, EntityRef) for item in entities):
            raise EvidenceContractError("retrieve request entities must contain EntityRef values")
        deduped_entities: list[EntityRef] = []
        seen: set[tuple[str, str, str]] = set()
        for entity in entities:
            if entity.key not in seen:
                seen.add(entity.key)
                deduped_entities.append(entity)
        if not evidence_ids and not deduped_entities:
            raise EvidenceContractError("retrieve request requires evidence_ids or entities")
        object.__setattr__(self, "evidence_ids", evidence_ids)
        object.__setattr__(self, "entities", tuple(deduped_entities))
        object.__setattr__(self, "reason", str(self.reason or "investigate")[:256])
        object.__setattr__(self, "attributes", dict(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "evidence_ids": list(self.evidence_ids),
            "entities": [item.to_dict() for item in self.entities],
            "limit": self.limit,
            "depth": self.depth,
            "reason": self.reason,
        }
        if self.attributes:
            payload["attributes"] = dict(self.attributes)
        return payload


@dataclass(frozen=True)
class RetrieveResult:
    """One bounded provider response with explicit incompleteness diagnostics."""

    status: ProviderStatus
    evidence: tuple[ProviderEvidence, ...] = ()
    relations: tuple[EvidenceRelation, ...] = ()
    coverage: Mapping[str, Any] = field(default_factory=dict)
    diagnostics: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in {"ok", "partial", "unavailable", "error"}:
            raise EvidenceContractError(f"unsupported provider status: {self.status!r}")
        evidence = tuple(self.evidence)
        relations = tuple(self.relations)
        if any(not isinstance(item, ProviderEvidence) for item in evidence):
            raise EvidenceContractError("retrieve result evidence must contain ProviderEvidence values")
        if any(not isinstance(item, EvidenceRelation) for item in relations):
            raise EvidenceContractError("retrieve result relations must contain EvidenceRelation values")
        if not isinstance(self.coverage, Mapping) or not isinstance(self.diagnostics, Mapping):
            raise EvidenceContractError("retrieve result coverage/diagnostics must be mappings")
        object.__setattr__(self, "evidence", evidence)
        object.__setattr__(self, "relations", relations)
        object.__setattr__(self, "coverage", dict(self.coverage))
        object.__setattr__(self, "diagnostics", dict(self.diagnostics))

    @property
    def complete(self) -> bool:
        if self.status != "ok":
            return False
        return bool(self.coverage.get("complete", True))

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "evidence": [item.to_dict() for item in self.evidence],
            "relations": [item.to_dict() for item in self.relations],
            "coverage": dict(self.coverage),
            "diagnostics": dict(self.diagnostics),
        }


@runtime_checkable
class EvidenceProvider(Protocol):
    """Provider boundary consumed by the deterministic investigation runtime."""

    name: str

    def can_handle(self, request: RetrieveRequest) -> bool:
        """Return whether this provider can resolve any identity in request."""

        ...

    def retrieve(self, request: RetrieveRequest) -> RetrieveResult:
        """Fetch bounded evidence without performing Agent reasoning."""

        ...


__all__ = [
    "EvidenceProvider",
    "ProviderEvidence",
    "ProviderStatus",
    "RetrieveRequest",
    "RetrieveResult",
]
