from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from tracecite.benchmarking import score_transcript


RUNNER = (
    Path(__file__).resolve().parents[1]
    / "benchmarks"
    / "agent-investigation"
    / "run_host.py"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_case(tmp_path: Path) -> tuple[Path, Path]:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    source = tmp_path / "prepared-source.log"
    source.write_text("alpha\ntarget marker\nomega\n", encoding="utf-8")
    digest = _sha256(source)

    (case_dir / "question.md").write_text("Why did this fail?\n", encoding="utf-8")
    (case_dir / "gold.json").write_text(
        json.dumps(
            {
                "required_concepts": [
                    {"id": "root-cause", "patterns": ["root cause"]}
                ],
                "evidence_markers": ["target marker"],
                "thresholds": {
                    "concept_recall": 1.0,
                    "evidence_marker_recall": 1.0,
                },
                "leak_terms": ["evaluator secret root cause"],
            }
        ),
        encoding="utf-8",
    )
    (case_dir / "case.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "id": "runner-case",
                "question_file": "question.md",
                "gold_file": "gold.json",
                "inputs": [
                    {
                        "id": "log",
                        "url": "https://example.invalid/log.txt",
                        "filename": "prepared-source.log",
                        "sha256": digest,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    prepared = tmp_path / "prepared.json"
    prepared.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "case_id": "runner-case",
                "inputs": [
                    {
                        "id": "log",
                        "path": str(source),
                        "bytes": source.stat().st_size,
                        "sha256": digest,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return case_dir, prepared


def test_external_host_runner_isolates_gold_and_records_scoreable_transcript(
    tmp_path: Path, monkeypatch
) -> None:
    case_dir, prepared = _write_case(tmp_path)
    output = tmp_path / "run.jsonl"
    fake_host = tmp_path / "fake_host.py"
    fake_host.write_text(
        """
import json
import os
from pathlib import Path

workspace = Path(os.environ["TRACECITE_BENCH_WORKSPACE"])
question = Path(os.environ["TRACECITE_BENCH_QUESTION"])
inputs = Path(os.environ["TRACECITE_BENCH_INPUTS"])
transcript = Path(os.environ["TRACECITE_BENCH_TRANSCRIPT"])

if "EVALUATOR_ONLY_SECRET" in os.environ:
    raise SystemExit(11)
if (workspace / "gold.json").exists() or (workspace / "case.json").exists():
    raise SystemExit(12)
if question.read_text(encoding="utf-8").strip() != "Why did this fail?":
    raise SystemExit(13)
if not (inputs / "prepared-source.log").is_file():
    raise SystemExit(14)

with transcript.open("a", encoding="utf-8") as handle:
    for event in [
        {
            "type": "model",
            "content": "I will inspect the local evidence.",
            "usage": {"input_tokens": 100, "output_tokens": 20},
        },
        {
            "type": "tool",
            "tool": "fake-read",
            "input": {"path": "inputs/prepared-source.log"},
            "output": "target marker",
        },
        {
            "type": "final",
            "answer": "The root cause is the target condition.",
            "evidence": ["inputs/prepared-source.log:2"],
        },
    ]:
        handle.write(json.dumps(event, sort_keys=True) + "\\n")
""".strip()
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("EVALUATOR_ONLY_SECRET", "must-not-reach-host")

    completed = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            str(case_dir),
            str(prepared),
            "--mode",
            "tracecite_context",
            "--model",
            "fake/model",
            "--seed",
            "7",
            "--output",
            str(output),
            "--",
            sys.executable,
            str(fake_host),
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=os.environ.copy(),
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout
    result = json.loads(completed.stdout)
    assert result["status"] == "ok"
    assert result["mode"] == "tracecite_context"
    assert result["context_id"]
    assert result["events"] == {"final": 1, "model": 1, "tool": 1}

    events = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert events[0]["type"] == "session"
    assert events[0]["seed"] == 7
    assert events[0]["context_id"] == result["context_id"]

    scored = score_transcript(case_dir, output)
    assert scored["passed"] is True
    assert scored["context_cost"]["usage_source"] == "model_events"
    assert scored["context_cost"]["reported_input_tokens"] == 100
    assert scored["context_cost"]["reported_output_tokens"] == 20


def test_external_host_runner_rejects_tampered_prepared_input(tmp_path: Path) -> None:
    case_dir, prepared = _write_case(tmp_path)
    payload = json.loads(prepared.read_text(encoding="utf-8"))
    Path(payload["inputs"][0]["path"]).write_text("tampered\n", encoding="utf-8")
    output = tmp_path / "run.jsonl"

    completed = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            str(case_dir),
            str(prepared),
            "--mode",
            "shell_rg",
            "--model",
            "fake/model",
            "--output",
            str(output),
            "--",
            sys.executable,
            "-c",
            "raise SystemExit(0)",
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    assert completed.returncode == 1
    result = json.loads(completed.stdout)
    assert result["status"] == "error"
    assert "digest mismatch" in result["error"]
    assert not output.exists()
