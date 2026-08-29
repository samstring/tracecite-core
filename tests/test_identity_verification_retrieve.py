from __future__ import annotations

import hashlib
from pathlib import Path

from tracecite.integrations.agent_projection import project
from tracecite.runtime import EvidenceRequest, RangeTarget, retrieve


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_range_retrieve_closes_scoped_identity_gap_in_same_call(tmp_path: Path) -> None:
    source = tmp_path / "incident.log"
    source.write_text(
        "\n".join(
            [
                "name: resource.example/widget-1001",
                "health: Healthy",
                "resourceID: local-device",
                "unrelated",
                "name: resource.example/widget-2002",
                "health: Unhealthy",
                "resourceID: local-device",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = retrieve(
        EvidenceRequest(
            RangeTarget(
                source,
                2,
                before=1,
                after=1,
                expected_sha256=_sha256(source),
            )
        )
    )

    canonical_data = dict(result.canonical_result.get("data") or {})
    integrity = canonical_data["evidence_integrity"]["scoped_identity"][0]
    verification = integrity["identity_verification"]
    assert len(verification) == 1
    assert verification[0]["status"] == "multiple_scoped_entities_observed"
    assert verification[0]["identifier_value"] == "local-device"
    assert [row["entity"] for row in verification[0]["entities"]] == [
        "resource.example/widget-1001",
        "resource.example/widget-2002",
    ]
    assert not any(
        item.get("kind") == "scope_uniqueness_unverified"
        for item in result.canonical_result.get("missing_evidence") or []
    )

    agent_view = project(result.to_dict(), profile="agent")
    agent_integrity = agent_view["data"]["evidence_integrity"]["scoped_identity"][0]
    assert agent_integrity["identity_verification"][0]["status"] == (
        "multiple_scoped_entities_observed"
    )
    assert "root cause" in agent_view["data"]["evidence_integrity"]["note"]
    assert "do not identify" in agent_view["data"]["evidence_integrity"]["note"]
