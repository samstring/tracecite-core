from __future__ import annotations

from pathlib import Path

from tracecite.runtime import EvidenceRequest, QueryTarget
from tracecite.runtime.retrieval_session import RetrievalSessionStore
from tracecite.runtime.retrieval_telemetry import RetrievalSessionTelemetry
from tracecite.runtime.session_retrieval import retrieve_with_session


ROOT = Path(__file__).resolve().parents[1]


def _store(tmp_path: Path) -> RetrievalSessionStore:
    return RetrievalSessionStore(
        tmp_path,
        "telemetry",
        namespace="_retrieval_sessions",
        legacy_evidence_context=False,
    )


def _search(
    store: RetrievalSessionStore,
    source: Path,
    query: str,
    *,
    regex: bool = False,
) -> dict:
    payload = retrieve_with_session(
        EvidenceRequest(QueryTarget(source, query, regex=regex, max_evidence=10)),
        store,
    ).to_dict()
    progress = RetrievalSessionTelemetry(store).record_search(
        source=str(source.resolve()),
        query=query,
        regex=regex,
        result=payload,
    )
    data = dict(payload.get("data") or {})
    data["session_progress"] = progress
    payload["data"] = data
    return payload


def test_session_progress_tracks_new_repeated_no_match_and_duplicates(tmp_path: Path) -> None:
    source = tmp_path / "runtime.log"
    source.write_text("alpha beta\ngamma\n", encoding="utf-8")
    store = _store(tmp_path)

    first = _search(store, source, "alpha")
    repeated = _search(store, source, "beta")
    missing = _search(store, source, "delta")
    duplicate = _search(store, source, "delta")

    progress = duplicate["data"]["session_progress"]
    assert first["coverage"]["new_evidence"] == 1
    assert repeated["coverage"]["new_evidence"] == 0
    assert repeated["coverage"]["repeated_evidence"] == 1
    assert missing["status"] == "no_match"
    assert progress == {
        "search_calls": 4,
        "expand_calls": 0,
        "unique_evidence_seen": 1,
        "exact_duplicate_queries": 1,
        "recent_window": 4,
        "recent_searches_with_new_evidence": 1,
        "recent_repeated_only_searches": 1,
        "recent_no_match_searches": 2,
    }


def test_session_progress_window_is_bounded_to_last_ten_searches(tmp_path: Path) -> None:
    source = tmp_path / "runtime.log"
    source.write_text("seed\n", encoding="utf-8")
    store = _store(tmp_path)

    _search(store, source, "seed")
    for index in range(12):
        _search(store, source, f"missing-{index}")

    progress = RetrievalSessionTelemetry(store).summary()
    assert progress["search_calls"] == 13
    assert progress["recent_window"] == 10
    assert progress["recent_searches_with_new_evidence"] == 0
    assert progress["recent_repeated_only_searches"] == 0
    assert progress["recent_no_match_searches"] == 10


def test_session_progress_is_mechanical_not_a_stop_decision() -> None:
    extension = (
        ROOT / "benchmarks" / "agent-investigation" / "pi_tracecite_extension_progress.ts"
    ).read_text(encoding="utf-8")
    skill = (ROOT / ".pi" / "skills" / "tracecite" / "SKILL.md").read_text(encoding="utf-8")

    assert "session_progress" in extension
    assert "session_progress" in skill
    assert "never decides sufficiency, root cause, or stopping" in extension
    assert "does not mean" in skill
    assert "the investigation should stop" in skill
    assert "You own hypotheses, conclusions, and when to stop" in extension
