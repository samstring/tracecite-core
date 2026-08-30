from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from tracecite.runtime import EvidenceRequest, QueryTarget, RangeTarget
from tracecite.runtime.retrieval_session import RetrievalSessionStore
from tracecite.runtime.session_retrieval import retrieve_with_session


ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "benchmarks" / "agent-investigation" / "pi_tracecite_bridge.py"


def _store(tmp_path: Path, name: str = "session") -> RetrievalSessionStore:
    return RetrievalSessionStore(
        tmp_path,
        name,
        namespace="_retrieval_sessions",
        legacy_evidence_context=False,
    )


def _run_bridge(*args: str, cwd: Path) -> dict:
    env = os.environ.copy()
    paths = [str(ROOT / "src")]
    if env.get("PYTHONPATH"):
        paths.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(paths)
    completed = subprocess.run(
        [sys.executable, str(BRIDGE), *args],
        cwd=cwd,
        env=env,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    return json.loads(completed.stdout)


def test_truncated_search_does_not_resend_visible_repeated_rows(tmp_path: Path) -> None:
    source = tmp_path / "runtime.log"
    source.write_text(
        "\n".join(f"ERROR timeout request={index}" for index in range(20)) + "\n",
        encoding="utf-8",
    )
    store = _store(tmp_path)
    request = EvidenceRequest(QueryTarget(source, "timeout", max_evidence=3))

    first = retrieve_with_session(request, store).to_dict()
    repeated = retrieve_with_session(request, store).to_dict()

    assert first["coverage"]["evidence_truncated"] is True
    assert len(first["evidence"]) == 3
    assert repeated["coverage"]["evidence_truncated"] is True
    assert repeated["coverage"]["new_evidence"] == 0
    assert repeated["coverage"]["repeated_evidence"] == 3
    assert repeated["evidence"] == []
    refs = repeated["data"]["matched_existing_evidence"]
    assert len(refs) == 3
    assert all(item.get("uri") for item in refs)
    assert all("label" not in item for item in refs)


def test_new_query_keeps_identity_of_old_evidence_match_without_resending_body(tmp_path: Path) -> None:
    source = tmp_path / "runtime.log"
    source.write_text(
        "alpha beta same-line\nunrelated\n",
        encoding="utf-8",
    )
    store = _store(tmp_path)

    first = retrieve_with_session(
        EvidenceRequest(QueryTarget(source, "alpha", max_evidence=3)),
        store,
    ).to_dict()
    second = retrieve_with_session(
        EvidenceRequest(QueryTarget(source, "beta", max_evidence=3)),
        store,
    ).to_dict()

    assert len(first["evidence"]) == 1
    assert second["coverage"]["new_evidence"] == 0
    assert second["coverage"]["repeated_evidence"] == 1
    assert second["evidence"] == []
    refs = second["data"]["matched_existing_evidence"]
    assert len(refs) == 1
    assert refs[0]["start_line"] == 1
    assert refs[0]["end_line"] == 1
    assert refs[0]["uri"] == first["evidence"][0]["uri"]
    assert "label" not in refs[0]


def test_overlapping_expand_projects_only_lines_not_already_exposed(tmp_path: Path) -> None:
    source = tmp_path / "runtime.log"
    source.write_text(
        "".join(f"line-{index}\n" for index in range(1, 31)),
        encoding="utf-8",
    )
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    store = _store(tmp_path)

    first = retrieve_with_session(
        EvidenceRequest(RangeTarget(source, 10, before=3, after=3, expected_sha256=digest)),
        store,
    ).to_dict()
    second = retrieve_with_session(
        EvidenceRequest(RangeTarget(source, 12, before=3, after=3, expected_sha256=digest)),
        store,
    ).to_dict()

    assert "7: line-7" in first["data"]["new_text"]
    assert "13: line-13" in first["data"]["new_text"]
    assert second["data"]["unseen_ranges"] == [[14, 15]]
    assert "14: line-14" in second["data"]["new_text"]
    assert "15: line-15" in second["data"]["new_text"]
    assert "13: line-13" not in second["data"]["new_text"]
    assert second["data"]["repeated_text_suppressed"] is False


def test_append_only_growth_keeps_generation_and_only_projects_new_overlap(tmp_path: Path) -> None:
    source = tmp_path / "live.log"
    source.write_text(
        "".join(f"line-{index}\n" for index in range(1, 21)),
        encoding="utf-8",
    )
    store = _store(tmp_path)

    first = retrieve_with_session(
        EvidenceRequest(RangeTarget(source, 18, before=2, after=2)),
        store,
    ).to_dict()
    first_version = first["data"]["source_version"]
    assert "16: line-16" in first["data"]["new_text"]
    assert "20: line-20" in first["data"]["new_text"]

    with source.open("a", encoding="utf-8") as handle:
        handle.write("line-21\nline-22\nline-23\n")

    second = retrieve_with_session(
        EvidenceRequest(RangeTarget(source, 20, before=2, after=3)),
        store,
    ).to_dict()

    assert second["data"]["source_version"] == first_version
    assert second["data"]["unseen_ranges"] == [[21, 23]]
    assert "21: line-21" in second["data"]["new_text"]
    assert "23: line-23" in second["data"]["new_text"]
    assert "20: line-20" not in second["data"]["new_text"]


def test_truncate_or_recreate_rolls_generation_and_does_not_hide_new_content(tmp_path: Path) -> None:
    source = tmp_path / "live.log"
    source.write_text(
        "".join(f"old-{index}\n" for index in range(1, 21)),
        encoding="utf-8",
    )
    store = _store(tmp_path)

    first = retrieve_with_session(
        EvidenceRequest(RangeTarget(source, 3, before=2, after=2)),
        store,
    ).to_dict()
    old_version = first["data"]["source_version"]
    assert "3: old-3" in first["data"]["new_text"]

    source.write_text(
        "".join(f"new-{index}\n" for index in range(1, 6)),
        encoding="utf-8",
    )

    second = retrieve_with_session(
        EvidenceRequest(RangeTarget(source, 3, before=2, after=2)),
        store,
    ).to_dict()

    assert second["data"]["source_version"] != old_version
    assert "3: new-3" in second["data"]["new_text"]
    assert second["status"] != "no_new_evidence"


def test_session_operation_history_is_atomic_and_has_no_sidecar(tmp_path: Path) -> None:
    source = tmp_path / "runtime.log"
    source.write_text("alpha beta same-line\nunrelated\n", encoding="utf-8")
    store = _store(tmp_path)

    retrieve_with_session(EvidenceRequest(QueryTarget(source, "alpha", max_evidence=3)), store)
    repeated = retrieve_with_session(
        EvidenceRequest(QueryTarget(source, "beta", max_evidence=3)), store
    ).to_dict()
    retrieve_with_session(EvidenceRequest(QueryTarget(source, "missing", max_evidence=3)), store)
    duplicate = retrieve_with_session(
        EvidenceRequest(QueryTarget(source, "missing", max_evidence=3)), store
    ).to_dict()

    state = store.load()
    assert state.revision == 4
    assert state.operation_counts == {"search": 4}
    assert state.exact_duplicate_requests == 1
    assert len(state.recent_operations) == 4
    assert state.recent_operations[1].status == "no_new_evidence"
    assert state.recent_operations[1].repeated_evidence == 1
    assert state.recent_operations[-1].status == "no_match"
    assert state.recent_operations[-1].exact_duplicate_request is True

    summary = state.retrieval_summary()
    assert summary["recent_window"] == 4
    assert summary["recent_with_new_evidence"] == 1
    assert summary["recent_repeated_only"] == 1
    assert summary["recent_no_match"] == 2
    assert repeated["data"]["session_progress"]["operation_counts"] == {"search": 2}
    assert duplicate["data"]["session_progress"]["exact_duplicate_requests"] == 1
    assert not list(tmp_path.rglob("*" + "." + "telemetry" + "." + "json"))


def test_parallel_retrievals_merge_session_state_without_lost_updates(tmp_path: Path) -> None:
    source = tmp_path / "runtime.log"
    count = 24
    source.write_text(
        "".join(f"marker-{index}\n" for index in range(count)),
        encoding="utf-8",
    )
    store = _store(tmp_path)

    def search(index: int) -> None:
        result = retrieve_with_session(
            EvidenceRequest(QueryTarget(source, f"marker-{index}", max_evidence=1)),
            store,
        )
        assert result.new_evidence

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(search, range(count)))

    state = store.load()
    assert len(state.seen_evidence) == count
    assert state.revision == count


def test_pi_bridge_can_replay_old_evidence_without_counting_it_as_new(tmp_path: Path) -> None:
    source = tmp_path / "runtime.log"
    source.write_text("one\ntwo\nthree\nfour\n", encoding="utf-8")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    session = tmp_path / "pi-session.json"

    first = _run_bridge(
        "--session",
        str(session),
        "expand",
        str(source),
        "2",
        "--radius",
        "1",
        "--sha256",
        digest,
        cwd=tmp_path,
    )
    repeated = _run_bridge(
        "--session",
        str(session),
        "expand",
        str(source),
        "2",
        "--radius",
        "1",
        "--sha256",
        digest,
        cwd=tmp_path,
    )
    replayed = _run_bridge(
        "--session",
        str(session),
        "expand",
        str(source),
        "2",
        "--radius",
        "1",
        "--sha256",
        digest,
        "--replay",
        cwd=tmp_path,
    )

    assert "1: one" in first["data"]["new_text"]
    assert repeated["status"] == "no_new_evidence"
    assert repeated["data"]["new_text"] == ""
    assert replayed["data"]["replayed"] is True
    assert replayed["coverage"]["new_evidence"] == 0
    assert replayed["coverage"]["replayed_evidence"] == 1
    assert "1: one" in replayed["data"]["new_text"]
    assert "3: three" in replayed["data"]["new_text"]


def test_pi_extension_treats_stop_as_agent_owned_and_exposes_replay() -> None:
    extension = (
        ROOT / "benchmarks" / "agent-investigation" / "pi_tracecite_extension.ts"
    ).read_text(encoding="utf-8")

    assert "STOP TraceCite retrieval" not in extension
    assert "decide when the Agent should stop" in extension
    assert "data.new_text" in extension
    assert "source_sha256" in extension
    assert "matched_existing_evidence" in extension
    assert "does not mean that evidence is understood, important, causal, or sufficient" in extension
    assert "replay=true" in extension
    assert 'args.push("--replay")' in extension
