from __future__ import annotations

from tracecite.evidence import EntityRef, EvidenceRelation
from tracecite.runtime.correlation import EvidenceNode, correlate


def test_exact_entities_form_bounded_connected_graph() -> None:
    session = EntityRef("session", "S-1")
    nodes = [
        EvidenceNode(f"e{index}", "log", "client", entities=(session,))
        for index in range(10)
    ]

    graph = correlate(nodes)

    assert len(graph.relations) == 9
    assert set(graph.distance(["e0"]).values()) == {0, 1}
    assert graph.relations[0].basis == "exact_entity"


def test_declared_and_temporal_relations_are_explainable() -> None:
    nodes = [
        EvidenceNode("client", "request", "mobile", timestamp="2026-01-01T00:00:00Z"),
        EvidenceNode("server", "span", "otel", timestamp="2026-01-01T00:00:02Z"),
    ]
    declared = EvidenceRelation("client", "server", "propagated", "domain_declared", confidence=1.0)

    graph = correlate(nodes, declared_relations=(declared,), temporal_window_seconds=10)

    assert {item.basis for item in graph.relations} == {"domain_declared", "timestamp_window"}
    assert graph.distance(["client"])["server"] == 1
