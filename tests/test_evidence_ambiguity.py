from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from tracecite.runtime.evidence_ambiguity import (
    scoped_identity_fanout_hints,
    verify_scoped_identity_gaps,
)


def test_reports_sibling_scope_fanout_without_causal_claim_or_query_plan() -> None:
    text = "\n".join(
        [
            "resource.example/widget-1001 ready",
            "resource.example/widget-1002 ready",
            "resource.example/widget-1003 failed",
        ]
    )
    hints = scoped_identity_fanout_hints(text)
    fanout = next(item for item in hints if item["kind"] == "sibling_scope_fanout")
    assert fanout["scope"] == "resource.example/"
    assert fanout["family"] == "widget-*"
    assert fanout["member_count"] == 3
    assert "navigation_query" not in fanout


def test_reports_unverified_local_identifier_as_fact_without_query_plan() -> None:
    text = "\n".join(
        [
            "- name: test.device/device-plugin-failures-3083",
            "  health: Healthy",
            "  resourceID: testdevice",
            "- name: test.device/device-plugin-failures-3083",
            "  health: Unhealthy",
            "  resourceID: testdevice",
        ]
    )
    hints = scoped_identity_fanout_hints(text)
    gap = next(item for item in hints if item["kind"] == "scope_uniqueness_unverified")
    assert gap["identifier_key"] == "resourceID"
    assert gap["identifier_value"] == "testdevice"
    assert "recommended_search" not in gap
    assert "recommended_action" not in gap
    assert gap["scopes"] == ["test.device/"]
    assert "test.device/device-plugin-failures-3083" in gap["scoped_entities"]
    assert "root cause" not in gap["verification"].lower()


def test_source_paths_and_dates_do_not_become_identity_scopes() -> None:
    text = "\n".join(
        [
            "created: 2026/07/06",
            "at k8s.io/kubernetes/test/e2e_node/device_plugin_test.go:177",
            "resourceID: local-device",
        ]
    )
    hints = scoped_identity_fanout_hints(text)
    assert not any(item["kind"] == "scope_uniqueness_unverified" for item in hints)


def test_uuid_like_identifier_does_not_trigger_scope_uniqueness_gap() -> None:
    text = "\n".join(
        [
            "name: worker.example/worker-1001",
            "requestID: 123e4567-e89b-12d3-a456-426614174000",
        ]
    )
    hints = scoped_identity_fanout_hints(text)
    assert not any(item["kind"] == "scope_uniqueness_unverified" for item in hints)


def test_identifier_without_nearby_scope_does_not_trigger_gap() -> None:
    text = "\n".join(
        [
            "requestID: local-17",
            "ordinary state transition",
            "ordinary state transition",
            "ordinary state transition",
            "ordinary state transition",
            "ordinary state transition",
            "name: worker.example/worker-1001",
        ]
    )
    hints = scoped_identity_fanout_hints(text)
    assert not any(item["kind"] == "scope_uniqueness_unverified" for item in hints)


def test_identity_gap_fact_precedes_broader_fanout() -> None:
    text = "\n".join(
        [
            "name: resource.example/widget-1001",
            "resourceID: local-device",
            "name: resource.example/widget-1002",
            "name: resource.example/widget-1003",
        ]
    )
    hints = scoped_identity_fanout_hints(text, limit=1)
    assert hints[0]["kind"] == "scope_uniqueness_unverified"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_verifies_one_identifier_across_multiple_scoped_entities(tmp_path: Path) -> None:
    source = tmp_path / "evidence.log"
    source.write_text(
        "\n".join(
            [
                "name: resource.example/widget-1001",
                "health: Healthy",
                "resourceID: local-device",
                "noise",
                "name: resource.example/widget-2002",
                "health: Unhealthy",
                "resourceID: local-device",
                "noise",
                "name: resource.example/widget-3003",
                "resourceID: another-device",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    visible = "\n".join(
        [
            "1: name: resource.example/widget-1001",
            "2: health: Healthy",
            "3: resourceID: local-device",
        ]
    )
    verification = verify_scoped_identity_gaps(
        source,
        visible,
        expected_sha256=_sha256(source),
    )
    assert len(verification) == 1
    result = verification[0]
    assert result["status"] == "multiple_scoped_entities_observed"
    assert result["identifier_value"] == "local-device"
    assert result["entity_count_observed"] == 2
    assert [row["entity"] for row in result["entities"]] == [
        "resource.example/widget-1001",
        "resource.example/widget-2002",
    ]
    assert result["entities"][0]["references"] == [
        {"entity_ref": "evidence.log:1", "identifier_ref": "evidence.log:3"}
    ]
    assert result["entities"][1]["references"] == [
        {"entity_ref": "evidence.log:5", "identifier_ref": "evidence.log:7"}
    ]
    assert "not source-unique" in result["finding"]
    assert "does not by itself identify a root cause" in result["causal_note"]


def test_single_direct_association_stays_unverified_when_sibling_family_coexists(tmp_path: Path) -> None:
    source = tmp_path / "evidence.log"
    source.write_text(
        "\n".join(
            [
                "name: test.device/device-plugin-failures-3083",
                "health: Healthy",
                "resourceID: testdevice",
                "node snapshot capacity: test.device/device-plugin-failures-3083=1 "
                "test.device/device-plugin-failures-5477=1 "
                "test.device/device-plugin-failures-6835=0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    visible = "\n".join(
        [
            "1: name: test.device/device-plugin-failures-3083",
            "2: health: Healthy",
            "3: resourceID: testdevice",
        ]
    )
    result = verify_scoped_identity_gaps(
        source,
        visible,
        expected_sha256=_sha256(source),
    )[0]
    assert result["entity_count_observed"] == 1
    assert result["status"] == "uniqueness_unverified_with_sibling_scope_fanout"
    assert result["sibling_entity_count_observed"] == 3
    assert [row["entity"] for row in result["sibling_entities"]] == [
        "test.device/device-plugin-failures-3083",
        "test.device/device-plugin-failures-5477",
        "test.device/device-plugin-failures-6835",
    ]
    assert "does not prove" in result["finding"]
    assert "identifier" in result["correlation_requirement"]
    assert "does not by itself identify a root cause" in result["causal_note"]


def test_verification_rejects_changed_source_hash(tmp_path: Path) -> None:
    source = tmp_path / "evidence.log"
    source.write_text(
        "name: resource.example/widget-1001\nresourceID: local-device\n",
        encoding="utf-8",
    )
    visible = "1: name: resource.example/widget-1001\n2: resourceID: local-device\n"
    with pytest.raises(ValueError, match="source changed"):
        verify_scoped_identity_gaps(
            source,
            visible,
            expected_sha256="0" * 64,
        )


def test_bounded_sibling_selection_prefers_entities_near_direct_identifier_evidence(tmp_path: Path) -> None:
    source = tmp_path / "evidence.log"
    rows = [f"name: resource.example/widget-{1000 + i}" for i in range(1, 12)]
    rows += ["noise"] * 80
    rows += [
        "name: resource.example/widget-9999",
        "name: resource.example/widget-1001",
        "resourceID: local-device",
    ]
    source.write_text("\n".join(rows) + "\n", encoding="utf-8")
    visible = "\n".join([
        "name: resource.example/widget-1001",
        "resourceID: local-device",
    ])
    result = verify_scoped_identity_gaps(
        source,
        visible,
        expected_sha256=_sha256(source),
        entity_limit=3,
    )[0]
    selected = [row["entity"] for row in result["sibling_entities"]]
    assert "resource.example/widget-1001" in selected
    assert "resource.example/widget-9999" in selected
    assert result["sibling_selection_basis"] == "nearest_to_direct_identifier_association"
