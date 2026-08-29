from __future__ import annotations

import json
from pathlib import Path

import pytest

from tracecite.runtime import InvestigationError, InvestigationState, InvestigationStore


def _store(tmp_path: Path) -> InvestigationStore:
    store = InvestigationStore(tmp_path / "investigation.json")
    store.create("why is the iOS page blank?", investigation_id="INV-1")
    return store


def test_old_v1_state_without_source_sessions_remains_readable(tmp_path: Path) -> None:
    store = _store(tmp_path)
    raw = json.loads(store.path.read_text(encoding="utf-8"))
    raw.pop("source_sessions", None)
    store.path.write_text(json.dumps(raw), encoding="utf-8")

    state = store.load()

    assert state.schema_version == 1
    assert getattr(state, "source_sessions") == []
    assert state.to_dict()["source_sessions"] == []


def test_live_source_recognition_is_reused_across_follow_up_turns(tmp_path: Path) -> None:
    store = _store(tmp_path)
    session = store.register_source_session(
        "ios-device-log",
        session_id="S1",
        identity={
            "device": "device-a",
            "bundle_id": "com.example.app",
            "launch_id": "launch-1",
            "stream": "console",
        },
        fingerprint="identity-v1",
        source_type="ios_device_log",
        format="ios_console",
        segmenter="mobile.ios.console",
        extension="mobile",
        confidence=0.97,
        coverage={"start": "10:00", "end": "10:05"},
    )

    first = store.inspect_source_session(
        session["id"],
        identity={
            "device": "device-a",
            "bundle_id": "com.example.app",
            "launch_id": "launch-1",
            "stream": "console",
        },
        fingerprint="identity-v1",
    )
    assert first["status"] == "known"
    assert first["source_changed"] is False
    assert first["reuse"] is True

    # A live log growing in time updates Coverage, not recognition identity.
    updated = store.update_source_session_coverage(
        "S1", {"start": "10:00", "end": "10:12"}
    )
    assert updated["recognition_status"] == "known"
    assert updated["coverage"] == {"start": "10:00", "end": "10:12"}

    follow_up = store.inspect_source_session("S1")
    assert follow_up["reuse"] is True
    assert follow_up["coverage"]["end"] == "10:12"
    assert len(store.list_source_sessions()) == 1


def test_identity_change_is_detected_without_forcing_an_agent_strategy(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.register_source_session(
        "ios-device-log",
        session_id="S1",
        identity={"device": "device-a", "launch_id": "launch-1"},
        format="ios_console",
        recognition_status="known",
    )

    result = store.inspect_source_session(
        "S1", identity={"device": "device-b", "launch_id": "launch-1"}
    )

    assert result["status"] == "changed"
    assert result["source_changed"] is True
    assert result["reuse"] is False
    assert result["reasons"] == ["identity_changed"]
    # Inspection is advisory/read-only. The Agent may decide whether to probe,
    # sample, create a new session, or explicitly invalidate this one.
    assert store.get_source_session("S1")["recognition_status"] == "known"


def test_invalidate_and_refresh_make_revalidation_explicit(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.register_source_session(
        "ios-device-log",
        session_id="S1",
        identity={"device": "device-a", "launch_id": "launch-1"},
        format="ios_console",
        segmenter="mobile.ios.console",
        extension="mobile",
        recognition_status="known",
    )

    invalidated = store.invalidate_source_session("S1", "format_drift")
    assert invalidated["recognition_status"] == "needs_revalidation"
    status = store.inspect_source_session("S1")
    assert status["reuse"] is False
    assert status["reasons"] == ["format_drift"]

    refreshed = store.refresh_source_session(
        "S1",
        format="ios_console_v2",
        segmenter="mobile.ios.console.v2",
        confidence=0.94,
        coverage={"start": "10:12", "end": "10:15"},
    )
    assert refreshed["recognition_status"] == "known"
    assert refreshed["invalidation_reason"] == ""
    assert store.inspect_source_session("S1")["reuse"] is True


def test_source_session_state_is_bounded_and_unique(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.register_source_session("source-a", session_id="S1")

    with pytest.raises(InvestigationError, match="source_id 已存在"):
        store.register_source_session("source-a", session_id="S2")
    with pytest.raises(InvestigationError, match="0 到 1"):
        store.register_source_session("source-b", session_id="S2", confidence=2.0)
    with pytest.raises(InvestigationError, match="changed / needs_revalidation"):
        store.invalidate_source_session("S1", "changed", status="known")


def test_source_session_contract_is_declared_not_import_time_monkey_patched() -> None:
    assert InvestigationState.to_dict.__module__ == "tracecite.runtime.investigation"
    assert InvestigationState.from_dict.__func__.__module__ == "tracecite.runtime.investigation"
    assert InvestigationStore.register_source_session.__module__ == "tracecite.runtime.investigation"
    assert InvestigationStore.inspect_source_session.__module__ == "tracecite.runtime.investigation"
