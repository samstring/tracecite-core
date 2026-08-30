from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from tracecite.runtime import EvidenceRequest, QueryTarget, RangeTarget
from tracecite.runtime.retrieval_session import RetrievalSessionStore
from tracecite.runtime.session_retrieval import retrieve_with_session


def _store(tmp_path: Path) -> RetrievalSessionStore:
    return RetrievalSessionStore(
        tmp_path,
        "standalone",
        namespace="_retrieval_sessions",
        legacy_evidence_context=False,
    )


def test_standalone_session_suppresses_repeated_search_without_investigation(tmp_path: Path) -> None:
    source = tmp_path / "runtime.log"
    source.write_text("INFO boot\nERROR timeout request=7\nINFO done\n", encoding="utf-8")
    store = _store(tmp_path)

    first = retrieve_with_session(EvidenceRequest(QueryTarget(source, "timeout")), store)
    second = retrieve_with_session(EvidenceRequest(QueryTarget(source, "timeout")), store)
    second_payload = second.to_dict()

    assert first.status == "ok"
    assert first.new_evidence
    assert second.status == "no_new_evidence"
    assert second.new_evidence == ()
    assert second_payload["data"]["novelty"]["state"] == "no_new_evidence"
    assert "all_returned_evidence_already_seen" in second_payload["data"]["novelty"]["basis"]
    assert store.path.is_file()
    assert not (tmp_path / "investigation.json").exists()


def test_standalone_session_suppresses_repeated_immutable_range_as_novelty_fact(tmp_path: Path) -> None:
    source = tmp_path / "runtime.log"
    source.write_text("one\ntwo\nthree\nfour\n", encoding="utf-8")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    store = _store(tmp_path)
    request = EvidenceRequest(
        RangeTarget(source, 2, before=1, after=1, expected_sha256=digest)
    )

    first = retrieve_with_session(request, store)
    second = retrieve_with_session(request, store)
    second_payload = second.to_dict()

    assert first.status == "ok"
    assert second.status == "no_new_evidence"
    assert second_payload["data"]["novelty"]["state"] == "no_new_evidence"
    assert "requested_context_already_covered" in second_payload["data"]["novelty"]["basis"]


def test_standalone_session_persists_structural_relation_novelty(tmp_path: Path) -> None:
    source = tmp_path / "runtime.log"
    source.write_text(
        "- name: resource-a\n"
        "resources:\n"
        "resourceID: device-a\n"
        "done\n",
        encoding="utf-8",
    )
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    store = _store(tmp_path)

    result = retrieve_with_session(
        EvidenceRequest(RangeTarget(source, 2, before=1, after=1, expected_sha256=digest)),
        store,
    )

    assert result.status == "ok"
    assert result.progress is not None
    assert result.progress.delta.new_relations >= 1
    assert store.load().seen_relations
    data = result.canonical_result["data"]
    assert data["observed_relations"][0]["relation_id"].startswith("rel:")


def test_standalone_session_rejects_investigation_owned_request(tmp_path: Path) -> None:
    source = tmp_path / "runtime.log"
    source.write_text("ERROR timeout\n", encoding="utf-8")
    store = _store(tmp_path)

    with pytest.raises(ValueError, match="cannot also use investigation_path"):
        retrieve_with_session(
            EvidenceRequest(QueryTarget(source, "timeout"), investigation_path=tmp_path / "investigation.json"),
            store,
        )
