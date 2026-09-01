from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "benchmarks" / "agent-investigation" / "pi_tracecite_bridge.py"


def test_directory_source_target_exposes_identity_without_content(tmp_path: Path) -> None:
    source = tmp_path / "containerd-goroutines.txt"
    body = "goroutine 1 [semacquire]:\nexample stack frame\n"
    source.write_text(body, encoding="utf-8")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()

    session = tmp_path / "retrieval-session.json"
    completed = subprocess.run(
        [sys.executable, str(BRIDGE), "--session", str(session), "retrieve", "."],
        cwd=tmp_path,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert completed.returncode == 0, completed.stderr

    payload = json.loads(completed.stdout)
    rows = payload.get("evidence") or []
    row = next(
        item
        for item in rows
        if "containerd-goroutines.txt" in str(item.get("label") or "")
    )

    assert row["metadata_only"] is True
    assert row["source_path"].endswith("containerd-goroutines.txt")
    assert row["sha256"] == digest
    assert row["uri"] == f"tracecite-source://sha256/{digest}"
    assert f"bytes={source.stat().st_size}" in row["label"]
    assert f"sha256={digest}" in row["label"]
    assert body not in json.dumps(row)
