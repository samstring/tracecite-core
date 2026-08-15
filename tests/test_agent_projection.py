from __future__ import annotations

from tracecite.integrations.agent_projection import (
    apply_survey_brief,
    compact_filter_payload,
    dedupe_evidence_labels,
    dedupe_survey_coverage,
    lightweight_result,
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
