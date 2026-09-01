from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path

from tracecite.benchmarking import prepare_case, validate_case


CASES_ROOT = (
    Path(__file__).resolve().parents[1]
    / "benchmarks"
    / "agent-investigation"
    / "cases"
)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def test_prepare_case_extracts_and_pins_gzip_payload(tmp_path: Path) -> None:
    payload = b"goroutine 1 [semacquire]:\ncontainerd metrics collector\n"
    archive = gzip.compress(payload)
    source = tmp_path / "incident.log.gz"
    source.write_bytes(archive)

    case_dir = tmp_path / "case"
    case_dir.mkdir()
    (case_dir / "question.md").write_text("Why did the runtime stall?\n", encoding="utf-8")
    (case_dir / "gold.json").write_text("{}\n", encoding="utf-8")
    (case_dir / "case.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "id": "archive-case",
                "question_file": "question.md",
                "gold_file": "gold.json",
                "inputs": [
                    {
                        "id": "goroutines",
                        "url": source.as_uri(),
                        "filename": "goroutines.txt",
                        "sha256": _sha256(archive),
                        "extract": {
                            "kind": "gzip",
                            "sha256": _sha256(payload),
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    assert validate_case(case_dir)["status"] == "ok"
    result = prepare_case(case_dir, tmp_path / "work")
    prepared = result["prepared"][0]
    assert prepared["bytes"] == len(payload)
    assert prepared["sha256"] == _sha256(payload)
    assert prepared["source_bytes"] == len(archive)
    assert prepared["source_sha256"] == _sha256(archive)
    assert prepared["extract"] == {"kind": "gzip"}
    assert Path(prepared["path"]).read_bytes() == payload


def test_containerd_6772_case_is_valid_and_does_not_leak_gold() -> None:
    case_dir = CASES_ROOT / "containerd-6772"
    result = validate_case(case_dir)
    assert result["status"] == "ok"
    assert result["case_id"] == "containerd-6772"
    question = (case_dir / "question.md").read_text(encoding="utf-8")
    assert "WithConstLabels" not in question
    assert "lock inversion" not in question
    assert "deadlock in metrics" not in question
