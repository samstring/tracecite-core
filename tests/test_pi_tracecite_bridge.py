from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "benchmarks" / "agent-investigation" / "pi_tracecite_bridge.py"


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


def test_pi_bridge_uses_independent_retrieval_session_and_persists_novelty(tmp_path: Path) -> None:
    source = tmp_path / "runtime.log"
    source.write_text("before\nERROR timeout request=7\nafter\n", encoding="utf-8")
    session = tmp_path / "pi-session.json"

    first = _run_bridge(
        "--session",
        str(session),
        "search",
        str(source),
        "timeout",
        "--max-evidence",
        "5",
        cwd=tmp_path,
    )
    assert first["status"] == "ok"
    assert first["outcome"] == "not_assessed"
    assert first["evidence"]
    assert first["coverage"]["new_evidence"] == 1
    assert "progress" in first["data"]
    assert not session.exists()
    assert (tmp_path / "_retrieval_sessions" / "pi-session.json").is_file()

    repeated = _run_bridge(
        "--session",
        str(session),
        "search",
        str(source),
        "timeout",
        "--max-evidence",
        "5",
        cwd=tmp_path,
    )
    assert repeated["status"] == "no_new_evidence"
    assert repeated["outcome"] == "not_assessed"
    assert repeated["evidence"] == []
    assert repeated["coverage"]["repeated_evidence"] >= 1
    assert repeated["data"]["matched_existing_evidence"]
    assert repeated["data"]["matched_existing_evidence"][0]["start_line"] == 2
    assert "label" not in repeated["data"]["matched_existing_evidence"][0]
    assert repeated["data"]["stop_reason"]["kind"] == "no_new_evidence"


def test_new_query_can_point_to_old_evidence_without_resending_its_body(tmp_path: Path) -> None:
    source = tmp_path / "runtime.log"
    source.write_text(
        "before\nERROR timeout request=7 shared-marker\nafter\n",
        encoding="utf-8",
    )
    session = tmp_path / "pi-session.json"

    first = _run_bridge(
        "--session",
        str(session),
        "search",
        str(source),
        "timeout",
        "--max-evidence",
        "5",
        cwd=tmp_path,
    )
    second = _run_bridge(
        "--session",
        str(session),
        "search",
        str(source),
        "shared-marker",
        "--max-evidence",
        "5",
        cwd=tmp_path,
    )

    assert first["coverage"]["new_evidence"] == 1
    assert second["status"] == "no_new_evidence"
    assert second["coverage"]["new_evidence"] == 0
    assert second["coverage"]["repeated_evidence"] == 1
    assert second["evidence"] == []
    matched = second["data"]["matched_existing_evidence"]
    assert len(matched) == 1
    assert matched[0]["uri"] == first["evidence"][0]["uri"]
    assert matched[0]["start_line"] == 2
    assert matched[0]["end_line"] == 2
    assert matched[0]["source_path"]
    assert "label" not in matched[0]


def test_pi_bridge_expand_tracks_immutable_range_without_investigation(tmp_path: Path) -> None:
    source = tmp_path / "runtime.log"
    source.write_text("one\ntwo\nthree\n", encoding="utf-8")
    session = tmp_path / "pi-session.json"
    digest = hashlib.sha256(source.read_bytes()).hexdigest()

    expanded = _run_bridge(
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
    assert expanded["status"] == "ok"
    assert expanded["outcome"] == "not_assessed"
    assert "1: one" in expanded["data"]["text"]
    assert "2: two" in expanded["data"]["text"]
    assert "3: three" in expanded["data"]["text"]

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
    assert repeated["status"] == "no_new_evidence"
    assert repeated["evidence"] == []
    assert repeated["data"]["stop_reason"]["kind"] == "no_new_evidence"
    assert not session.exists()
