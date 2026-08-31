from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCORE_SCRIPT = ROOT / "benchmarks" / "agent-investigation" / "log_code_score.py"
ADAPTER_SCRIPT = ROOT / "benchmarks" / "agent-investigation" / "pi_session_to_transcript.py"


def _load_score_module():
    spec = importlib.util.spec_from_file_location("tracecite_log_code_score", SCORE_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _case(tmp_path: Path) -> Path:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    _write_json(
        case_dir / "case.json",
        {
            "schema_version": 1,
            "id": "log-code-demo",
            "source_issue": "https://github.com/example/project/issues/1",
            "fix_reference": "https://github.com/example/project/pull/2",
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
    (case_dir / "question.md").write_text("Why did it fail?\n", encoding="utf-8")
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
            "unsupported_claims": [],
            "contradictions": [],
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


def _write_transcript(path: Path, answer: str, source_path: str = "pkg/worker.go") -> None:
    events = [
        {"type": "session", "mode": "pi-log-code-native", "model": "demo"},
        {
            "type": "tool",
            "name": "read",
            "arguments": {
                "path": f"/tmp/run/workspace/source/{source_path}",
                "offset": 40,
                "limit": 4,
            },
            "output": "line 40\nworker queue checksum mismatch\nstale cache entry\ninvalidate cache",
        },
        {
            "type": "tool",
            "name": "grep",
            "arguments": {"path": "/tmp/run/workspace/evidence/runtime.log", "pattern": "ChecksumException"},
            "output": "runtime.log:12: ChecksumException in worker queue",
        },
        {"type": "final", "answer": answer},
    ]
    path.write_text("".join(json.dumps(row) + "\n" for row in events), encoding="utf-8")


def test_log_code_score_accepts_source_and_runtime_path_citations(tmp_path: Path) -> None:
    module = _load_score_module()
    case_dir = _case(tmp_path)
    transcript = tmp_path / "run.jsonl"
    _write_transcript(
        transcript,
        (
            "The worker queue hit a checksum mismatch because of a stale cache entry; "
            "invalidate the cache. Evidence: pkg/worker.go:L41 and runtime.log:L12."
        ),
    )

    score = module.score_log_code(case_dir, transcript)
    citation = score["quality"]["citation"]
    assert score["passed"] is True
    assert score["quality"]["supported_dimension_recall"] == 1.0
    assert citation["accuracy"] == 1.0
    assert "pkg/worker.go:L41" in citation["valid_refs"]
    assert "evidence/runtime.log:L12" in citation["valid_refs"]


def test_log_code_score_does_not_validate_same_line_in_wrong_source_file(tmp_path: Path) -> None:
    module = _load_score_module()
    case_dir = _case(tmp_path)
    transcript = tmp_path / "wrong-path.jsonl"
    _write_transcript(
        transcript,
        (
            "The worker queue hit a checksum mismatch because of a stale cache entry; "
            "invalidate the cache. Evidence: pkg/other.go:L41."
        ),
    )

    score = module.score_log_code(case_dir, transcript)
    citation = score["quality"]["citation"]
    assert score["passed"] is False
    assert citation["accuracy"] == 0.0
    assert citation["invalid_refs"] == ["pkg/other.go:L41"]
    assert score["quality"]["supported_dimension_recall"] == 0.0


def test_pi_session_adapter_preserves_tool_call_arguments(tmp_path: Path) -> None:
    session = tmp_path / "session.jsonl"
    answer = tmp_path / "answer.md"
    transcript = tmp_path / "transcript.jsonl"
    call_id = "call_read_1"
    session.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "message",
                        "message": {
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "toolCall",
                                    "id": call_id,
                                    "name": "read",
                                    "arguments": {"path": "/tmp/workspace/source/pkg/worker.go", "offset": 40, "limit": 4},
                                }
                            ],
                            "usage": {"input": 1, "output": 1},
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "message",
                        "message": {
                            "role": "toolResult",
                            "toolCallId": call_id,
                            "toolName": "read",
                            "content": [{"type": "text", "text": "a\nb\nc\nd"}],
                        },
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    answer.write_text("pkg/worker.go:L41\n", encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            str(ADAPTER_SCRIPT),
            str(session),
            str(answer),
            str(transcript),
            "--mode",
            "pi-log-code-native",
            "--model",
            "demo",
        ],
        cwd=ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert completed.returncode == 0, completed.stderr
    rows = [json.loads(line) for line in transcript.read_text().splitlines() if line.strip()]
    tool = next(row for row in rows if row.get("type") == "tool")
    assert tool["arguments"] == {
        "path": "/tmp/workspace/source/pkg/worker.go",
        "offset": 40,
        "limit": 4,
    }
