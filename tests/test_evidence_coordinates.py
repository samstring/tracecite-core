from __future__ import annotations

import importlib.util
from pathlib import Path

from tracecite.runtime import attach_source_line_coordinates
from tracecite.runtime.repeated_evidence import attach_matched_existing_evidence


ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "benchmarks" / "agent-investigation" / "pi_tracecite_bridge.py"
EXTENSION_IMPL = ROOT / "benchmarks" / "agent-investigation" / "pi_tracecite_extension_impl.ts"


def _load_bridge_module():
    spec = importlib.util.spec_from_file_location("pi_tracecite_bridge_coordinates_test", BRIDGE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_source_line_coordinates_report_geometry_without_relation_claims(tmp_path: Path) -> None:
    source = tmp_path / "evidence.log"
    source.write_text("x\n", encoding="utf-8")
    other = tmp_path / "other.log"
    other.write_text("y\n", encoding="utf-8")

    rows = attach_source_line_coordinates(
        [
            {"uri": "e:a", "source_path": str(source), "start_line": 10, "end_line": 20},
            {"uri": "e:b", "source_path": str(source), "start_line": 24, "end_line": 30},
            {"uri": "e:c", "source_path": str(source), "start_line": 18, "end_line": 25},
            {"uri": "e:d", "source_path": str(other), "start_line": 21, "end_line": 21},
        ]
    )

    position = rows[0]["position"]
    assert position["coordinate_space"] == "source_line"
    assert position["span_lines"] == 11
    assert position["peer_total"] == 2
    peers = position["peer_distances"]
    assert peers[0] == {
        "start_line": 18,
        "end_line": 25,
        "line_gap": 0,
        "direction": "overlap",
        "overlaps": True,
        "uri": "e:c",
    }
    assert peers[1]["start_line"] == 24
    assert peers[1]["line_gap"] == 3
    assert peers[1]["direction"] == "after"
    assert peers[1]["overlaps"] is False

    encoded = repr(rows).lower()
    for forbidden in ("related", "relevance", "causal", "association_score"):
        assert forbidden not in encoded


def test_matched_existing_projection_compares_new_and_repeated_rows(tmp_path: Path) -> None:
    source = tmp_path / "runtime.log"
    source.write_text("x\n", encoding="utf-8")

    new_row = {
        "uri": "e:new",
        "source_path": str(source),
        "start_line": 100,
        "end_line": 110,
        "label": "new",
    }
    old_row = {
        "uri": "e:old",
        "source_path": str(source),
        "start_line": 120,
        "end_line": 125,
        "label": "old body is not repeated",
    }

    class DummyResult:
        canonical_result = {"evidence": [new_row, old_row], "data": {}, "coverage": {}}
        new_evidence = (new_row,)

        @staticmethod
        def to_dict():
            return {"evidence": [dict(new_row)], "data": {}, "coverage": {}}

    payload = attach_matched_existing_evidence(DummyResult())  # type: ignore[arg-type]
    current = payload["evidence"][0]
    repeated = payload["data"]["matched_existing_evidence"][0]

    assert current["position"]["peer_distances"][0]["uri"] == "e:old"
    assert current["position"]["peer_distances"][0]["line_gap"] == 9
    assert repeated["position"]["peer_distances"][0]["uri"] == "e:new"
    assert "label" not in repeated


def test_pi_navigation_projection_preserves_core_position_facts(tmp_path: Path) -> None:
    source = tmp_path / "runtime.log"
    source.write_text("x\n", encoding="utf-8")
    position = {
        "coordinate_space": "source_line",
        "source_path": str(source.resolve()),
        "start_line": 41,
        "end_line": 47,
        "span_lines": 7,
        "peer_total": 1,
        "peer_distances": [
            {
                "start_line": 70,
                "end_line": 75,
                "line_gap": 22,
                "direction": "after",
                "overlaps": False,
            }
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
