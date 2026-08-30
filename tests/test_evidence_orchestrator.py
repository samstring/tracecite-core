from __future__ import annotations

from pathlib import Path

from tracecite.extension.evidence import EntityRef
from tracecite.extension.retrieval import RetrieveRequest
from tracecite.integrations.investigator import investigate
from tracecite.integrations.json_evidence_provider import JsonEvidenceProvider
from tracecite.runtime.correlation import EvidenceNode, correlate
from tracecite.runtime.traversal_frontier import TraversalLimits
from tracecite.runtime.grouping import group_evidence
from tracecite.runtime.traversal import traverse_evidence
from tracecite.runtime.reducer import ReductionPolicy, reduce_evidence


CASE = (
    Path(__file__).resolve().parents[1]
    / "benchmarks"
    / "evidence-intelligence"
    / "cases"
    / "mobile-payment-crash"
)


def _providers() -> list[JsonEvidenceProvider]:
    return [
        JsonEvidenceProvider.from_path(CASE / name)
        for name in ("crash.json", "analytics.json", "network.json", "trace.json", "client.json")
    ]


def test_investigate_follows_session_request_trace_without_agent_loop() -> None:
    providers = _providers()
    result = investigate(
        providers,
        seed_evidence_ids=("crash:C123",),
        exploration_policy=TraversalLimits(
            max_depth=3,
            max_retrievals=20,
            max_no_growth_rounds=3,
        ),
        max_tokens=2400,
    )

    investigation = result.investigation
    ids = {node.id for node in investigation.graph.nodes}
    required = {
        "crash:C123",
        "event:tap-pay",
        "network:R19",
        "span:T22",
        "span:callback",
        "client:callback",
    }
    assert investigation.status == "ok"
    assert investigation.stop_reason == "frontier_exhausted"
    assert investigation.coverage["complete"] is True
    assert required <= ids
    assert "event:noise" not in ids
    assert "network:noise" not in ids
    assert investigation.coverage["retrievals"] < 12

    reasons = {step.reason for step in investigation.trace}
    assert "seed" in reasons
    assert "expand:app:session:S88" in reasons
    assert "expand:edge:request:R19" in reasons
    assert "expand:otel:trace:T22" in reasons

    package_ids = {item["id"] for item in result.package.evidence}
    assert required <= package_ids
    assert result.package.budget["within_budget"] is True


def test_package_citations_resolve_back_to_provider_records() -> None:
    providers = _providers()
    result = investigate(
        providers,
        seed_evidence_ids=("crash:C123",),
        exploration_policy=TraversalLimits(max_retrievals=20, max_no_growth_rounds=3),
        max_tokens=2400,
    )
    by_name = {provider.name: provider for provider in providers}

    for item in result.package.evidence:
        uri = str(item.get("uri") or "")
        assert uri.startswith("evidence+json://")
        resolved = None
        for provider in by_name.values():
            try:
                resolved = provider.resolve(uri)
                break
            except (KeyError, ValueError):
                continue
        assert resolved is not None
        assert resolved.id == item["id"]
        assert resolved.evidence_uri == uri


def test_missing_provider_evidence_is_explicitly_incomplete() -> None:
    class BrokenProvider:
        name = "broken"

        def can_handle(self, request: RetrieveRequest) -> bool:
            return True

        def retrieve(self, request: RetrieveRequest):
            raise RuntimeError("provider unavailable")

    result = traverse_evidence(
        [BrokenProvider()],
        seed_evidence_ids=("crash:missing",),
        exploration_policy=TraversalLimits(max_provider_errors=2),
    )
    assert result.status == "empty"
    assert result.coverage["complete"] is False
    assert result.coverage["provider_errors"] == 1
    assert result.coverage["missing_seed_ids"] == 1
    assert result.diagnostics["provider_non_ok"]


def test_retrieval_budget_stops_with_partial_coverage() -> None:
    result = traverse_evidence(
        _providers(),
        seed_evidence_ids=("crash:C123",),
        exploration_policy=TraversalLimits(
            max_retrievals=2,
            max_depth=3,
            max_no_growth_rounds=3,
        ),
    )
    assert result.status == "partial"
    assert result.stop_reason == "max_retrievals"
    assert result.coverage["complete"] is False
    assert result.coverage["retrievals"] == 2
    assert result.diagnostics["interrupted_entity"]


def test_namespace_prevents_false_exact_entity_correlation() -> None:
    left = EvidenceNode(
        id="a",
        kind="request",
        source="one",
        timestamp="2026-08-27T10:00:00Z",
        entities=(EntityRef("request", "R1", namespace="service-a"),),
    )
    right = EvidenceNode(
        id="b",
        kind="request",
        source="two",
        timestamp="2026-08-27T10:00:00Z",
        entities=(EntityRef("request", "R1", namespace="service-b"),),
    )

    strict = correlate((left, right))
    assert strict.relations == ()

    temporal = correlate((left, right), temporal_window_seconds=1.0)
    assert len(temporal.relations) == 1
    assert temporal.relations[0].basis == "timestamp_window"
    assert temporal.relations[0].confidence < 1.0


def test_same_entity_correlation_and_grouping_scale_linearly() -> None:
    session = EntityRef("session", "large", namespace="bench")
    nodes = tuple(
        EvidenceNode(
            id=f"log:{index:05d}",
            kind="log",
            source="client",
            timestamp=f"2026-08-27T10:00:{index % 60:02d}Z",
            severity="info",
            label=f"heartbeat {index}",
            entities=(session,),
            evidence_uri=f"evidence://scale/{index}",
            attributes={"message": f"heartbeat {index}"},
        )
        for index in range(10_000)
    )
    graph = correlate(nodes)
    assert len(graph.relations) == len(nodes) - 1

    grouping = group_evidence(graph.nodes)
    assert len(grouping.groups) == 1
    assert grouping.groups[0].count == 10_000
    assert len(grouping.groups[0].representative_ids) <= 3

    reduced = reduce_evidence(
        graph,
        grouping,
        policy=ReductionPolicy(max_items=3, seed_ids=("log:00000",)),
    )
    assert len(reduced.selected_ids) <= 3
    assert reduced.omitted_non_representative >= 9_997


def test_integration_investigator_delegates_public_runtime_facade(monkeypatch) -> None:
    import tracecite.integrations.investigator as facade
    from types import SimpleNamespace

    providers = _providers()
    canonical = traverse_evidence(
        providers,
        seed_evidence_ids=("crash:C123",),
        exploration_policy=TraversalLimits(max_retrievals=20, max_no_growth_rounds=3),
    )
    calls = []

    def fake_runtime_investigate(selected, **kwargs):
        calls.append((tuple(selected), kwargs))
        return SimpleNamespace(investigation=canonical)

    monkeypatch.setattr(facade, "runtime_investigate", fake_runtime_investigate)
    result = facade.investigate(
        providers,
        seed_evidence_ids=("crash:C123",),
        exploration_policy=TraversalLimits(max_retrievals=20, max_no_growth_rounds=3),
        max_tokens=2400,
    )

    assert len(calls) == 1
    assert calls[0][1]["seed_evidence_ids"] == ("crash:C123",)
    assert result.investigation is canonical
    assert result.package.evidence


def test_integration_investigator_does_not_import_orchestrator_function() -> None:
    import inspect
    import tracecite.integrations.investigator as facade

    source = inspect.getsource(facade)
    assert "traverse_evidence(" not in source
    assert "runtime_investigate(" in source
