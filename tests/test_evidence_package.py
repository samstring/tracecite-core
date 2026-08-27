from __future__ import annotations

from tracecite.evidence import EntityRef
from tracecite.integrations.evidence_package import build_evidence_package, estimate_json_tokens
from tracecite.runtime.correlation import EvidenceNode, correlate
from tracecite.runtime.grouping import group_evidence
from tracecite.runtime.reducer import ReductionPolicy, reduce_evidence


def test_package_respects_budget_and_exposes_omissions_and_recovery() -> None:
    session = EntityRef("session", "S-1")
    nodes = [
        EvidenceNode(
            "crash",
            "crash",
            "bugly",
            severity="fatal",
            label="fatal checkout crash",
            entities=(session,),
            evidence_uri="evidence://crash#1",
        ),
        *[
            EvidenceNode(
                f"e-{index}",
                "log",
                "client",
                severity="error" if index % 7 == 0 else "info",
                label=f"request {index} timeout while checkout was active",
                entities=(session,),
                evidence_uri=f"evidence://log#{index}",
            )
            for index in range(40)
        ],
    ]
    graph = correlate(nodes)
    grouping = group_evidence(nodes)
    reduction = reduce_evidence(graph, grouping, policy=ReductionPolicy(max_items=10, seed_ids=("crash",)))

    package = build_evidence_package(graph, grouping, reduction, max_tokens=700)
    payload = package.to_dict()

    assert payload["budget"]["within_budget"] is True
    assert estimate_json_tokens({key: value for key, value in payload.items() if key != "package_id"}) <= 700
    assert payload["coverage"]["canonical_evidence"] == 41
    assert payload["coverage"]["truncated"] is True
    assert payload["evidence"][0]["id"] == "crash"
    assert payload["coverage"]["package_evidence"] < 41
