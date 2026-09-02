from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "benchmarks" / "agent-investigation" / "pi_tracecite_bridge.py"


def _run_bridge(tmp_path: Path, *args: str) -> dict:
    session = tmp_path / "retrieval-session.json"
    completed = subprocess.run(
        [sys.executable, str(BRIDGE), "--session", str(session), *args],
        cwd=tmp_path,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_directory_source_target_exposes_identity_without_content(tmp_path: Path) -> None:
    source = tmp_path / "containerd-goroutines.txt"
    body = "goroutine 1 [semacquire]:\nexample stack frame\n"
    source.write_text(body, encoding="utf-8")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()

    # Compatibility tracecite_search always supplies a query. A directory is
    # still a source-discovery target rather than a text QueryTarget.
    payload = _run_bridge(tmp_path, "retrieve", ".", "--query", ".")
    rows = payload.get("evidence") or []
    row = next(
        item
        for item in rows
        if "containerd-goroutines.txt" in str(item.get("label") or "")
    )

    assert row["metadata_only"] is True
    assert row["source_path"] == str(source.resolve())
    assert row["sha256"] == digest
    assert row["uri"] == f"tracecite-source://sha256/{digest}"
    assert f"access_file={source.resolve()}" in row["label"]
    assert f"bytes={source.stat().st_size}" in row["label"]
    assert f"sha256={digest}" in row["label"]
    assert body not in json.dumps(row)


def test_query_result_preserves_original_file_for_follow_up_calls(tmp_path: Path) -> None:
    source = tmp_path / "containerd-goroutines.txt"
    body = "goroutine 1 [semacquire]:\nexample stack frame\n"
    source.write_text(body, encoding="utf-8")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()

    payload = _run_bridge(
        tmp_path,
        "retrieve",
        str(source),
        "--query",
        "goroutine",
        "--max-evidence",
        "3",
    )
    rows = payload.get("evidence") or []
    row = next(
        item
        for item in rows
        if str(item.get("uri") or "").startswith("tracecite-access://")
    )

    assert row["metadata_only"] is True
    assert row["source_path"] == str(source.resolve())
    assert row["sha256"] == digest
    assert row["uri"] == f"tracecite-access://sha256/{digest}"
    assert f"follow_up_file={source.resolve()}" in row["label"]
    assert "snapshot refs are citations, not file paths" in row["label"]
    assert body not in json.dumps(row)
