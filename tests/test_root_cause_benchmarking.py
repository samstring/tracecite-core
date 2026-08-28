from __future__ import annotations

import json
from pathlib import Path

from tracecite.root_cause_benchmarking import score_transcript, validate_case


def _write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _case(tmp_path: Path) -> Path:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    _write_json(
        case_dir / "case.json",
        {
            "schema_version": 1,
            "id": "demo-root-cause",
            "source_issue": "https://github.com/example/project/issues/7",
            "fix_reference": "https://github.com/example/project/pull/8",
            "question_file": "question.md",
            "gold_file": "gold.json",
            "inputs": [
                {
                    "id": "runtime",
                    "url": "https://example.invalid/runtime.log",
                    "filename": "runtime.log",
                    "sha256": "a" * 64,
                }
            ],
            "provenance": {"project": "example/project"},
        },
    )
    (case_dir / "question.md").write_text("Why did the request fail?\n", encoding="utf-8")
    _write_json(
        case_dir / "gold.json",
        {
            "root_cause_schema_version": 1,
            "root_cause": {
                "failure_localization": {"patterns": ["worker queue"]},
                "immediate_failure_mechanism": {"patterns": ["checksum mismatch"]},
                "upstream_contributor": {"patterns": ["stale cache entry"]},
                "fix_alignment": {"patterns": ["invalidate.*cache"]},
            },
            "evidence_markers": ["ChecksumException"],
            "unsupported_claims": [{"id": "network", "patterns": ["network outage"]}],
            "contradictions": [{"id": "success", "patterns": ["request succeeded"]}],
            "root_cause_thresholds": {
                "dimension_recall": 1.0,
                "supported_dimension_recall": 1.0,
                "citation_accuracy": 1.0,
                "evidence_marker_recall": 1.0,
                "max_unsupported_claim_hits": 0,
                "max_contradiction_hits": 0,
            },
        },
    )
    return case_dir


def test_root_cause_score_uses_fixed_dimensions_citations_and_attempted_context(tmp_path: Path) -> None:
    case_dir = _case(tmp_path)
    transcript = tmp_path / "run.jsonl"
    events = [
        {"type": "session", "mode": "tracecite", "model": "demo"},
        {"type": "request_context", "serialized_chars": 400, "message_chars": 300, "tool_schema_chars": 100, "estimated_tokens_chars_div_4": 100},
        {"type": "model", "usage": {"input_tokens": 90, "output_tokens": 20}},
        {"type": "tool", "tool": "tracecite_search", "output": "runtime.log #L12 ChecksumException", "duration_ms": 4.5},
        {"type": "final", "answer": "The worker queue hit a checksum mismatch because a stale cache entry was reused. The fix should invalidate the cache before reuse. Evidence: L12.", "evidence": []},
    ]
    transcript.write_text("".join(json.dumps(item) + "\n" for item in events), encoding="utf-8")

    assert validate_case(case_dir)["status"] == "ok"
    score = score_transcript(case_dir, transcript)
    assert score["passed"] is True
    assert score["quality"]["dimension_recall"] == 1.0
    assert score["quality"]["supported_dimension_recall"] == 1.0
    assert all(item["supported"] for item in score["quality"]["dimension_evidence_support"])
    assert score["quality"]["citation"]["accuracy"] == 1.0
    assert score["quality"]["unsupported_claim_hits"] == 0
    assert score["context_cost"]["attempted_context_requests"] == 1
    assert score["context_cost"]["cumulative_attempted_context_chars"] == 400
    assert score["context_cost"]["reported_input_tokens"] == 90


def test_root_cause_score_accepts_cat_n_tool_line_as_visible_citation(tmp_path: Path) -> None:
    case_dir = _case(tmp_path)
    transcript = tmp_path / "cat-n.jsonl"
    events = [
        {"type": "session", "mode": "free_shell", "model": "demo"},
        {"type": "tool", "tool": "free_shell", "output": "    12\tChecksumException in worker queue from stale cache entry; invalidate cache", "duration_ms": 1},
        {"type": "final", "answer": "The worker queue hit a checksum mismatch because a stale cache entry was reused; invalidate the cache. Evidence: L12.", "evidence": []},
    ]
    transcript.write_text("".join(json.dumps(item) + "\n" for item in events), encoding="utf-8")

    score = score_transcript(case_dir, transcript)
    assert score["quality"]["citation"]["accuracy"] == 1.0
    assert score["quality"]["citation"]["cited_lines"] == [12]
    assert score["quality"]["citation"]["invalid_lines"] == []
    assert score["quality"]["supported_dimension_recall"] == 1.0


def test_numbered_final_answer_is_not_treated_as_shell_visible_citation(tmp_path: Path) -> None:
    case_dir = _case(tmp_path)
    transcript = tmp_path / "numbered-answer.jsonl"
    events = [
        {"type": "session", "mode": "free_shell", "model": "demo"},
        {"type": "tool", "tool": "free_shell", "output": "worker queue ChecksumException stale cache entry invalidate cache", "duration_ms": 1},
        {"type": "final", "answer": "12\tThe worker queue hit a checksum mismatch due to a stale cache entry; invalidate the cache.", "evidence": []},
    ]
    transcript.write_text("".join(json.dumps(item) + "\n" for item in events), encoding="utf-8")

    score = score_transcript(case_dir, transcript)
    assert score["quality"]["citation"]["citations"] == 0
    assert score["quality"]["citation"]["accuracy"] == 0.0
    assert score["quality"]["supported_dimension_recall"] == 0.0
    assert score["passed"] is False


def test_root_cause_score_rejects_unsupported_claim_and_invalid_citation(tmp_path: Path) -> None:
    case_dir = _case(tmp_path)
    transcript = tmp_path / "bad.jsonl"
    events = [
        {"type": "session", "mode": "tracecite", "model": "demo"},
        {"type": "tool", "tool": "tracecite_search", "output": "runtime.log #L12 ChecksumException", "duration_ms": 1},
        {"type": "final", "answer": "The worker queue hit a checksum mismatch due to a stale cache entry; invalidate the cache. There was also a network outage. Evidence: L99.", "evidence": []},
    ]
    transcript.write_text("".join(json.dumps(item) + "\n" for item in events), encoding="utf-8")

    score = score_transcript(case_dir, transcript)
    assert score["passed"] is False
    assert score["quality"]["unsupported_claim_hits"] == 1
    assert score["quality"]["citation"]["invalid_lines"] == [99]


def test_root_cause_score_rejects_correct_claims_with_unrelated_valid_citation(tmp_path: Path) -> None:
    case_dir = _case(tmp_path)
    transcript = tmp_path / "unsupported-by-citation.jsonl"
    events = [
        {"type": "session", "mode": "tracecite", "model": "demo"},
        {"type": "tool", "tool": "tracecite_search", "output": "runtime.log #L12 ChecksumException", "duration_ms": 1},
        {
            "type": "final",
            "answer": (
                "The worker queue hit a checksum mismatch because a stale cache entry was reused; "
                "the fix should invalidate the cache.\n\n"
                "A separate observation is visible at L12."
            ),
            "evidence": [],
        },
    ]
    transcript.write_text("".join(json.dumps(item) + "\n" for item in events), encoding="utf-8")

    score = score_transcript(case_dir, transcript)
    assert score["quality"]["dimension_recall"] == 1.0
    assert score["quality"]["citation"]["accuracy"] == 1.0
    assert score["quality"]["supported_dimension_recall"] == 0.0
    assert score["passed"] is False
