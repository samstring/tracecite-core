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


def test_investigate_transport_must_not_be_wider_than_bounded_transport() -> None:
    with pytest.raises(ValueError, match="focused_max_evidence"):
        EvidenceRoutingPolicy(
            bounded_max_evidence=5,
            focused_max_evidence=6,
        )
    with pytest.raises(ValueError, match="focused_max_line_chars"):
        EvidenceRoutingPolicy(
            bounded_max_line_chars=400,
            focused_max_line_chars=401,
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
    assert payload["coverage"]["context_start_line"] == 1
    assert payload["coverage"]["context_end_line"] == 3


def test_direct_query_keeps_lossless_raw_source_context(tmp_path) -> None:
    source = tmp_path / "runtime.log"
    source.write_text(
        "tap pay\napp background\nobject released\nlate callback\nCRASH\n",
        encoding="utf-8",
    )
    state_path = tmp_path / "investigation.json"
    InvestigationStore(state_path).create("diagnose crash")

    result = retrieve(
        EvidenceRequest(
            QueryTarget(source, "CRASH", snapshot=False),
            investigation_path=state_path,
        ),
        routing_policy=EvidenceRoutingPolicy(
            fallback_direct_chars=8_000,
            max_direct_chars=8_000,
        ),
    )
    payload = result.to_dict()

    assert payload["data"]["routing"]["mode"] == "direct"
    assert payload["data"]["direct_raw"]["fidelity"] == "lossless_line_addressable"
    assert "runtime.log:1 tap pay" in payload["data"]["text"]
    assert "runtime.log:2 app background" in payload["data"]["text"]
    assert "runtime.log:3 object released" in payload["data"]["text"]
    assert "runtime.log:4 late callback" in payload["data"]["text"]
    assert "runtime.log:5 CRASH" in payload["data"]["text"]
    assert payload["coverage"]["direct_raw_lines"] == 5


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
        focused_after_executions=2,
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


def test_repeated_query_same_source_does_not_repeat_raw_direct_dump(tmp_path) -> None:
    source = tmp_path / "runtime.log"
    source.write_text("alpha\nERROR one\nomega\n", encoding="utf-8")
    state_path = tmp_path / "investigation.json"
    InvestigationStore(state_path).create("repeat search")
    policy = EvidenceRoutingPolicy(
        fallback_direct_chars=8_000,
        max_direct_chars=8_000,
        focused_after_executions=10,
    )

    first = retrieve(
        EvidenceRequest(QueryTarget(source, "ERROR", snapshot=False), investigation_path=state_path),
        routing_policy=policy,
    ).to_dict()
    second = retrieve(
        EvidenceRequest(QueryTarget(source, "ERROR", snapshot=False), investigation_path=state_path),
        routing_policy=policy,
    ).to_dict()

    assert first["data"]["routing"]["mode"] == "direct"
    assert "direct_raw" in first["data"]
    assert second["data"]["routing"]["mode"] == "bounded"
    assert "source_already_seen" in second["data"]["routing"]["reasons"]
    assert "direct_raw" not in second["data"]


def _assert_complete_error_index(payload: dict) -> None:
    assert "evidence_index" not in payload["coverage"]
    index = payload["data"]["evidence_index"]
    assert index["total_matches"] == 20
    assert index["entries"] == [
        {"rule": "ERROR", "count": 20, "lines": list(range(1, 21))}
    ]


def test_after_direct_read_query_becomes_bounded_and_can_escalate(tmp_path) -> None:
    source = tmp_path / "runtime.log"
    source.write_text("".join(f"ERROR item={i}\n" for i in range(20)), encoding="utf-8")
    state_path = tmp_path / "investigation.json"
    InvestigationStore(state_path).create("inspect then search")
    policy = EvidenceRoutingPolicy(
        fallback_direct_chars=8_000,
        max_direct_chars=8_000,
        bounded_max_evidence=5,
        focused_max_evidence=2,
        bounded_match_records=4,
        focused_match_records=100,
    )

    first = retrieve(
        EvidenceRequest(SourceTarget(source), investigation_path=state_path),
        routing_policy=policy,
    )
    assert first.to_dict()["data"]["routing"]["mode"] == "direct"

    searched = retrieve(
        EvidenceRequest(
            QueryTarget(source, "ERROR", snapshot=False),
            investigation_path=state_path,
        ),
        routing_policy=policy,
    )
    payload = searched.to_dict()

    assert payload["data"]["routing"]["mode"] == "bounded"
    assert payload["data"]["routing"]["next_mode"] == "focused"
    assert payload["coverage"]["match_records"] == 20
    assert payload["coverage"]["evidence_returned"] == 0
    assert payload["coverage"]["evidence_indexed"] is True
    assert payload["coverage"]["evidence_truncated"] is False
    _assert_complete_error_index(payload)


def test_deep_query_uses_tighter_investigate_transport_cap(tmp_path) -> None:
    source = tmp_path / "runtime.log"
    source.write_text("".join(f"ERROR item={i}\n" for i in range(20)), encoding="utf-8")
    state_path = tmp_path / "investigation.json"
    InvestigationStore(state_path).create("deep query")
    policy = EvidenceRoutingPolicy(
        fallback_direct_chars=1,
        max_direct_chars=1,
        bounded_max_evidence=5,
        focused_max_evidence=2,
        bounded_max_line_chars=128,
        focused_max_line_chars=64,
        focused_after_executions=2,
        focused_match_records=100,
    )

    for query in ("item=0", "item=1"):
        retrieve(
            EvidenceRequest(
                QueryTarget(source, query, snapshot=False),
                investigation_path=state_path,
            ),
            routing_policy=policy,
        )

    result = retrieve(
        EvidenceRequest(
            QueryTarget(source, "ERROR", snapshot=False),
            investigation_path=state_path,
        ),
        routing_policy=policy,
    )
    payload = result.to_dict()

    assert payload["data"]["routing"]["mode"] == EvidenceRoute.FOCUSED.value
    assert "exploration_depth" in payload["data"]["routing"]["reasons"]
    assert payload["coverage"]["match_records"] == 20
    assert payload["coverage"]["evidence_returned"] == 0
    assert payload["coverage"]["evidence_indexed"] is True
    assert payload["coverage"]["evidence_truncated"] is False
    _assert_complete_error_index(payload)


def test_large_first_source_uses_bounded_uniform_navigation_sample(tmp_path) -> None:
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
    assert payload["data"]["routing"]["mode"] == "bounded"
    assert "direct_output_exceeds_budget" in payload["data"]["routing"]["reasons"]
    assert payload["data"]["strategy"] == "uniform"
    assert payload["data"]["navigation_only"] is True
    assert payload["coverage"]["sampled_records"] == 64
    assert payload["coverage"]["returned_chars"] <= 12_000
    assert payload["data"]["samples"]
    assert any(
        sample.get("start_line") == 89 and "MIDPOINT_STRUCTURAL_LANDMARK" in sample.get("text", "")
        for sample in payload["data"]["samples"]
    )


def test_deep_history_monotonically_escalates_source_inspection_to_investigate(tmp_path) -> None:
    source = tmp_path / "runtime.log"
    source.write_text("alpha\nbeta\ngamma\ndelta\n", encoding="utf-8")
    state_path = tmp_path / "investigation.json"
    InvestigationStore(state_path).create("deep investigation")
    policy = EvidenceRoutingPolicy(
        fallback_direct_chars=8_000,
        max_direct_chars=8_000,
        focused_after_executions=4,
    )

    for query in ("alpha", "beta", "gamma", "delta"):
        retrieve(
            EvidenceRequest(
                QueryTarget(source, query, snapshot=False),
                investigation_path=state_path,
            ),
            routing_policy=policy,
        )

    result = retrieve(
        EvidenceRequest(SourceTarget(source), investigation_path=state_path),
        routing_policy=policy,
    )
    payload = result.to_dict()

    assert payload["data"]["routing"]["mode"] == EvidenceRoute.FOCUSED.value
    assert "exploration_depth" in payload["data"]["routing"]["reasons"]
    assert result.operation == "survey"
