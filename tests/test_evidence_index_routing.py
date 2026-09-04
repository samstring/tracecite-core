from __future__ import annotations

from pathlib import Path

from tracecite.runtime import (
    EvidenceRequest,
    EvidenceRoutingPolicy,
    QueryTarget,
    RangeTarget,
    RetrievalSessionStore,
    materialize,
    retrieve,
)


def _store(tmp_path: Path) -> RetrievalSessionStore:
    return RetrievalSessionStore(
        tmp_path,
        "evidence-index",
        namespace="_retrieval_sessions",
        legacy_evidence_context=False,
    )


def test_small_query_returns_complete_evidence_without_index(tmp_path: Path) -> None:
    source = tmp_path / "runtime.log"
    source.write_text("".join(f"ERROR item={index}\n" for index in range(1, 6)), encoding="utf-8")
    store = _store(tmp_path)

    result = retrieve(
        EvidenceRequest(QueryTarget(source, "ERROR", snapshot=True)),
        session=store,
        routing_policy=EvidenceRoutingPolicy(mode="bounded"),
    ).to_dict()

    assert result["status"] == "ok"
    assert result["coverage"]["match_records"] == 5
    assert result["coverage"]["complete"] is True
    assert len(result["evidence"]) == 5
    assert "evidence_index" not in result["data"]
    assert "evidence_indexed" not in result["coverage"]


def test_more_than_five_matches_still_return_complete_evidence_when_budget_fits(tmp_path: Path) -> None:
    source = tmp_path / "runtime.log"
    source.write_text(
        "ERROR first\n"
        "ERROR second\n"
        "ERROR third\n"
        "timeout fourth\n"
        "timeout fifth\n"
        "refused sixth\n"
        "refused seventh\n",
        encoding="utf-8",
    )
    store = _store(tmp_path)

    searched = retrieve(
        EvidenceRequest(
            QueryTarget(source, r"ERROR|timeout|refused", regex=True, snapshot=True)
        ),
        session=store,
        routing_policy=EvidenceRoutingPolicy(mode="bounded"),
    ).to_dict()

    assert searched["status"] == "ok"
    assert searched["coverage"]["match_records"] == 7
    assert searched["coverage"]["complete"] is True
    assert len(searched["evidence"]) == 7
    assert "evidence_index" not in searched["data"]

    pointer = next(item for item in searched["evidence"] if "refused sixth" in str(item.get("label")))
    recovered = materialize(
        RangeTarget(
            pointer["source_path"],
            pointer["start_line"],
            before=0,
            after=0,
            expected_sha256=pointer["sha256"],
        ),
        session=store,
    ).to_dict()

    assert recovered["status"] == "ok"
    assert "refused sixth" in recovered["data"]["text"]


def test_high_cardinality_pointer_projection_returns_too_broad_not_locator_dump(tmp_path: Path) -> None:
    source = tmp_path / "many.log"
    source.write_text("".join(f"ERROR item={index}\n" for index in range(1, 1001)), encoding="utf-8")
    store = _store(tmp_path)

    result = retrieve(
        EvidenceRequest(QueryTarget(source, "ERROR", snapshot=True)),
        session=store,
        routing_policy=EvidenceRoutingPolicy(mode="bounded"),
    ).to_dict()

    assert result["status"] == "too_broad"
    assert result["evidence"] == []
    assert result["coverage"]["too_broad"] is True
    assert result["coverage"]["evidence_returned"] == 0
    assert result["data"]["reason"] == "MATCHED_EVIDENCE_BUDGET_EXCEEDED"
    assert "evidence_index" not in result["data"]
    assert store.load().seen_evidence == ()
