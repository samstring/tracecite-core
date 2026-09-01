from __future__ import annotations

import importlib.util
from pathlib import Path

from tracecite.runtime import EvidenceCoordinate, attach_seen_evidence_distances


ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "benchmarks" / "agent-investigation" / "pi_tracecite_bridge.py"
EXTENSION_IMPL = ROOT / "benchmarks" / "agent-investigation" / "pi_tracecite_extension_impl.ts"


def _load_bridge_module():
    spec = importlib.util.spec_from_file_location("pi_tracecite_bridge_coordinates_test", BRIDGE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_seen_evidence_distance_reports_geometry_without_relation_claims() -> None:
    digest = "a" * 64
    rows = attach_seen_evidence_distances(
        [{"uri": "current", "sha256": digest, "start_line": 24, "end_line": 30}],
        (
            EvidenceCoordinate("A", digest, 10, 20),
            EvidenceCoordinate("B", digest, 40, 45),
            EvidenceCoordinate("other", "b" * 64, 25, 25),
        ),
    )

    position = rows[0]["position"]
    assert position["coordinate_space"] == "source_line_sha256"
    assert position["nearest_seen"] == [
        {"ref": "A", "range": [10, 20], "line_gap": 3, "direction": "before"},
        {"ref": "B", "range": [40, 45], "line_gap": 9, "direction": "after"},
    ]

    encoded = repr(rows).lower()
    for forbidden in ("related", "relevance", "causal", "association_score"):
        assert forbidden not in encoded


def test_pi_navigation_projection_preserves_core_position_facts(tmp_path: Path) -> None:
    source = tmp_path / "runtime.log"
    source.write_text("x\n", encoding="utf-8")
    position = {
        "coordinate_space": "source_line_sha256",
        "nearest_seen": [
            {"ref": "runtime.log:L10-L20", "range": [10, 20], "line_gap": 20, "direction": "before"}
        ],
    }
    payload = {
        "evidence": [],
        "data": {
            "signal_hints": [
                {
                    "line": 41,
                    "end_line": 47,
                    "match_line": 44,
                    "match_end_line": 44,
                    "segment_kind": "stack_block",
                    "expand_line": 44,
                    "expand_radius": 3,
                    "severity": 0,
                    "count": 1,
                    "label": "stack navigation",
                    "position": position,
                }
            ]
        },
    }

    bridge = _load_bridge_module()
    rows = bridge._navigation_hint_evidence(source, payload)
    assert len(rows) == 1
    row = rows[0]
    assert row["position"] == position
    assert row["match_line"] == 44
    assert row["segment_kind"] == "stack_block"
    assert row["expand_line"] == 44
    assert row["expand_radius"] == 3

    extension_text = EXTENSION_IMPL.read_text(encoding="utf-8")
    assert "position: row?.position" in extension_text
    assert "match_line: row?.match_line" in extension_text
    assert "expand_line: row?.expand_line" in extension_text
