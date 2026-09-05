from __future__ import annotations

import json

from tracecite_core.record_search import iter_matching_records
from tracecite_core.segmenter import JsonLineSegmenter


def test_unscoped_record_search_does_not_compute_reference_datetime(tmp_path, monkeypatch) -> None:
    source = tmp_path / "records.jsonl"
    source.write_text(
        "".join(json.dumps({"n": i}, separators=(",", ":")) + "\n" for i in range(5)),
        encoding="utf-8",
    )

    import tracecite_core.record_search as record_search

    def fail_reference(*args, **kwargs):
        raise AssertionError("unscoped record search must not pre-scan for a reference timestamp")

    monkeypatch.setattr(record_search, "reference_datetime", fail_reference)

    rows = list(
        iter_matching_records(
            source,
            query=None,
            segmenter=JsonLineSegmenter(),
            line_from=1,
            line_to=2,
        )
    )

    assert [row.start_line for row in rows] == [1, 2]


def test_explicit_time_scope_still_computes_reference_datetime(tmp_path, monkeypatch) -> None:
    source = tmp_path / "records.jsonl"
    source.write_text('{"timestamp":"2026-09-05T00:00:00Z","n":1}\n', encoding="utf-8")

    import tracecite_core.record_search as record_search

    calls = 0
    real_reference = record_search.reference_datetime

    def counted_reference(*args, **kwargs):
        nonlocal calls
        calls += 1
        return real_reference(*args, **kwargs)

    monkeypatch.setattr(record_search, "reference_datetime", counted_reference)

    list(
        iter_matching_records(
            source,
            query=None,
            segmenter=JsonLineSegmenter(),
            since="2026-09-05T00:00:00Z",
        )
    )

    assert calls == 1
