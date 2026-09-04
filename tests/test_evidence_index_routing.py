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


def test_five_matches_return_all_evidence_directly(tmp_path: Path) -> None:
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
    assert result["coverage"]["evidence_indexed"] is False
    assert len(result["evidence"]) == 5
    assert "evidence_index" not in result["data"]
    assert "signal_hints" not in result["data"]


def test_more_than_five_matches_return_complete_line_index_then_materialize(tmp_path: Path) -> None:
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
    policy = EvidenceRoutingPolicy(mode="bounded")

    searched = retrieve(
        EvidenceRequest(
            QueryTarget(source, r"ERROR|timeout|refused", regex=True, snapshot=True)
        ),
        session=store,
        routing_policy=policy,
    ).to_dict()

    assert searched["status"] == "ok"
    assert searched["coverage"]["match_records"] == 7
    assert searched["coverage"]["evidence_indexed"] is True
    assert searched["coverage"]["evidence_bodies_withheld"] == 7
    assert searched["evidence"] == []
    assert "signal_hints" not in searched["data"]
    assert "signal_hint_note" not in searched["data"]
    assert "evidence_index" not in searched["coverage"]

    index = searched["data"]["evidence_index"]
    assert index["complete"] is True
    assert index["navigation_only"] is True
    assert index["total_matches"] == 7
    entries = {item["rule"]: item for item in index["entries"]}
    assert entries["ERROR"] == {"rule": "ERROR", "count": 3, "lines": [1, 2, 3]}
    assert entries["timeout"] == {"rule": "timeout", "count": 2, "lines": [4, 5]}
    assert entries["refused"] == {"rule": "refused", "count": 2, "lines": [6, 7]}

    locator = entries["refused"]["lines"][0]
    recovered = materialize(
        RangeTarget(
            source,
            locator,
            before=0,
            after=0,
            expected_sha256=index["source_sha256"],
        ),
        session=store,
        routing_policy=policy,
    ).to_dict()

    assert recovered["status"] == "ok"
    assert "refused sixth" in recovered["data"]["new_text"]


def test_large_index_returns_every_matching_line_without_sampling(tmp_path: Path) -> None:
    source = tmp_path / "many.log"
    source.write_text("".join(f"ERROR item={index}\n" for index in range(1, 1001)), encoding="utf-8")
    store = _store(tmp_path)

    result = retrieve(
        EvidenceRequest(QueryTarget(source, "ERROR", snapshot=True)),
        session=store,
        routing_policy=EvidenceRoutingPolicy(mode="bounded"),
    ).to_dict()

    index = result["data"]["evidence_index"]
    entry = index["entries"][0]
    assert entry["count"] == 1000
    assert entry["lines"] == list(range(1, 1001))
    assert "sample_lines" not in entry
