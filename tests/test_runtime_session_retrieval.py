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

    assert first.status == "ok"
    assert first.new_evidence
    assert second.status == "no_new_evidence"
    assert second.new_evidence == ()
    assert second.stop_reason is not None
    assert second.stop_reason.kind == "no_new_evidence"
    assert store.path.is_file()
    assert not (tmp_path / "investigation.json").exists()


def test_standalone_session_hard_stops_repeated_immutable_range(tmp_path: Path) -> None:
    source = tmp_path / "runtime.log"
    source.write_text("one\ntwo\nthree\nfour\n", encoding="utf-8")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    store = _store(tmp_path)
    request = EvidenceRequest(
        RangeTarget(source, 2, before=1, after=1, expected_sha256=digest)
    )

    first = retrieve_with_session(request, store)
    second = retrieve_with_session(request, store)

    assert first.status == "ok"
    assert second.status == "no_new_evidence"
    assert second.stop_reason is not None
    assert "requested_context_already_covered" in second.stop_reason.basis


def test_standalone_session_rejects_investigation_owned_request(tmp_path: Path) -> None:
    source = tmp_path / "runtime.log"
    source.write_text("ERROR timeout\n", encoding="utf-8")
    store = _store(tmp_path)

    with pytest.raises(ValueError, match="cannot also use investigation_path"):
        retrieve_with_session(
            EvidenceRequest(QueryTarget(source, "timeout"), investigation_path=tmp_path / "investigation.json"),
            store,
        )
