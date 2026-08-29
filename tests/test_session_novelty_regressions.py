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
    assert "replay=true" in extension
    assert 'args.push("--replay")' in extension
