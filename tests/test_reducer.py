from __future__ import annotations

from tracecite.evidence import EntityRef
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
