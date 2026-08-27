from __future__ import annotations

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
