from __future__ import annotations

import json

from tracecite.runtime.evidence_selection import select_signal_hints


def _record(line: int, text: str) -> str:
    return json.dumps(
        {
            "text": text,
            "metadata": {"start_line": line, "end_line": line},
        }
    )


def test_late_panic_survives_bounded_signature_capacity(tmp_path) -> None:
    records = tmp_path / "records.jsonl"
    rows = [
        _record(index, f"ERROR worker shard={index} code=E{index}")
        for index in range(1, 80)
    ]
    rows.append(
        _record(
            103399,
            "panic: failed to set defaults: PodLevelResourcesFixDefaulting is enabled but PodLevelResources is disabled",
        )
    )
    records.write_text("\n".join(rows) + "\n", encoding="utf-8")

    hints = select_signal_hints(records, limit=4, signature_cap=16)

    assert any(item["line"] == 103399 for item in hints)
    panic = next(item for item in hints if item["line"] == 103399)
    assert panic["severity"] == 4
    assert "PodLevelResourcesFixDefaulting" in panic["label"]


def test_repeated_low_severity_signal_does_not_hide_unique_fatal(tmp_path) -> None:
    records = tmp_path / "records.jsonl"
    rows = [
        _record(index, f"ERROR disk capacity invalid value={index}")
        for index in range(1, 40)
    ]
    rows.append(_record(9000, "FATAL runtime corruption detected in checkpoint"))
    records.write_text("\n".join(rows) + "\n", encoding="utf-8")

    hints = select_signal_hints(records, limit=2, signature_cap=8)

    assert hints[0]["line"] == 9000
    assert hints[0]["severity"] == 4
