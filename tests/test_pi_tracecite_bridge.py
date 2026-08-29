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


def test_pi_bridge_uses_canonical_retrieve_and_persists_novelty(tmp_path: Path) -> None:
    source = tmp_path / "runtime.log"
    source.write_text("before\nERROR timeout request=7\nafter\n", encoding="utf-8")
    state = tmp_path / "pi-investigation.json"

    first = _run_bridge(
        "--state",
        str(state),
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

    repeated = _run_bridge(
        "--state",
        str(state),
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
    assert repeated["data"]["stop_reason"]["kind"] == "no_new_evidence"


def test_pi_bridge_expand_is_observation_not_semantic_support(tmp_path: Path) -> None:
    source = tmp_path / "runtime.log"
    source.write_text("one\ntwo\nthree\n", encoding="utf-8")
    state = tmp_path / "pi-investigation.json"
    digest = hashlib.sha256(source.read_bytes()).hexdigest()

    expanded = _run_bridge(
        "--state",
        str(state),
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
