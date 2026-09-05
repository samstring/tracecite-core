from __future__ import annotations

import json

from tracecite.runtime import EvidenceShellPolicy, EvidenceShellRequest, run_evidence_shell
from tracecite_core.segmenter import JsonLineSegmenter


def _policy() -> EvidenceShellPolicy:
    return EvidenceShellPolicy(
        max_evidence_tokens=20_000,
        max_evidence_bytes=200_000,
        source_mode="static",
    )


def _source(tmp_path, rows) -> str:
    path = tmp_path / "events.jsonl"
    path.write_text(
        "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )
    return str(path)


def test_where_head_uses_streaming_jsonl_without_record_scan(tmp_path, monkeypatch) -> None:
    source = _source(
        tmp_path,
        [
            {"spanID": "other", "seq": 1},
            {"spanID": "target", "seq": 2},
            {"spanID": "target", "seq": 3},
            {"spanID": "target", "seq": 4},
            *({"spanID": "target", "seq": index} for index in range(5, 5000)),
        ],
    )

    def fail_segment_file(*args, **kwargs):
        raise AssertionError("bounded JSONL selection must not construct Records")

    monkeypatch.setattr(JsonLineSegmenter, "segment_file", fail_segment_file)

    import tracecite.runtime.evidence_shell_jsonl_selection as selection

    real_loads = selection.json_loads
    decodes = 0

    def counted_loads(value):
        nonlocal decodes
        decodes += 1
        return real_loads(value)

    # Patch only the source-line decoder. Patching stdlib json.loads globally
    # would also count SourceVersion/session state JSON and would not measure the
    # physical source scan we are asserting here.
    monkeypatch.setattr(selection, "json_loads", counted_loads)

    result = run_evidence_shell(
        EvidenceShellRequest(source=source, program="where spanID == target | head 3"),
        policy=_policy(),
    )

    assert result["status"] == "ok"
    assert result["data"]["execution_engine"] == "jsonl_streaming_bounded_head"
    assert result["data"]["physical_plan"]["selection"] == "early_stop_head"
    assert [item["start_line"] for item in result["evidence"]] == [2, 3, 4]
    assert decodes == 4


def test_where_sort_head_uses_fixed_capacity_topk_without_record_scan(tmp_path, monkeypatch) -> None:
    source = _source(
        tmp_path,
        [
            {"traceID": "x", "duration": 2, "name": "early-low"},
            {"traceID": "other", "duration": 999, "name": "ignore"},
            {"traceID": "x", "duration": 9, "name": "first-high"},
            {"traceID": "x", "duration": 9, "name": "second-high"},
            {"traceID": "x", "duration": 4, "name": "mid"},
        ],
    )

    def fail_segment_file(*args, **kwargs):
        raise AssertionError("sorted JSONL selection must not construct Records")

    monkeypatch.setattr(JsonLineSegmenter, "segment_file", fail_segment_file)

    result = run_evidence_shell(
        EvidenceShellRequest(
            source=source,
            program="where traceID == x | sort duration desc numeric | head 2",
        ),
        policy=_policy(),
    )

    assert result["status"] == "ok"
    # Keep the old transport-visible engine label while asserting the new
    # physical implementation explicitly.
    assert result["data"]["execution_engine"] == "bounded_terminal_topn"
    assert result["data"]["physical_plan"]["selection"] == "fixed_capacity_topk"
    assert result["data"]["physical_plan"]["source_scan"] == "jsonl_raw_lines"
    # Equal sort keys preserve source order, matching canonical stable sort.
    assert [item["start_line"] for item in result["evidence"]] == [3, 4]


def test_sort_head_project_stays_streaming_and_matches_project_shape(tmp_path, monkeypatch) -> None:
    source = _source(
        tmp_path,
        [
            {"service": "a", "duration": 2, "started": 20},
            {"service": "b", "duration": 9, "started": 30},
            {"service": "a", "duration": 7, "started": 10},
            {"service": "a", "duration": 5, "started": 40},
        ],
    )

    def fail_segment_file(*args, **kwargs):
        raise AssertionError("projected JSONL selection must not construct Records")

    monkeypatch.setattr(JsonLineSegmenter, "segment_file", fail_segment_file)

    import tracecite.runtime.evidence_shell_jsonl_selection as selection

    semantic_calls = 0
    real_semantics = selection.extract_jsonline_semantics

    def counted_semantics(*args, **kwargs):
        nonlocal semantic_calls
        semantic_calls += 1
        return real_semantics(*args, **kwargs)

    monkeypatch.setattr(selection, "extract_jsonline_semantics", counted_semantics)

    result = run_evidence_shell(
        EvidenceShellRequest(
            source=source,
            program=(
                "where service == a | sort duration desc numeric | head 2 "
                "| project duration started"
            ),
        ),
        policy=_policy(),
    )

    assert result["status"] == "ok"
    assert result["coverage"] == {"complete": True, "match_records": 2}
    assert result["data"]["execution_engine"] == "bounded_terminal_topn"
    assert result["data"]["physical_plan"]["projection"] == "post_selection"
    assert result["data"]["aggregate"]["fields"] == ["duration", "started"]
    assert [row["values"] for row in result["data"]["aggregate"]["rows"]] == [
        {"duration": 7, "started": 10},
        {"duration": 5, "started": 40},
    ]
    # No semantic field participates in predicate/sort/project, and projected
    # aggregates do not need EvidencePointer timestamps.
    assert semantic_calls == 0


def test_topk_semantics_are_enriched_only_for_retained_evidence(tmp_path, monkeypatch) -> None:
    source = _source(
        tmp_path,
        [
            {"name": "target", "duration": index, "time": 1733674800 + index}
            for index in range(1000)
        ],
    )

    import tracecite.runtime.evidence_shell_jsonl_selection as selection

    semantic_calls = 0
    real_semantics = selection.extract_jsonline_semantics

    def counted_semantics(*args, **kwargs):
        nonlocal semantic_calls
        semantic_calls += 1
        return real_semantics(*args, **kwargs)

    monkeypatch.setattr(selection, "extract_jsonline_semantics", counted_semantics)

    result = run_evidence_shell(
        EvidenceShellRequest(
            source=source,
            program="search target | sort duration desc numeric | head 3",
        ),
        policy=_policy(),
    )

    assert result["status"] == "ok"
    assert [item["start_line"] for item in result["evidence"]] == [1000, 999, 998]
    # Timestamp semantics are needed for the three final EvidencePointers, not
    # for every discarded Top-K candidate.
    assert semantic_calls == 3


def test_absolute_time_scope_keeps_untimestamped_records_like_canonical(tmp_path) -> None:
    source = _source(
        tmp_path,
        [
            {"timestamp": "2026-09-05T10:00:00Z", "kind": "x"},
            {"timestamp": "2026-09-05T10:05:00Z", "kind": "x"},
            {"kind": "x"},
            {"timestamp": "2026-09-05T10:20:00Z", "kind": "x"},
        ],
    )

    result = run_evidence_shell(
        EvidenceShellRequest(
            source=source,
            program="where kind == x | head 3",
            since="2026-09-05T10:04:00Z",
            until="2026-09-05T10:10:00Z",
        ),
        policy=_policy(),
    )

    assert result["status"] == "ok"
    assert [item["start_line"] for item in result["evidence"]] == [2, 3]
