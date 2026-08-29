from __future__ import annotations

import hashlib
from pathlib import Path

from tracecite.runtime.evidence_fidelity import enrich_search_leaf_context


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _payload(source: Path, *, line: int, label: str) -> dict:
    digest = _sha256(source)
    return {
        "operation": "search",
        "status": "ok",
        "outcome": "supported",
        "data": {"query": "Unhealthy"},
        "coverage": {"evidence_returned": 1},
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
    }


def test_search_context_surfaces_scoped_identifier_gap_and_sibling_fanout(tmp_path: Path) -> None:
    source = tmp_path / "evidence.log"
    source.write_text(
        "\n".join(
            [
                "name: resource.example/widget-1001",
                "resources:",
                "- health: Healthy",
                "localID: local-device",
                "name: resource.example/widget-1001",
                "- health: Unhealthy",
                "localID: local-device",
                "noise",
                "resource.example/widget-1002 ready",
                "resource.example/widget-1003 ready",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = enrich_search_leaf_context(
        _payload(source, line=6, label="- health: Unhealthy")
    )

    integrity = result["data"]["evidence_integrity"]
    row = integrity["scoped_identity"][0]
    hint = row["scoped_identity_hints"][0]
    verification = row["identity_verification"][0]

    assert hint["kind"] == "scope_uniqueness_unverified"
    assert hint["identifier_key"] == "localID"
    assert hint["identifier_value"] == "local-device"
    assert verification["status"] == "uniqueness_unverified_with_sibling_scope_fanout"
    assert verification["entity_count_observed"] == 1
    assert verification["sibling_entity_count_observed"] == 3
    assert {item["entity"] for item in verification["sibling_entities"]} == {
        "resource.example/widget-1001",
        "resource.example/widget-1002",
        "resource.example/widget-1003",
    }
    assert "does not by itself identify a root cause" in verification["causal_note"]
    assert "before using identifier-only correlation" in integrity["note"]


def test_structured_search_without_local_identifier_adds_no_identity_integrity(tmp_path: Path) -> None:
    source = tmp_path / "evidence.log"
    source.write_text(
        "name: resource.example/widget-1001\nresources:\n- health: Unhealthy\n",
        encoding="utf-8",
    )

    result = enrich_search_leaf_context(
        _payload(source, line=3, label="- health: Unhealthy")
    )

    assert "nearby:" in result["evidence"][0]["label"]
    assert "evidence_integrity" not in result["data"]
