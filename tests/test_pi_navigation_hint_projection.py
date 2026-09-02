from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "benchmarks" / "agent-investigation" / "pi_tracecite_bridge.py"


def _load_bridge_module():
    spec = importlib.util.spec_from_file_location("pi_tracecite_bridge_test", BRIDGE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_navigation_hint_is_metadata_only_and_materializable(tmp_path: Path) -> None:
    source = tmp_path / "runtime-evidence.txt"
    body = "first line\nsecond line\nthird line\n"
    source.write_text(body, encoding="utf-8")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()

    payload = {
        "evidence": [{"sha256": digest}],
        "data": {
            "signal_hints": [
                {
                    "line": 41,
                    "end_line": 47,
                    "severity": 0,
                    "count": 1,
                    "label": "goroutine <num> [sync.Mutex.Lock]",
                }
            ]
        },
    }

    bridge = _load_bridge_module()
    rows = bridge._navigation_hint_evidence(source, payload)

    assert len(rows) == 1
    row = rows[0]
    assert row["metadata_only"] is True
    assert row["source_path"] == str(source.resolve())
    assert row["sha256"] == digest
    assert row["start_line"] == 41
    assert row["end_line"] == 47
    assert row["uri"] == f"tracecite-navigation://sha256/{digest}/L41-L47"
    assert "navigation_hint=structural_diversity" in row["label"]
    assert "materialize this range with TraceCite before citing" in row["label"]
    assert body not in json.dumps(row)
