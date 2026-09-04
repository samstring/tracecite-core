from __future__ import annotations

import pytest

from tracecite.runtime import (
    EvidenceRequest,
    EvidenceRoute,
    EvidenceRoutingPolicy,
    InvestigationStore,
    QueryTarget,
    SourceTarget,
    retrieve,
)


def test_routing_policy_uses_remaining_context_fraction_not_magic_file_size() -> None:
    policy = EvidenceRoutingPolicy(
        remaining_context_tokens=10_000,
        direct_context_fraction=0.10,
        fallback_direct_chars=2_000,
        max_direct_chars=100_000,
    )
    assert policy.direct_char_budget == 4_000


def test_deep_progressive_transport_must_not_be_wider_than_progressive_transport() -> None:
    with pytest.raises(ValueError, match="deep_progressive_max_candidates"):
        EvidenceRoutingPolicy(
            progressive_max_candidates=5,
            deep_progressive_max_candidates=6,
        )
    with pytest.raises(ValueError, match="deep_progressive_max_line_chars"):
        EvidenceRoutingPolicy(
            progressive_max_line_chars=400,
            deep_progressive_max_line_chars=401,
        )


def test_small_first_source_uses_direct_line_addressable_path(tmp_path) -> None:
    source = tmp_path / "issue.md"
    source.write_text("first\nsecond\nthird\n", encoding="utf-8")
    state_path = tmp_path / "investigation.json"
    InvestigationStore(state_path).create("inspect the issue")

    result = retrieve(
        EvidenceRequest(SourceTarget(source), investigation_path=state_path),
        routing_policy=EvidenceRoutingPolicy(
            fallback_direct_chars=8_000,
            max_direct_chars=8_000,
        ),
    )
    payload = result.to_dict()

    assert result.operation == "expand"
    assert result.status == "ok"
    assert payload["data"]["routing"]["mode"] == "direct"
    assert "1: first" in payload["data"]["text"]
    assert "2: second" in payload["data"]["text"]
    assert "3: third" in payload["data"]["text"]


def test_query_uses_shell_contract_not_direct_raw_dump(tmp_path) -> None:
    source = tmp_path / "runtime.log"
    source.write_text(
        "tap pay\napp background\nobject released\nlate callback\nCRASH\n",
        encoding="utf-8",
    )
    state_path = tmp_path / "investigation.json"
    InvestigationStore(state_path).create("diagnose crash")

    payload = retrieve(
        EvidenceRequest(
            QueryTarget(source, "CRASH", snapshot=False),
            investigation_path=state_path,
        ),
        routing_policy=EvidenceRoutingPolicy(
            fallback_direct_chars=8_000,
            max_direct_chars=8_000,
        ),
    ).to_dict()

    assert payload["status"] == "ok"
    assert len(payload["evidence"]) == 1
    assert "CRASH" in payload["evidence"][0]["label"]
    assert "routing" not in payload["data"]
    assert "direct_raw" not in payload["data"]
    assert "text" not in payload["data"]
    assert payload["data"]["source_version"]


def test_multiple_unseen_tiny_sources_stay_direct_while_aggregate_fits_budget(tmp_path) -> None:
    sources = []
    for index in range(5):
        source = tmp_path / f"part-{index}.log"
        source.write_text(f"event source={index}\nstate ok={index}\n", encoding="utf-8")
        sources.append(source)
    state_path = tmp_path / "investigation.json"
    InvestigationStore(state_path).create("inspect tiny multi-source incident")
    policy = EvidenceRoutingPolicy(
        fallback_direct_chars=8_000,
        max_direct_chars=8_000,
        deep_progressive_after_executions=2,
    )

    modes = []
    reasons = []
    for source in sources:
        result = retrieve(
            EvidenceRequest(SourceTarget(source), investigation_path=state_path),
            routing_policy=policy,
        )
        routing = result.to_dict()["data"]["routing"]
        modes.append(routing["mode"])
        reasons.extend(routing["reasons"])

    assert modes == ["direct"] * len(sources)
    assert "aggregate_line_addressable_sources_fit_budget" in reasons


def test_repeated_query_suppresses_body_without_changing_source_version(tmp_path) -> None:
    source = tmp_path / "runtime.log"
    source.write_text("alpha\nERROR one\nomega\n", encoding="utf-8")
    state_path = tmp_path / "investigation.json"
    InvestigationStore(state_path).create("repeat search")

    first = retrieve(
        EvidenceRequest(QueryTarget(source, "ERROR", snapshot=False), investigation_path=state_path),
    ).to_dict()
    second = retrieve(
        EvidenceRequest(QueryTarget(source, "ERROR", snapshot=False), investigation_path=state_path),
    ).to_dict()

    assert first["status"] == "ok"
    assert len(first["evidence"]) == 1
    assert second["status"] == "no_new_evidence"
    assert second["evidence"] == []
    assert second["data"]["source_version"] == first["data"]["source_version"]
    repeated = second["data"]["matched_existing_evidence"]
    assert repeated[0]["start_line"] == 2
    assert repeated[0]["sha256"]


def test_source_direct_read_does_not_force_query_into_legacy_progressive_path(tmp_path) -> None:
    source = tmp_path / "runtime.log"
    source.write_text("".join(f"ERROR item={i}\n" for i in range(20)), encoding="utf-8")
    state_path = tmp_path / "investigation.json"
    InvestigationStore(state_path).create("inspect then search")
    policy = EvidenceRoutingPolicy(
        fallback_direct_chars=8_000,
        max_direct_chars=8_000,
        progressive_max_candidates=5,
        deep_progressive_max_candidates=2,
    )

    first = retrieve(
        EvidenceRequest(SourceTarget(source), investigation_path=state_path),
        routing_policy=policy,
    )
    assert first.to_dict()["data"]["routing"]["mode"] == "direct"

    payload = retrieve(
        EvidenceRequest(QueryTarget(source, "ERROR", snapshot=False), investigation_path=state_path),
        routing_policy=policy,
    ).to_dict()

    assert payload["status"] == "ok"
    assert payload["coverage"]["match_records"] == 20
    assert len(payload["evidence"]) == 20
    assert "routing" not in payload["data"]
    assert "evidence_index" not in payload["data"]


def test_query_candidate_caps_in_routing_policy_do_not_truncate_shell_results(tmp_path) -> None:
    source = tmp_path / "runtime.log"
    source.write_text("".join(f"ERROR item={i}\n" for i in range(20)), encoding="utf-8")
    state_path = tmp_path / "investigation.json"
    InvestigationStore(state_path).create("deep query")
    policy = EvidenceRoutingPolicy(
        fallback_direct_chars=1,
        max_direct_chars=1,
        progressive_max_candidates=5,
        deep_progressive_max_candidates=2,
        progressive_max_line_chars=128,
        deep_progressive_max_line_chars=64,
        deep_progressive_after_executions=2,
    )

    for query in ("item=0", "item=1"):
        retrieve(
            EvidenceRequest(QueryTarget(source, query, snapshot=False), investigation_path=state_path),
            routing_policy=policy,
        )

    payload = retrieve(
        EvidenceRequest(QueryTarget(source, "ERROR", snapshot=False), investigation_path=state_path),
        routing_policy=policy,
    ).to_dict()

    assert payload["status"] == "ok"
    assert payload["coverage"]["match_records"] == 20
    assert len(payload["evidence"]) == 18  # two records were already exposed by earlier queries
    assert payload["coverage"]["repeated_evidence"] == 2
    assert "evidence_index" not in payload["data"]


def test_large_first_source_uses_progressive_uniform_navigation_sample(tmp_path) -> None:
    source = tmp_path / "large.log"
    rows = [f"record {index}" for index in range(623)]
    rows[88] = "MIDPOINT_STRUCTURAL_LANDMARK"
    source.write_text("\n".join(rows) + "\n", encoding="utf-8")
    state_path = tmp_path / "investigation.json"
    InvestigationStore(state_path).create("inspect large source")

    result = retrieve(
        EvidenceRequest(SourceTarget(source), investigation_path=state_path),
        routing_policy=EvidenceRoutingPolicy(
            fallback_direct_chars=200,
            max_direct_chars=200,
        ),
    )
    payload = result.to_dict()

    assert result.operation == "sample"
    assert payload["data"]["routing"]["mode"] == "progressive"
    assert "direct_output_exceeds_budget" in payload["data"]["routing"]["reasons"]
    assert payload["data"]["strategy"] == "uniform"
    assert payload["data"]["navigation_only"] is True
    assert payload["coverage"]["sampled_records"] == 64
    assert payload["coverage"]["returned_chars"] <= 12_000
    assert any(
        sample.get("start_line") == 89 and "MIDPOINT_STRUCTURAL_LANDMARK" in sample.get("text", "")
        for sample in payload["data"]["samples"]
    )


def test_query_execution_history_can_still_drive_source_target_routing(tmp_path) -> None:
    source = tmp_path / "runtime.log"
    source.write_text("alpha\nbeta\ngamma\ndelta\n", encoding="utf-8")
    state_path = tmp_path / "investigation.json"
    InvestigationStore(state_path).create("deep investigation")
    policy = EvidenceRoutingPolicy(
        fallback_direct_chars=8_000,
        max_direct_chars=8_000,
        deep_progressive_after_executions=4,
    )

    for query in ("alpha", "beta", "gamma", "delta"):
        retrieve(
            EvidenceRequest(QueryTarget(source, query, snapshot=False), investigation_path=state_path),
            routing_policy=policy,
        )

    result = retrieve(
        EvidenceRequest(SourceTarget(source), investigation_path=state_path),
        routing_policy=policy,
    )
    payload = result.to_dict()

    assert payload["data"]["routing"]["mode"] == EvidenceRoute.PROGRESSIVE.value
    assert "exploration_depth" in payload["data"]["routing"]["reasons"]
    assert result.operation == "survey"


def test_query_shell_transport_has_no_public_direct_progressive_mode(tmp_path) -> None:
    source = tmp_path / "routing.log"
    source.write_text("ERROR one\nERROR two\n", encoding="utf-8")
    state_path = tmp_path / "investigation.json"
    InvestigationStore(state_path).create("routing contract")

    source_result = retrieve(
        EvidenceRequest(SourceTarget(source), investigation_path=state_path),
        routing_policy=EvidenceRoutingPolicy(fallback_direct_chars=8_000, max_direct_chars=8_000),
    ).to_dict()
    query_result = retrieve(
        EvidenceRequest(QueryTarget(source, "ERROR", snapshot=False), investigation_path=state_path),
        routing_policy=EvidenceRoutingPolicy(fallback_direct_chars=8_000, max_direct_chars=8_000),
    ).to_dict()

    assert source_result["data"]["routing"]["mode"] in {"direct", "progressive"}
    assert "routing" not in query_result["data"]


def test_legacy_bounded_and_focused_policy_inputs_normalize_to_progressive() -> None:
    assert EvidenceRoutingPolicy(mode="bounded").mode == "progressive"
    assert EvidenceRoutingPolicy(mode="focused").mode == "progressive"
