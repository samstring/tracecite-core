from __future__ import annotations

import json
from pathlib import Path

from tracecite.runtime.evidence_selection import select_signal_hints, structural_signature


def _record(text: str, start_line: int) -> dict:
    return {
        "text": text,
        "metadata": {
            "start_line": start_line,
            "end_line": start_line + max(0, len(text.splitlines()) - 1),
        },
    }


def test_structural_signature_normalizes_volatile_stack_values() -> None:
    left = """goroutine 101 [sync.Mutex.Lock]:
example.com/project.(*Worker).Handle(0xc000123456)
/src/worker.go:123 +0x4a
example.com/project.(*Queue).Run(42)
/src/queue.go:88 +0x1f
"""
    right = """goroutine 902 [sync.Mutex.Lock]:
example.com/project.(*Worker).Handle(0xc000abcdef)
/src/worker.go:987 +0x9b
example.com/project.(*Queue).Run(77)
/src/queue.go:144 +0x2c
"""
    assert structural_signature(left) == structural_signature(right)


def test_truncated_search_retains_rare_structural_branch(tmp_path: Path) -> None:
    records = tmp_path / "matched-records.jsonl"
    common = """goroutine 101 [sync.Mutex.Lock]:
example.com/project.(*Worker).Handle(0xc000123456)
/src/worker.go:123 +0x4a
example.com/project.(*Queue).Run(42)
/src/queue.go:88 +0x1f
"""
    rare = """goroutine 999 [sync.Mutex.Lock]:
example.com/project.(*Worker).Handle(0xc000999999)
/src/worker.go:456 +0x7d
example.com/project.(*Registry).Refresh(17)
/src/registry.go:211 +0x33
example.com/project.(*Supervisor).Run(5)
/src/supervisor.go:72 +0x10
"""

    rows = [_record(common, 10 + index * 10) for index in range(61)]
    rows.append(_record(rare, 900))
    records.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )

    hints = select_signal_hints(records, limit=4, signature_cap=256)

    rare_hint = next(item for item in hints if item["line"] == 900)
    assert rare_hint["kind"] == "structural_diversity"
    assert rare_hint["count"] == 1
    assert rare_hint["severity"] == 0

    common_hint = next(item for item in hints if item["line"] == 10)
    assert common_hint["count"] == 61
    assert hints.index(rare_hint) < hints.index(common_hint)
