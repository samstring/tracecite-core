from __future__ import annotations

import hashlib
from pathlib import Path

from tracecite.integrations.agent_projection import project
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


def test_agent_projection_wires_structured_context_without_changing_full_view(tmp_path: Path) -> None:
    source = tmp_path / "events.log"
    source.write_text(
        "name: service.example/worker-1001\nstate: degraded\nlocalID: worker-a\n",
        encoding="utf-8",
    )
    payload = _search_payload(source, label="state: degraded", line=2)

    agent = project(payload, profile="agent")
    full = project(payload, profile="full")

    assert "events.log:1 name: service.example/worker-1001" in agent["evidence"][0]["label"]
    assert "events.log:3 localID: worker-a" in agent["evidence"][0]["label"]
    assert full == payload
    assert full["evidence"][0]["label"] == "state: degraded"


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
