from __future__ import annotations

import pytest

from tracecite.extension.retrieval import (
    ProviderEvidence,
    RetrieveRequest as ProviderRetrieveRequest,
    RetrieveResult as ProviderRetrieveResult,
)
from tracecite.runtime import (
    EvidenceRequest,
    InvestigationStore,
    ProviderTarget,
    retrieve,
)


class _Provider:
    def __init__(self, name: str, *, label: str) -> None:
        self.name = name
        self.label = label

    def can_handle(self, request: ProviderRetrieveRequest) -> bool:
        return bool(request.evidence_ids)

    def retrieve(self, request: ProviderRetrieveRequest) -> ProviderRetrieveResult:
        return ProviderRetrieveResult(
            status="ok",
            evidence=(
                ProviderEvidence(
                    id="record-1",
                    kind="log",
                    source="shared-source",
                    label=self.label,
                    evidence_uri="evidence://shared/record-1",
                ),
            ),
            coverage={"complete": True},
        )


def _request(tmp_path, providers) -> EvidenceRequest:
    state_path = tmp_path / "investigation.json"
    if not state_path.exists():
        InvestigationStore(state_path).create("provider namespace regression")
    return EvidenceRequest(
        ProviderTarget(ProviderRetrieveRequest(evidence_ids=("record-1",))),
        providers=tuple(providers),
        investigation_path=state_path,
    )


def test_same_local_id_and_native_uri_from_different_providers_do_not_collide(tmp_path) -> None:
    providers = (
        _Provider("provider-a", label="from A"),
        _Provider("provider-b", label="from B"),
    )

    result = retrieve(_request(tmp_path, providers))

    assert result.status == "ok"
    assert len(result.canonical_result["evidence"]) == 2
    assert len(result.new_evidence) == 2
    rows = {row["uri"]: row for row in result.canonical_result["evidence"]}
    assert set(rows) == {
        "provider://provider-a/record-1",
        "provider://provider-b/record-1",
    }
    for uri, row in rows.items():
        provider = "provider-a" if "provider-a" in uri else "provider-b"
        metadata = row["metadata"]
        assert metadata["evidence_uri"] == uri
        assert metadata["attributes"]["provider"] == provider
        assert metadata["attributes"]["provider_record_id"] == "record-1"
        assert metadata["attributes"]["provider_evidence_uri"] == "evidence://shared/record-1"


def test_provider_namespace_is_the_progress_identity_across_retrievals(tmp_path) -> None:
    providers = (
        _Provider("provider-a", label="from A"),
        _Provider("provider-b", label="from B"),
    )

    first = retrieve(_request(tmp_path, providers))
    second = retrieve(_request(tmp_path, providers))

    assert len(first.new_evidence) == 2
    assert second.status == "no_new_evidence"
    assert second.new_evidence == ()
    assert second.repeated_evidence == 2
    assert second.stop_reason is not None
    assert second.stop_reason.kind == "no_new_evidence"


def test_duplicate_provider_names_are_rejected_as_ambiguous_namespaces(tmp_path) -> None:
    request = _request(
        tmp_path,
        (
            _Provider("duplicate", label="first"),
            _Provider("duplicate", label="second"),
        ),
    )

    with pytest.raises(ValueError, match="provider names must be unique"):
        retrieve(request)


def test_provider_name_and_record_id_are_uri_escaped(tmp_path) -> None:
    provider = _Provider("service / west", label="escaped")

    result = retrieve(_request(tmp_path, (provider,)))

    assert result.canonical_result["evidence"][0]["uri"] == "provider://service%20%2F%20west/record-1"
