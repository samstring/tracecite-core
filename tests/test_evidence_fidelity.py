from __future__ import annotations

import hashlib
from pathlib import Path

from tracecite.integrations.agent_projection import project
from tracecite.runtime import EvidenceRequest, EvidenceRoutingPolicy, QueryTarget, retrieve
from tracecite.runtime.evidence_fidelity import enrich_search_leaf_context


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _search_payload(source: Path, *, label: str, line: int, sha256: str | None = None) -> dict:
    digest = sha256 or _sha256(source)
    return {
        "operation": "search",
        "status": "ok",
        "outcome": "supported",
        "evidence": [
            {
                "uri": f"evidence://sha256/{digest}#L{line}",
                "source_path": str(source),
                "sha256": digest,
                "start_line": line,
                "end_line": line,
                "label": label,
            }
        ],
        "coverage": {"match_records": 1, "evidence_returned": 1},
        "data": {"query": "degraded"},
    }


def test_structured_leaf_keeps_bounded_parent_and_sibling_context(tmp_path: Path) -> None:
    source = tmp_path / "evidence.log"
    source.write_text(
        "\n".join(
            [
                "name: entity.example/item-1001",
                "attributes:",
                "- state: degraded",
                "  localID: device-a",
                "observed: true",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    payload = _search_payload(source, label="- state: degraded", line=3)

    result = enrich_search_leaf_context(payload)

    label = result["evidence"][0]["label"]
    assert label.startswith("- state: degraded || nearby:")
    assert "evidence.log:1 name: entity.example/item-1001" in label
    assert "evidence.log:3 - state: degraded" in label
    assert "evidence.log:4 localID: device-a" in label
    assert result["coverage"]["structured_context_enriched"] == 1
    assert payload["evidence"][0]["label"] == "- state: degraded"


def test_public_retrieve_owns_structured_context_and_identity_gap(tmp_path: Path) -> None:
    source = tmp_path / "events.log"
    source.write_text(
        "name: service.example/worker-1001\nstate: degraded\nlocalID: worker-a\n",
        encoding="utf-8",
    )

    result = retrieve(
        EvidenceRequest(QueryTarget(source, "state: degraded", snapshot=False)),
        routing_policy=EvidenceRoutingPolicy(mode="bounded"),
    ).to_dict()

    assert result["outcome"] == "not_assessed"
    assert "events.log:1 name: service.example/worker-1001" in result["evidence"][0]["label"]
    assert "events.log:3 localID: worker-a" in result["evidence"][0]["label"]
    assert result["coverage"]["structured_context_enriched"] == 1
    assert result["missing_evidence"][0]["kind"] == "scope_uniqueness_unverified"
    assert result["missing_evidence"][0]["identifier_value"] == "worker-a"
    assert result["data"]["progress"]["actionable_gaps"] == 1
    assert "stop" not in result["data"]["progress"]
    assert "stop_reason" not in result["data"]
    assert result["data"]["evidence_integrity"]["scoped_identity"]

    agent = project(result, profile="agent")
    full = project(result, profile="full")
    assert agent["evidence"][0]["label"] == result["evidence"][0]["label"]
    assert full == result


def test_agent_projection_does_not_discover_structured_context(tmp_path: Path) -> None:
    source = tmp_path / "events.log"
    source.write_text(
        "name: service.example/worker-1001\nstate: degraded\nlocalID: worker-a\n",
        encoding="utf-8",
    )
    payload = _search_payload(source, label="state: degraded", line=2)

    agent = project(payload, profile="agent")

    assert agent["evidence"][0]["label"] == "state: degraded"
    assert "structured_context_enriched" not in agent["coverage"]
    assert "evidence_integrity" not in agent["data"]


def test_unstructured_search_hit_is_unchanged(tmp_path: Path) -> None:
    source = tmp_path / "plain.log"
    source.write_text("first line\nrequest failed while reconnecting\nthird line\n", encoding="utf-8")
    payload = _search_payload(source, label="request failed while reconnecting", line=2)

    result = enrich_search_leaf_context(payload)

    assert result["evidence"][0]["label"] == "request failed while reconnecting"
    assert "structured_context_enriched" not in result["coverage"]


def test_hash_mismatch_conservatively_skips_context_enrichment(tmp_path: Path) -> None:
    source = tmp_path / "changed.log"
    source.write_text("name: service.example/worker-1\nstate: degraded\n", encoding="utf-8")
    payload = _search_payload(source, label="state: degraded", line=2, sha256="0" * 64)

    result = enrich_search_leaf_context(payload)

    assert result["evidence"][0]["label"] == "state: degraded"
    assert "structured_context_enriched" not in result["coverage"]
