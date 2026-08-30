from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "benchmarks" / "agent-investigation" / "pi_tracecite_bridge.py"


def _run(tmp_path: Path, *args: str) -> dict:
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
    value = json.loads(completed.stdout)
    assert isinstance(value, dict)
    return value


def test_bridge_exposes_retrieve_materialize_replay_and_aggregate(tmp_path: Path) -> None:
    source = tmp_path / "app.log"
    source.write_text("INFO boot\nERROR timeout id=7\nINFO done\nERROR timeout id=8\n", encoding="utf-8")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()

    retrieved = _run(tmp_path, "retrieve", str(source), "--query", "timeout")
    assert retrieved["status"] == "ok"
    assert retrieved["evidence"]

    materialized = _run(
        tmp_path,
        "materialize",
        str(source),
        "2",
        "--radius",
        "1",
        "--sha256",
        digest,
    )
    assert "ERROR timeout" in (materialized.get("data") or {}).get("new_text", "")

    replayed = _run(
        tmp_path,
        "replay",
        str(source),
        "2",
        "--radius",
        "1",
        "--sha256",
        digest,
    )
    assert replayed["operation"] == "replay"
    assert replayed["coverage"]["new_evidence"] == 0
    assert replayed["data"]["replayed"] is True

    aggregated = _run(tmp_path, "aggregate", str(source), "ERROR", "--operation", "count")
    assert aggregated["operation"] == "aggregate"
    assert aggregated["data"]["count"] == 2
    assert aggregated["coverage"]["complete"] is True


def test_bridge_exposes_provider_traverse(tmp_path: Path) -> None:
    provider = tmp_path / "provider.json"
    provider.write_text(
        json.dumps(
            {
                "name": "fixture",
                "evidence": [
                    {
                        "id": "e1",
                        "kind": "log",
                        "source": "fixture",
                        "label": "first",
                        "entities": [{"kind": "request", "value": "r1"}],
                    },
                    {
                        "id": "e2",
                        "kind": "log",
                        "source": "fixture",
                        "label": "second",
                        "entities": [{"kind": "request", "value": "r1"}],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    traversed = _run(tmp_path, "traverse", str(provider), "--seed-evidence-id", "e1")
    assert traversed["operation"] == "traverse"
    assert traversed["status"] in {"ok", "partial", "empty"}
    assert traversed["graph"]["nodes"] >= 1


def test_bridge_exposes_verify_as_structured_operation(tmp_path: Path) -> None:
    missing = tmp_path / "missing-manifest.json"
    verified = _run(tmp_path, "verify", str(missing))
    assert verified["operation"] == "verify"
    assert verified["status"] == "error"
