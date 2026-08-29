from __future__ import annotations

import hashlib
from pathlib import Path

from tracecite.integrations.agent_projection import project
from tracecite.runtime import (
    EvidenceRequest,
    EvidenceRoutingPolicy,
    QueryTarget,
    RangeTarget,
    SourceTarget,
    retrieve,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_transport_retrieval_never_claims_epistemic_support(tmp_path: Path) -> None:
    source = tmp_path / "runtime.log"
    source.write_text("first\nERROR event\nlast\n", encoding="utf-8")

    direct_source = retrieve(
        EvidenceRequest(SourceTarget(source)),
        routing_policy=EvidenceRoutingPolicy(mode="direct"),
    ).to_dict()
    direct_query = retrieve(
        EvidenceRequest(QueryTarget(source, "ERROR", snapshot=False)),
        routing_policy=EvidenceRoutingPolicy(mode="direct"),
    ).to_dict()
    bounded_query = retrieve(
        EvidenceRequest(QueryTarget(source, "ERROR", snapshot=False)),
        routing_policy=EvidenceRoutingPolicy(mode="bounded"),
    ).to_dict()

    assert direct_source["outcome"] == "not_assessed"
    assert direct_query["outcome"] == "not_assessed"
    assert bounded_query["outcome"] == "not_assessed"


def test_range_integrity_is_canonical_and_projection_only_preserves_it(tmp_path: Path) -> None:
    source = tmp_path / "evidence.log"
    source.write_text(
        "\n".join(
            [
                "name: resource.example/widget-1001",
                "resourceID: device-a",
                "name: resource.example/widget-1002",
                "state: ready",
                "name: resource.example/widget-1003",
                "state: ready",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    digest = _sha256(source)

    result = retrieve(
        EvidenceRequest(
            RangeTarget(
                source,
                1,
                end_line=2,
                before=0,
                after=0,
                expected_sha256=digest,
            )
        )
    ).to_dict()

    assert result["outcome"] == "not_assessed"
    integrity = result["data"]["evidence_integrity"]["scoped_identity"][0]
    assert integrity["source"] == "evidence.log"
    assert integrity["identity_verification"][0]["status"] == (
        "uniqueness_unverified_with_sibling_scope_fanout"
    )
    assert result["missing_evidence"][0]["kind"] == "scope_uniqueness_unverified"
    assert result["missing_evidence"][0]["identifier_value"] == "device-a"
    assert result["data"]["progress"]["actionable_gaps"] == 1
    assert result["data"]["progress"]["stop"]["recommended"] is False

    projected = project(result, profile="agent")
    assert projected["data"]["evidence_integrity"] == result["data"]["evidence_integrity"]
    assert projected["missing_evidence"] == result["missing_evidence"]
