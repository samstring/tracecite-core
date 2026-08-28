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
    with pytest.raises(ValueError, match="investigate_max_evidence"):
        EvidenceRoutingPolicy(
            bounded_max_evidence=5,
            investigate_max_evidence=6,
        )
    with pytest.raises(ValueError, match="investigate_max_line_chars"):
        EvidenceRoutingPolicy(
            bounded_max_line_chars=400,
            investigate_max_line_chars=401,
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


def test_after_direct_read_query_becomes_bounded_and_can_escalate(tmp_path) -> None:
    source = tmp_path / "runtime.log"
    source.write_text("".join(f"ERROR item={i}\n" for i in range(20)), encoding="utf-8")
    state_path = tmp_path / "investigation.json"
    InvestigationStore(state_path).create("inspect then search")
    policy = EvidenceRoutingPolicy(
        fallback_direct_chars=8_000,
        max_direct_chars=8_000,
        bounded_max_evidence=5,
        investigate_max_evidence=2,
        bounded_match_records=4,
        investigate_match_records=100,
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
    assert payload["data"]["routing"]["next_mode"] == "investigate"
    assert payload["coverage"]["match_records"] == 20
    assert payload["coverage"]["evidence_returned"] == 5
    assert payload["coverage"]["evidence_truncated"] is True


def test_deep_query_uses_tighter_investigate_transport_cap(tmp_path) -> None:
    source = tmp_path / "runtime.log"
    source.write_text("".join(f"ERROR item={i}\n" for i in range(20)), encoding="utf-8")
    state_path = tmp_path / "investigation.json"
    InvestigationStore(state_path).create("deep query")
    policy = EvidenceRoutingPolicy(
        fallback_direct_chars=1,
        max_direct_chars=1,
        bounded_max_evidence=5,
        investigate_max_evidence=2,
        bounded_max_line_chars=128,
        investigate_max_line_chars=64,
        investigate_after_executions=2,
        investigate_match_records=100,
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

    assert payload["data"]["routing"]["mode"] == EvidenceRoute.INVESTIGATE.value
    assert "exploration_depth" in payload["data"]["routing"]["reasons"]
    assert payload["coverage"]["match_records"] == 20
    assert payload["coverage"]["evidence_returned"] == 2
    assert payload["coverage"]["evidence_truncated"] is True


def test_large_first_source_uses_bounded_probe_instead_of_direct_dump(tmp_path) -> None:
    source = tmp_path / "large.log"
    source.write_text("x" * 12_000 + "\n", encoding="utf-8")
    state_path = tmp_path / "investigation.json"
    InvestigationStore(state_path).create("inspect large source")

    result = retrieve(
        EvidenceRequest(SourceTarget(source), investigation_path=state_path),
        routing_policy=EvidenceRoutingPolicy(
            fallback_direct_chars=2_000,
            max_direct_chars=2_000,
        ),
    )
    payload = result.to_dict()

    assert result.operation == "probe"
    assert payload["data"]["routing"]["mode"] == "bounded"
    assert "direct_output_exceeds_budget" in payload["data"]["routing"]["reasons"]
    assert "text" not in payload["data"]


def test_deep_history_monotonically_escalates_source_inspection_to_investigate(tmp_path) -> None:
    source = tmp_path / "runtime.log"
    source.write_text("alpha\nbeta\ngamma\ndelta\n", encoding="utf-8")
    state_path = tmp_path / "investigation.json"
    InvestigationStore(state_path).create("deep investigation")
    policy = EvidenceRoutingPolicy(
        fallback_direct_chars=8_000,
        max_direct_chars=8_000,
        investigate_after_executions=4,
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

    assert payload["data"]["routing"]["mode"] == EvidenceRoute.INVESTIGATE.value
    assert "exploration_depth" in payload["data"]["routing"]["reasons"]
    assert result.operation == "survey"
