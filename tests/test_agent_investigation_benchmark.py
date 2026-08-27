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


def test_benchmark_scores_quality_and_context_cost(tmp_path: Path) -> None:
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
    assert result["context_cost"]["reported_input_tokens"] == 10
    assert result["context_cost"]["reported_output_tokens"] == 30


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
