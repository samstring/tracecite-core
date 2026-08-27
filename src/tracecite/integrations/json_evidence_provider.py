"""Small provider-neutral JSON evidence adapter used by tests and benchmarks.

This is deliberately a generic transport adapter, not a Bugly/Sentry/OTel
implementation. It demonstrates the Provider contract with multiple independent
runtime evidence sources while remaining useful for exported fixture data.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import quote, unquote, urlsplit

from tracecite.extension.evidence import EntityRef, EvidenceRelation
from tracecite.extension.retrieval import ProviderEvidence, RetrieveRequest, RetrieveResult


JSON_PROVIDER_SCHEMA_VERSION = 1


class JsonEvidenceProvider:
    def __init__(
        self,
        name: str,
        evidence: Sequence[ProviderEvidence],
        *,
        relations: Sequence[EvidenceRelation] = (),
        source_path: str | Path | None = None,
    ) -> None:
        resolved_name = str(name or "").strip()
        if not resolved_name or len(resolved_name) > 128:
            raise ValueError("JSON evidence provider name must be 1-128 characters")
        records = tuple(evidence)
        if any(not isinstance(item, ProviderEvidence) for item in records):
            raise ValueError("evidence must contain ProviderEvidence values")
        relation_values = tuple(relations)
        if any(not isinstance(item, EvidenceRelation) for item in relation_values):
            raise ValueError("relations must contain EvidenceRelation values")
        ids = [item.id for item in records]
        if len(ids) != len(set(ids)):
            raise ValueError("JSON evidence ids must be unique within one provider")
        self.name = resolved_name
        self.source_path = Path(source_path).resolve() if source_path is not None else None
        self._by_id: dict[str, ProviderEvidence] = {}
        self._entity_index: dict[tuple[str, str, str], list[str]] = {}
        for record in records:
            normalized = record if record.evidence_uri else ProviderEvidence(
                id=record.id,
                kind=record.kind,
                source=record.source,
                timestamp=record.timestamp,
                severity=record.severity,
                label=record.label,
                entities=record.entities,
                evidence_uri=self._uri(record.id),
                attributes=record.attributes,
            )
            self._by_id[normalized.id] = normalized
            for entity in normalized.entities:
                self._entity_index.setdefault(entity.key, []).append(normalized.id)
        for values in self._entity_index.values():
            values.sort()
        self._relations = relation_values

    def _uri(self, evidence_id: str) -> str:
        return f"evidence+json://{quote(self.name, safe='')}/{quote(evidence_id, safe='')}"

    @classmethod
    def from_path(cls, path: str | Path, *, name: str | None = None) -> "JsonEvidenceProvider":
        source = Path(path).expanduser().resolve()
        payload = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            raise ValueError("JSON evidence file must contain an object")
        if int(payload.get("schema_version") or 0) != JSON_PROVIDER_SCHEMA_VERSION:
            raise ValueError("unsupported JSON evidence provider schema")
        resolved_name = str(name or payload.get("provider") or source.stem).strip()
        raw_records = payload.get("evidence") or []
        if not isinstance(raw_records, list):
            raise ValueError("JSON evidence file 'evidence' must be an array")
        records: list[ProviderEvidence] = []
        for value in raw_records:
            if not isinstance(value, Mapping):
                raise ValueError("JSON evidence record must be an object")
            enriched = dict(value)
            enriched.setdefault("source", str(payload.get("source") or resolved_name))
            records.append(ProviderEvidence.from_mapping(enriched))
        raw_relations = payload.get("relations") or []
        if not isinstance(raw_relations, list):
            raise ValueError("JSON evidence file 'relations' must be an array")
        relations = [EvidenceRelation.from_mapping(value) for value in raw_relations]
        return cls(resolved_name, records, relations=relations, source_path=source)

    def can_handle(self, request: RetrieveRequest) -> bool:
        if any(item in self._by_id for item in request.evidence_ids):
            return True
        return any(entity.key in self._entity_index for entity in request.entities)

    def retrieve(self, request: RetrieveRequest) -> RetrieveResult:
        matched: set[str] = {item for item in request.evidence_ids if item in self._by_id}
        for entity in request.entities:
            matched.update(self._entity_index.get(entity.key, ()))
        ordered = sorted(matched)
        selected_ids = ordered[: request.limit]
        selected = tuple(self._by_id[item] for item in selected_ids)
        selected_set = set(selected_ids)
        relations = tuple(
            relation
            for relation in self._relations
            if relation.source_id in selected_set or relation.target_id in selected_set
        )
        complete = len(ordered) <= request.limit
        return RetrieveResult(
            status="ok" if complete else "partial",
            evidence=selected,
            relations=relations,
            coverage={
                "complete": complete,
                "matched": len(ordered),
                "returned": len(selected),
                "truncated": not complete,
            },
            diagnostics={
                "provider": self.name,
                "source_bytes": self.source_path.stat().st_size if self.source_path else 0,
            },
        )

    def get(self, evidence_id: str) -> ProviderEvidence:
        try:
            return self._by_id[str(evidence_id)]
        except KeyError as exc:
            raise KeyError(f"unknown evidence id for {self.name}: {evidence_id}") from exc

    def resolve(self, evidence_uri: str) -> ProviderEvidence:
        parsed = urlsplit(str(evidence_uri))
        if parsed.scheme != "evidence+json" or unquote(parsed.netloc) != self.name:
            raise ValueError("evidence URI does not belong to this JSON provider")
        evidence_id = unquote(parsed.path.lstrip("/"))
        record = self.get(evidence_id)
        if record.evidence_uri != evidence_uri:
            raise ValueError("evidence URI is not canonical for this record")
        return record

    @property
    def evidence_count(self) -> int:
        return len(self._by_id)


__all__ = ["JSON_PROVIDER_SCHEMA_VERSION", "JsonEvidenceProvider"]
