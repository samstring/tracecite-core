from __future__ import annotations

import json
from pathlib import Path

from tracecite.runtime import EvidenceShellPolicy, EvidenceShellRequest, run_evidence_shell


def _count(source: Path, program: str) -> int:
    result = run_evidence_shell(
        EvidenceShellRequest(source=source, program=program),
        policy=EvidenceShellPolicy(
            max_evidence_tokens=12_000,
            max_evidence_bytes=64 * 1024,
            source_mode="static",
        ),
    )
    assert result["status"] == "ok"
    return int(result["data"]["aggregate"]["count"])


def test_explicit_where_and_is_lowered_to_multiple_predicate_stages(tmp_path: Path) -> None:
    source = tmp_path / "events.jsonl"
    rows = [
        {"service": "route", "timestamp": 10, "status": 200},
        {"service": "route", "timestamp": 20, "status": 503},
        {"service": "travel", "timestamp": 20, "status": 503},
    ]
    source.write_text(
        "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )

    assert _count(
        source,
        "where service == route and timestamp >= 15 and timestamp <= 25 | count",
    ) == 1


def test_quoted_value_containing_and_is_not_split(tmp_path: Path) -> None:
    source = tmp_path / "messages.jsonl"
    rows = [
        {"message": "research and development"},
        {"message": "research"},
    ]
    source.write_text(
        "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )

    assert _count(source, 'where message == "research and development" | count') == 1
