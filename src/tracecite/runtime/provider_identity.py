"""Canonical provider-record identity normalization for public Runtime retrieval.

Provider record IDs and source-native evidence URIs are only meaningful inside
the provider that emitted them unless an external contract says otherwise. This
module wraps providers at the Runtime boundary so two independent providers can
never collide merely because they both use ``id=123`` or the same URI string.

The provider's original URI is preserved as provenance metadata. No relation,
relevance, causal, or ranking semantics are introduced here.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

from tracecite.extension.retrieval import (
    EvidenceProvider,
    ProviderEvidence,
    RetrieveRequest as ProviderRetrieveRequest,
    RetrieveResult as ProviderRetrieveResult,
)

from .agent_api import EvidenceRequest, ProviderTarget


def provider_record_uri(provider_name: str, record_id: str) -> str:
    """Return stable canonical identity for one provider-local record ID."""

    name = str(provider_name or "").strip()
    identifier = str(record_id or "").strip()
    if not name:
        raise ValueError("evidence provider requires a non-empty name")
    if not identifier:
        raise ValueError("provider evidence requires a non-empty id")
    return f"provider://{quote(name, safe='')}/{quote(identifier, safe='')}"


@dataclass(frozen=True)
class _NamespacedProvider:
    provider: EvidenceProvider
    name: str

    def can_handle(self, request: ProviderRetrieveRequest) -> bool:
        return self.provider.can_handle(request)

    def retrieve(self, request: ProviderRetrieveRequest) -> ProviderRetrieveResult:
        result = self.provider.retrieve(request)
        if not isinstance(result, ProviderRetrieveResult):
            return result

        evidence: list[ProviderEvidence] = []
        for item in result.evidence:
            attributes = dict(item.attributes)
            attributes.setdefault("provider", self.name)
            attributes.setdefault("provider_record_id", item.id)
            if item.evidence_uri:
                attributes.setdefault("provider_evidence_uri", item.evidence_uri)
            evidence.append(
                ProviderEvidence(
                    id=item.id,
                    kind=item.kind,
                    source=item.source,
                    timestamp=item.timestamp,
                    severity=item.severity,
                    label=item.label,
                    entities=item.entities,
                    evidence_uri=provider_record_uri(self.name, item.id),
                    attributes=attributes,
                )
            )
        return ProviderRetrieveResult(
            status=result.status,
            evidence=tuple(evidence),
            relations=result.relations,
            coverage=result.coverage,
            diagnostics=result.diagnostics,
        )


def namespace_provider_request(request: EvidenceRequest) -> EvidenceRequest:
    """Normalize ProviderTarget providers without changing non-provider requests."""

    if not isinstance(request, EvidenceRequest):
        raise TypeError("namespace_provider_request requires EvidenceRequest")
    if not isinstance(request.target, ProviderTarget):
        return request

    wrapped: list[EvidenceProvider] = []
    seen_names: set[str] = set()
    for provider in request.providers:
        name = str(getattr(provider, "name", "") or "").strip()
        if not name:
            raise ValueError("evidence provider requires a non-empty name")
        if name in seen_names:
            raise ValueError(f"evidence provider names must be unique: {name!r}")
        seen_names.add(name)
        wrapped.append(_NamespacedProvider(provider=provider, name=name))

    return EvidenceRequest(
        target=request.target,
        investigation_path=request.investigation_path,
        hypothesis_id=request.hypothesis_id,
        test_id=request.test_id,
        cache=request.cache,
        providers=tuple(wrapped),
    )


__all__ = ["namespace_provider_request", "provider_record_uri"]
