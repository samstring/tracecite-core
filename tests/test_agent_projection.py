from __future__ import annotations

from tracecite.integrations.agent_projection import (
    apply_survey_brief,
    compact_filter_payload,
    dedupe_evidence_labels,
    dedupe_survey_coverage,
    lightweight_result,
    project,
)


def test_dedupe_survey_coverage_collapses_aliases() -> None:
    coverage = dedupe_survey_coverage(
        {
            "scanned_lines": 10,
            "lines_scanned": 10,
            "records_scanned": 4,
            "scoped_records": 4,
        }
    )

    assert coverage["lines_scanned"] == 10
    assert coverage["records_scanned"] == 4
    assert "scanned_lines" not in coverage


def test_dedupe_evidence_labels_hoists_shared_label() -> None:
    rows = [["#L1", 1, 1, "same"], ["#L2", 2, 2, "same"]]
    coverage: dict[str, object] = {}

    dedupe_evidence_labels(rows, label_index=3, coverage=coverage)

    assert coverage["shared_label"] == "same"
    assert rows[0][3] == ""
    assert rows[1][3] == ""


def test_compact_filter_payload_points_to_records_path() -> None:
    view = compact_filter_payload(
        {
            "match_records": 3,
            "output_path": "/tmp/filtered.log",
            "records_path": "/tmp/filtered.log.records.jsonl",
        }
    )

    assert view["view"] == "agent"
    assert view["records_path"].endswith(".records.jsonl")
    assert "Do not Read output_path" in view["recovery"]


def test_lightweight_keeps_warnings_and_missing_evidence() -> None:
    payload = {
        "operation": "search",
        "status": "no_match",
        "warnings": ["零命中只表示证据不足"],
        "missing_evidence": [{"kind": "query_coverage", "detail": "none"}],
        "hypotheses": [],
        "verification": {},
        "next_queries": [],
        "artifacts": [],
        "data": {"query": "x"},
    }
    slim = lightweight_result(payload)
    assert slim["warnings"] == payload["warnings"]
    assert slim["missing_evidence"] == payload["missing_evidence"]
    assert "hypotheses" not in slim
    assert "verification" not in slim


def test_lightweight_drops_runtime_bookkeeping_but_keeps_actionable_progress() -> None:
    payload = {
        "operation": "expand",
        "status": "ok",
        "investigation": {"id": "inv-1", "revision": 9, "path": "/tmp/state.json"},
        "data": {
            "budget": {"usage": {"executions": 9}, "remaining": {"executions": None}},
            "cache": {"status": "bypass"},
            "progress": {
                "coverage_status": "partial",
                "readiness": "unknown",
                "seen_evidence": 100,
                "seen_lines": 80,
                "frontier_exhausted": False,
                "delta": {"grew": True, "new_evidence": 1, "new_lines": 7, "new_entities": 0},
                "stop": {"recommended": False, "reason": "evidence_grew"},
            },
            "routing": {
                "mode": "investigate",
                "reasons": ["exploration_depth"],
                "previous_executions": 8,
                "source_count": 1,
                "max_match_records": 345,
            },
            "text": "7: failure\n",
        },
        "evidence": [
            {
                "source_path": "/tmp/runtime.log",
                "start_line": 7,
                "end_line": 7,
                "uri": "evidence://sha256/abc#L7",
            }
        ],
    }

    slim = lightweight_result(payload)

    assert "investigation" not in slim
    assert "budget" not in slim["data"]
    assert "cache" not in slim["data"]
    assert slim["data"]["progress"] == {
        "coverage_status": "partial",
        "delta": {"grew": True, "new_evidence": 1, "new_lines": 7},
    }
    assert slim["data"]["routing"] == {
        "mode": "investigate",
        "reasons": ["exploration_depth"],
    }
    assert slim["data"]["text"] == "runtime.log:7 failure\n"


def test_apply_survey_brief_strips_template_text() -> None:
    payload = {
        "operation": "survey",
        "data": {
            "top_templates": [
                {
                    "template": "INFO worker",
                    "samples": [{"start_line": 1, "end_line": 1, "text": "full line"}],
                }
            ]
        },
        "coverage": {"scanned_lines": 4, "lines_scanned": 4},
        "evidence": [{"label": "x" * 120, "metadata": {"text": "full"}}],
    }

    brief = apply_survey_brief(payload)

    assert brief["data"]["brief"] is True
    assert "text" not in brief["data"]["top_templates"][0]["samples"][0]
    assert len(brief["evidence"][0]["label"]) <= 80


def test_project_full_returns_detached_canonical_view() -> None:
    payload = {"operation": "search", "data": {"query": "timeout"}, "evidence": []}

    full = project(payload, profile="full")
    full["data"]["query"] = "changed"

    assert payload["data"]["query"] == "timeout"


def test_project_accepts_custom_upper_layer_projection() -> None:
    payload = {"operation": "search", "status": "ok", "evidence": [{"uri": "E1"}]}

    view = project(
        payload,
        profile=lambda result: {
            "status": result["status"],
            "evidence_count": len(result.get("evidence") or []),
        },
    )

    assert view == {"status": "ok", "evidence_count": 1}
