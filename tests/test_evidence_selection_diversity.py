from __future__ import annotations

import json
from pathlib import Path

import pytest

from tracecite.runtime.evidence_selection import (
    HINT_LABEL_CHAR_LIMIT,
    MAX_EVIDENCE_SEGMENT_LINES,
    MAX_SIGNAL_HINT_LIMIT,
    MAX_STRUCTURAL_NEIGHBORHOOD_RADIUS,
    select_signal_hints,
    structural_signature,
)


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
    assert rare_hint["grouping_view"] == "structural"
    assert rare_hint["count"] == 1
    assert rare_hint["severity"] == 0

    common_hint = next(item for item in hints if item["line"] == 10)
    assert common_hint["count"] == 61
    assert hints.index(rare_hint) < hints.index(common_hint)


def test_source_neighborhood_fingerprint_stays_metadata_only(tmp_path: Path) -> None:
    source = tmp_path / "goroutines.txt"
    records = tmp_path / "matched-records.jsonl"

    lines = [f"filler {index}\n" for index in range(1, 260)]
    match_lines = [50, 90, 130, 170, 210]
    for line in match_lines[:-1]:
        lines[line - 3] = "example.com/project.(*CommonCaller).Run()\n"
        lines[line - 2] = "/src/common.go:42 +0x4a\n"
        lines[line - 1] = "example.com/project.(*Collector).Add()\n"
    rare_line = match_lines[-1]
    rare_marker = "example.com/project.(*RareCaller).SpecialPath()"
    lines[rare_line - 3] = rare_marker + "\n"
    lines[rare_line - 2] = "/src/rare.go:77 +0x9b\n"
    lines[rare_line - 1] = "example.com/project.(*Collector).Add()\n"
    source.write_text("".join(lines), encoding="utf-8")

    rows = [_record("example.com/project.(*Collector).Add()", line) for line in match_lines]
    records.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )

    hints = select_signal_hints(
        records,
        source_path=source,
        limit=4,
        signature_cap=256,
    )

    assert len(hints) <= 4
    rare_hint = next(item for item in hints if item["match_line"] == rare_line)
    assert rare_hint["grouping_view"] == "structural"
    assert rare_hint["line"] <= rare_line <= rare_hint["end_line"]
    assert rare_hint["end_line"] - rare_hint["line"] + 1 <= MAX_EVIDENCE_SEGMENT_LINES
    assert rare_hint["expand_radius"] <= MAX_EVIDENCE_SEGMENT_LINES // 2
    serialized = json.dumps(hints, sort_keys=True)
    assert rare_marker not in serialized
    assert all(len(str(item.get("label") or "")) <= HINT_LABEL_CHAR_LIMIT for item in hints)
    assert all("text" not in item and "neighborhood" not in item for item in hints)


def test_stack_hint_navigates_to_complete_bounded_block(tmp_path: Path) -> None:
    source = tmp_path / "goroutines.txt"
    records = tmp_path / "matched-records.jsonl"
    source_lines = [f"noise {index}\n" for index in range(1, 11)] + [
        "\n",
        "goroutine 7 [semacquire]:\n",
        "sync.(*Mutex).Lock()\n",
        "/usr/local/go/src/sync/mutex.go:81\n",
        "example.com/project.(*Collector).Add()\n",
        "/src/collector.go:163 +0x1da\n",
        "example.com/project.(*local).Create()\n",
        "/src/local.go:233 +0xa14\n",
        "\n",
        "tail\n",
    ]
    source.write_text("".join(source_lines), encoding="utf-8")
    match_line = 15
    records.write_text(
        json.dumps(_record("example.com/project.(*Collector).Add()", match_line)) + "\n",
        encoding="utf-8",
    )

    hints = select_signal_hints(records, source_path=source, limit=1, signature_cap=16)

    assert len(hints) == 1
    hint = hints[0]
    assert hint["match_line"] == match_line
    assert hint["line"] == 12
    assert hint["end_line"] == 18
    assert hint["segment_kind"] == "stack_block"
    assert hint["expand_line"] == 15
    assert hint["expand_radius"] == 3
    assert "segment=stack_block" in hint["label"]
    assert "expand_line=15" in hint["label"]
    assert "expand_radius=3" in hint["label"]
    assert "goroutine 7" not in json.dumps(hints)


def test_drain_groups_dynamic_plain_log_templates_when_installed(tmp_path: Path) -> None:
    pytest.importorskip("drain3")
    records = tmp_path / "matched-records.jsonl"
    request_ids = [
        "alpha",
        "bravo",
        "charlie",
        "delta",
        "echo",
        "foxtrot",
        "golf",
        "hotel",
    ]
    rows = [
        _record(
            f"request={request_id} operation=fetch timeout after {100 + index}ms",
            10 + index,
        )
        for index, request_id in enumerate(request_ids)
    ]
    rows.append(_record("permission denied while opening credentials", 100))
    records.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )

    hints = select_signal_hints(records, limit=4, signature_cap=256)

    template_hint = next(item for item in hints if item["grouping_view"] == "template")
    assert template_hint["count"] == len(request_ids)
    assert template_hint["severity"] == 3
    assert "<*>" not in json.dumps(hints)


def test_structural_navigation_rejects_unbounded_output_requests(tmp_path: Path) -> None:
    records = tmp_path / "matched-records.jsonl"
    records.write_text(json.dumps(_record("one match", 1)) + "\n", encoding="utf-8")

    with pytest.raises(ValueError):
        select_signal_hints(records, limit=MAX_SIGNAL_HINT_LIMIT + 1)
    with pytest.raises(ValueError):
        select_signal_hints(
            records,
            neighborhood_radius=MAX_STRUCTURAL_NEIGHBORHOOD_RADIUS + 1,
        )
