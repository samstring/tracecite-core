from __future__ import annotations

from tracecite.extension.evidence import EntityRef
from tracecite.runtime.correlation import EvidenceNode
from tracecite.runtime.grouping import group_evidence, normalize_template


def test_template_normalization_collapses_high_cardinality_values() -> None:
    assert normalize_template("request 123 timed out after 5000 ms") == "request <n> timed out after <n> ms"
    assert normalize_template("request 999 timed out after 6000 ms") == "request <n> timed out after <n> ms"


def test_grouping_selects_first_severe_and_last_representatives() -> None:
    nodes = [
        EvidenceNode("e1", "log", "client", timestamp="2026-01-01T00:00:01Z", label="request 1 timeout"),
        EvidenceNode("e2", "log", "client", timestamp="2026-01-01T00:00:02Z", severity="error", label="request 2 timeout"),
        EvidenceNode("e3", "log", "client", timestamp="2026-01-01T00:00:03Z", label="request 3 timeout"),
        EvidenceNode("e4", "log", "client", timestamp="2026-01-01T00:00:04Z", label="request 4 timeout"),
    ]

    result = group_evidence(nodes)
    group = result.groups[0]

    assert group.count == 4
    assert group.representative_ids == ("e1", "e2", "e4")
    assert result.collapsed_count == 1
    assert set(result.node_to_group) == {"e1", "e2", "e3", "e4"}


def test_same_exact_entity_still_groups_high_cardinality_message_values() -> None:
    request = EntityRef(kind="request", value="checkout-7", namespace="mobile")
    nodes = [
        EvidenceNode("e1", "log", "client", label="retry 123 timeout 5000", entities=(request,)),
        EvidenceNode("e2", "log", "client", label="retry 999 timeout 6000", entities=(request,)),
    ]

    result = group_evidence(nodes)

    assert len(result.groups) == 1
    assert result.groups[0].member_ids == ("e1", "e2")
    assert result.groups[0].template == "retry <n> timeout <n>"


def test_different_exact_entities_are_never_collapsed_by_template_normalization() -> None:
    nodes = [
        EvidenceNode(
            "e1",
            "log",
            "kubelet",
            label="device 123 became unhealthy",
            entities=(EntityRef(kind="pod", value="device-plugin-3083", namespace="test.device"),),
        ),
        EvidenceNode(
            "e2",
            "log",
            "kubelet",
            label="device 999 became unhealthy",
            entities=(EntityRef(kind="pod", value="device-plugin-5477", namespace="test.device"),),
        ),
    ]

    result = group_evidence(nodes)

    assert len(result.groups) == 2
    assert result.collapsed_count == 0
    assert result.node_to_group["e1"] != result.node_to_group["e2"]
    assert {group.template for group in result.groups} == {"device <n> became unhealthy"}


def test_entity_set_order_does_not_change_group_identity() -> None:
    request = EntityRef(kind="request", value="7", namespace="mobile")
    session = EntityRef(kind="session", value="abc", namespace="mobile")
    nodes = [
        EvidenceNode("e1", "log", "client", label="retry 1", entities=(request, session)),
        EvidenceNode("e2", "log", "client", label="retry 2", entities=(session, request)),
    ]

    result = group_evidence(nodes)

    assert len(result.groups) == 1
    assert result.groups[0].member_ids == ("e1", "e2")
