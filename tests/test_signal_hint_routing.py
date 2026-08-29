from __future__ import annotations

from tracecite.runtime import (
    EvidenceRequest,
    EvidenceRoutingPolicy,
    InvestigationStore,
    QueryTarget,
    RangeTarget,
    retrieve,
)


def test_truncated_search_exposes_late_panic_as_hint_until_materialized(tmp_path) -> None:
    source = tmp_path / "kubelet.log"
    rows = [f"ERROR worker shard={index} failed transiently\n" for index in range(1, 41)]
    rows.append(
        "panic: failed to set defaults: PodLevelResourcesFixDefaulting is enabled "
        "but PodLevelResources is disabled\n"
    )
    source.write_text("".join(rows), encoding="utf-8")

    state_path = tmp_path / "investigation.json"
    InvestigationStore(state_path).create("find the root cause")
    policy = EvidenceRoutingPolicy(
        fallback_direct_chars=1,
        max_direct_chars=1,
        bounded_max_evidence=5,
        investigate_max_evidence=2,
        signal_hint_limit=4,
        signal_signature_cap=16,
        investigate_match_records=100,
    )

    searched = retrieve(
        EvidenceRequest(
            QueryTarget(
                source,
                r"panic|fatal|error|failed|crash",
                regex=True,
                snapshot=False,
            ),
            investigation_path=state_path,
        ),
        routing_policy=policy,
    )
    payload = searched.to_dict()

    assert payload["coverage"]["match_records"] == 41
    assert payload["coverage"]["evidence_returned"] == 5
    assert payload["coverage"]["evidence_truncated"] is True
    assert all(item.get("start_line") != 41 for item in payload["evidence"])

    hints = payload["data"]["signal_hints"]
    panic = next(item for item in hints if item["line"] == 41)
    assert panic["ref"] == "kubelet.log:41"
    assert panic["severity"] == 4
    assert "PodLevelResourcesFixDefaulting" in panic["label"]
    assert "materialize" in payload["data"]["signal_hint_note"].lower()

    recovered = retrieve(
        EvidenceRequest(
            RangeTarget(source, panic["line"], before=0, after=0),
            investigation_path=state_path,
        ),
        routing_policy=policy,
    ).to_dict()

    assert recovered["status"] == "ok"
    assert recovered["coverage"]["new_evidence"] == 1
    assert recovered["evidence"][0]["start_line"] == 41
    assert "PodLevelResourcesFixDefaulting" in recovered["data"]["text"]
