from __future__ import annotations

from tracecite.evidence import EntityRef, EvidenceRelation
from tracecite.runtime.correlation import EvidenceNode, correlate
from tracecite.runtime.grouping import group_evidence
from tracecite.runtime.reducer import ReductionPolicy, reduce_evidence


def test_reducer_keeps_seed_related_and_diverse_representatives() -> None:
    session = EntityRef("session", "S-1")
    request = EntityRef("request", "R-9")
    nodes = [
        EvidenceNode("crash", "crash", "bugly", severity="fatal", entities=(session,), label="crash"),
        EvidenceNode("tap", "event", "analytics", entities=(session,), label="tap pay"),
        EvidenceNode("http", "network", "client", severity="error", entities=(session, request), label="request 9 timeout"),
        EvidenceNode("span", "span", "otel", severity="error", entities=(request,), label="gateway timeout"),
        *[
            EvidenceNode(f"dup-{index}", "log", "client", entities=(session,), label=f"retry {index} timeout")
            for index in range(20)
        ],
    ]
    graph = correlate(nodes)
    grouping = group_evidence(nodes)

    result = reduce_evidence(graph, grouping, policy=ReductionPolicy(max_items=4, seed_ids=("crash",)))

    assert "crash" in result.selected_ids
    assert "http" in result.selected_ids
    assert "span" in result.selected_ids
    assert result.omitted_non_representative > 0
    assert len(result.selected_ids) == 4
    assert len({graph.by_id[item].source for item in result.selected_ids}) >= 3
    assert result.diagnostics["score_semantics"] == "retention_priority_not_causal_likelihood"


def test_exact_entity_relation_has_lower_retention_cost_than_weak_relation() -> None:
    session = EntityRef("session", "S-1")
    nodes = [
        EvidenceNode("seed", "event", "client", entities=(session,), label="start"),
        EvidenceNode("exact", "event", "server", entities=(session,), label="same session"),
        EvidenceNode("weak", "event", "worker", label="nearby only"),
    ]
    graph = correlate(
        nodes,
        declared_relations=(
            EvidenceRelation(
                "seed",
                "weak",
                "temporal_near",
                "timestamp_window",
                confidence=0.5,
            ),
        ),
    )

    result = reduce_evidence(
        graph,
        group_evidence(nodes),
        policy=ReductionPolicy(max_items=3, seed_ids=("seed",)),
    )
    ranked = {item.id: item for item in result.ranked}

    assert "retention_path_cost:1" in ranked["exact"].reasons
    assert "retention_path_cost:3" in ranked["weak"].reasons
    assert ranked["exact"].score > ranked["weak"].score
    assert ranked["exact"].to_dict()["score_semantics"] == "retention_priority"


def test_max_graph_distance_bounds_weak_retention_expansion() -> None:
    nodes = [
        EvidenceNode("seed", "event", "client", label="start"),
        EvidenceNode("weak", "event", "worker", label="nearby only"),
    ]
    graph = correlate(
        nodes,
        declared_relations=(
            EvidenceRelation(
                "seed",
                "weak",
                "temporal_near",
                "timestamp_window",
                confidence=0.5,
            ),
        ),
    )

    result = reduce_evidence(
        graph,
        group_evidence(nodes),
        policy=ReductionPolicy(max_items=2, seed_ids=("seed",), max_graph_distance=2),
    )
    ranked = {item.id: item for item in result.ranked}

    assert not any(reason.startswith("retention_path_cost:") for reason in ranked["weak"].reasons)
    assert result.diagnostics["connected_candidates"] == 1
