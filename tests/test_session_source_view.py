from __future__ import annotations

from pathlib import Path

from tracecite.runtime import (
    RetrievalSessionStore,
    SessionSourceVersionStore,
    SessionSourceView,
)


def _session(root: Path, context_id: str) -> RetrievalSessionStore:
    return RetrievalSessionStore(
        root,
        context_id,
        namespace="_retrieval_sessions",
        legacy_evidence_context=False,
    )


def test_mutable_source_is_fixed_for_entire_retrieval_session(tmp_path: Path) -> None:
    source = tmp_path / "app.log"
    source.write_text("first\n", encoding="utf-8")
    state_root = tmp_path / "state"

    session_a = _session(state_root, "conversation-a")
    store_a = SessionSourceVersionStore.for_session(session_a)
    first = store_a.resolve(source, mode="mutable")
    assert isinstance(first, SessionSourceView)
    first_segment = Path(first.segments[0].path)
    assert first_segment.read_text(encoding="utf-8") == "first\n"

    # The original source changes while the same conversation/session is still
    # investigating. The session must keep the already frozen source version.
    source.write_text("second\n", encoding="utf-8")
    again = store_a.resolve(source, mode="mutable")
    assert again.version_id == first.version_id
    assert again.segments == first.segments
    assert Path(again.segments[0].path).read_text(encoding="utf-8") == "first\n"

    # A new RetrievalSession establishes a new view because the source changed.
    session_b = _session(state_root, "conversation-b")
    store_b = SessionSourceVersionStore.for_session(session_b)
    second = store_b.resolve(source, mode="mutable")
    assert second.version_id != first.version_id
    assert Path(second.segments[0].path).read_text(encoding="utf-8") == "second\n"

    # Another new session with an unchanged source reuses the verified snapshot
    # and SHA rather than snapshotting/hashing the same bytes again.
    session_c = _session(state_root, "conversation-c")
    third = SessionSourceVersionStore.for_session(session_c).resolve(source, mode="mutable")
    assert third.version_id == second.version_id
    assert third.segments == second.segments
    assert third.reused is True


def test_live_source_cuts_once_per_retrieval_session(tmp_path: Path) -> None:
    source = tmp_path / "live.log"
    source.write_text("A\n", encoding="utf-8")
    state_root = tmp_path / "state"

    session_a = _session(state_root, "conversation-live-a")
    store_a = SessionSourceVersionStore.for_session(session_a)
    first = store_a.resolve(source, mode="live", live_cut_timeout_seconds=0.05)
    first_version = first.version_id
    first_segments = first.segments

    # New live bytes must not silently enter the same conversation's evidence
    # world. Re-resolve returns the exact already-bound view without another cut.
    with source.open("a", encoding="utf-8") as handle:
        handle.write("B\n")
    again = store_a.resolve(source, mode="live", live_cut_timeout_seconds=0.05)
    assert again.version_id == first_version
    assert again.segments == first_segments

    # A new conversation/session may capture the newly appended bytes and bind
    # a newer immutable live view.
    session_b = _session(state_root, "conversation-live-b")
    second = SessionSourceVersionStore.for_session(session_b).resolve(
        source,
        mode="live",
        live_cut_timeout_seconds=0.05,
    )
    assert second.version_id != first_version
    assert second.total_bytes >= first.total_bytes
    assert second.total_lines >= first.total_lines
