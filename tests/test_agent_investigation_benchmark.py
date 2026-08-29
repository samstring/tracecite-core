from __future__ import annotations

import json
from pathlib import Path

import pytest

from tracecite.benchmarking import score_transcript, validate_case


CASES_ROOT = (
    Path(__file__).resolve().parents[1]
    / "benchmarks"
    / "agent-investigation"
    / "cases"
)
KUBERNETES_CASE = CASES_ROOT / "kubernetes-140848"
FLUTTER_CASE = CASES_ROOT / "flutter-179398"


@pytest.mark.parametrize(
    ("case_dir", "case_id", "forbidden"),
    [
        (KUBERNETES_CASE, "kubernetes-140848", "PodLevelResourcesFixDefaulting"),
        (FLUTTER_CASE, "flutter-179398", "RoundSuperellipse"),
    ],
)
def test_real_world_case_is_valid_and_does_not_leak_gold(
    case_dir: Path, case_id: str, forbidden: str
) -> None:
    result = validate_case(case_dir)
    assert result["status"] == "ok"
    assert result["case_id"] == case_id
    question = (case_dir / "question.md").read_text(encoding="utf-8")
    assert forbidden not in question


def test_case_requires_pinned_source_sha256(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    (case_dir / "question.md").write_text("Why did this fail?\n", encoding="utf-8")
    (case_dir / "gold.json").write_text("{}\n", encoding="utf-8")
    (case_dir / "case.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "id": "unpinned",
                "question_file": "question.md",
                "gold_file": "gold.json",
                "inputs": [
                    {
                        "id": "log",
                        "url": "https://example.invalid/log.txt",
                        "filename": "log.txt",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="sha256"):
        validate_case(case_dir)


def test_benchmark_scores_quality_and_legacy_tool_token_cost(tmp_path: Path) -> None:
    transcript = tmp_path / "run.jsonl"
    events = [
        {"type": "session", "mode": "tracecite_context", "model": "test-model"},
        {
            "type": "tool",
            "tool": "search",
            "output": (
                "panic: failed to merge global and in-flight KubeletConfiguration while setting defaults\n"
                "error: PodLevelResourcesFixDefaulting is enabled, but depends on features that are\n"
                "disabled: [PodLevelResources]"
            ),
            "input_tokens": 10,
            "output_tokens": 30,
        },
        {
            "type": "final",
            "answer": (
                "The kubelet panics during startup because feature gate dependency validation finds "
                "PodLevelResourcesFixDefaulting enabled while PodLevelResources is disabled. The restart/panic "
                "loop makes /configz unavailable, so the context deadline exceeded error is downstream."
            ),
            "evidence": ["evidence://sha256/example#L1-L3"],
        },
    ]
    transcript.write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )

    result = score_transcript(KUBERNETES_CASE, transcript)
    assert result["passed"] is True
    assert result["quality"]["concept_recall"] == 1.0
    assert result["quality"]["evidence_marker_recall"] == 1.0
    assert result["context_cost"]["tool_calls"] == 1
    assert result["context_cost"]["usage_source"] == "legacy_tool_fields"
    assert result["context_cost"]["reported_input_tokens"] == 10
    assert result["context_cost"]["reported_output_tokens"] == 30


def test_model_usage_is_authoritative_and_not_double_counted_with_tool_fields(
    tmp_path: Path,
) -> None:
    transcript = tmp_path / "provider-usage.jsonl"
    events = [
        {"type": "session", "mode": "tracecite_context", "model": "provider/model"},
        {
            "type": "model",
            "content": "I will inspect the panic.",
            "usage": {
                "input_tokens": 1000,
                "output_tokens": 80,
                "reasoning_tokens": 25,
                "cached_input_tokens": 400,
            },
        },
        {
            "type": "tool",
            "tool": "search",
            "output": "PodLevelResourcesFixDefaulting depends on PodLevelResources",
            "input_tokens": 99999,
            "output_tokens": 99999,
        },
        {
            "type": "model",
            "content": "The dependency mismatch explains the panic.",
            "usage": {
                "input_tokens": 1200,
                "output_tokens": 100,
                "reasoning_tokens": 30,
                "cached_input_tokens": 600,
                "cache_read_input_tokens": 500,
                "cache_creation_input_tokens": 50,
            },
        },
        {
            "type": "final",
            "answer": (
                "The kubelet panics because feature gate dependency validation sees "
                "PodLevelResourcesFixDefaulting enabled while PodLevelResources is disabled."
            ),
            "evidence": [],
        },
    ]
    transcript.write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )

    result = score_transcript(KUBERNETES_CASE, transcript)
    cost = result["context_cost"]
    assert cost["model_calls"] == 2
    assert cost["usage_source"] == "model_events"
    assert cost["usage_events"] == 2
    assert cost["reported_input_tokens"] == 2200
    assert cost["reported_output_tokens"] == 180
    assert cost["reported_reasoning_tokens"] == 55
    assert cost["reported_cached_input_tokens"] == 1000
    assert cost["reported_cache_read_input_tokens"] == 500
    assert cost["reported_cache_creation_input_tokens"] == 50


def test_benchmark_counts_exact_duplicate_visible_output(tmp_path: Path) -> None:
    transcript = tmp_path / "duplicate.jsonl"
    repeated = "same evidence block"
    transcript.write_text(
        "\n".join(
            [
                json.dumps({"type": "session", "mode": "shell_rg"}),
                json.dumps({"type": "tool", "tool": "rg", "output": repeated}),
                json.dumps({"type": "tool", "tool": "rg", "output": repeated}),
                json.dumps({"type": "final", "answer": "unknown", "evidence": []}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = score_transcript(KUBERNETES_CASE, transcript)
    assert result["context_cost"]["tool_output_chars"] == len(repeated) * 2
    assert result["context_cost"]["unique_tool_output_chars"] == len(repeated)
    assert result["context_cost"]["exact_duplicate_tool_output_chars"] == len(repeated)

def test_score_threshold_uses_reported_four_decimal_precision(tmp_path: Path) -> None:
    transcript = tmp_path / "precision.jsonl"
    events = [
        {"type": "session", "mode": "tracecite_context", "model": "test-model"},
        {"type": "tool", "tool": "search", "output": "DrawCircularArc round_superellipse_geometry.cc"},
        {
            "type": "final",
            "answer": (
                "Impeller RoundSuperellipse DrawCircularArc. A use-after-free lifetime bug left a poisoned pointer; "
                "the crashed thread is not the corrupting thread and is only a downstream manifestation."
            ),
            "evidence": [],
        },
    ]
    transcript.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")
    result = score_transcript(FLUTTER_CASE, transcript)
    assert result["quality"]["concept_recall"] == 1.0
    assert result["quality"]["evidence_marker_recall"] == 0.6667
    assert result["passed"] is True
