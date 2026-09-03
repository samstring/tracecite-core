from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from tracecite.runtime import tools as runtime_tools
from tracecite_core.records import Record
from tracecite_core.segmenter import (
    FormatSegmenter,
    JsonLineSegmenter,
    RawTextSegmenter,
    Segmenter,
    build_segmenter,
    detect_segmenter_kind,
)


@dataclass(frozen=True)
class CandidateHit:
    line_number: int
    byte_start: int
    byte_end: int


class LocalRecoveryUnsupported(RuntimeError):
    pass


def _timed(fn):
    start = time.perf_counter()
    value = fn()
    return value, time.perf_counter() - start


def scan_literal(path: Path, query: str) -> list[CandidateHit]:
    needle = query.encode("utf-8")
    if not needle:
        raise ValueError("query must not be empty")
    hits: list[CandidateHit] = []
    offset = 0
    with path.open("rb") as handle:
        for line_number, raw in enumerate(handle, start=1):
            end = offset + len(raw)
            if needle in raw:
                hits.append(CandidateHit(line_number, offset, end))
            offset = end
    return hits


def _read_hit_line(path: Path, hit: CandidateHit) -> str:
    with path.open("rb") as handle:
        handle.seek(hit.byte_start)
        raw = handle.read(hit.byte_end - hit.byte_start)
    return raw.decode("utf-8", errors="replace")


def _single_line_record(path: Path, hit: CandidateHit, segmenter: Segmenter) -> Record:
    text = _read_hit_line(path, hit)
    records = list(segmenter.segment_lines(iter([(hit.line_number, text)])))
    if len(records) != 1:
        raise LocalRecoveryUnsupported(
            f"single-line recovery produced {len(records)} records for {type(segmenter).__name__}"
        )
    return records[0]


def _find_previous_format_start(
    path: Path,
    hit: CandidateHit,
    segmenter: FormatSegmenter,
    *,
    initial_bytes: int = 64 * 1024,
    max_bytes: int = 4 * 1024 * 1024,
) -> int:
    file_start = 0
    window = min(initial_bytes, max(hit.byte_end, 1))
    while True:
        start = max(file_start, hit.byte_start - window)
        with path.open("rb") as handle:
            handle.seek(start)
            data = handle.read(hit.byte_end - start)
        base = start
        if start > 0:
            first_nl = data.find(b"\n")
            if first_nl < 0:
                if window >= max_bytes:
                    raise LocalRecoveryUnsupported("no complete line in backward recovery window")
                window = min(max_bytes, window * 2)
                continue
            base += first_nl + 1
            data = data[first_nl + 1 :]
        cursor = base
        candidates: list[int] = []
        for raw in data.splitlines(keepends=True):
            line_start = cursor
            cursor += len(raw)
            if line_start > hit.byte_start:
                break
            text = raw.decode("utf-8", errors="replace")
            if segmenter.pattern.match(text):
                candidates.append(line_start)
        if candidates:
            return candidates[-1]
        if start == file_start:
            return file_start
        if window >= max_bytes:
            raise LocalRecoveryUnsupported("segment start not found within local recovery bound")
        window = min(max_bytes, window * 2)


def _find_next_format_start(
    path: Path,
    hit: CandidateHit,
    segmenter: FormatSegmenter,
    *,
    max_bytes: int = 4 * 1024 * 1024,
) -> int:
    size = path.stat().st_size
    scanned = 0
    with path.open("rb") as handle:
        handle.seek(hit.byte_end)
        while handle.tell() < size:
            line_start = handle.tell()
            raw = handle.readline()
            if not raw:
                break
            scanned += len(raw)
            text = raw.decode("utf-8", errors="replace")
            if segmenter.pattern.match(text):
                return line_start
            if scanned >= max_bytes:
                raise LocalRecoveryUnsupported("next segment start not found within local recovery bound")
    return size


def _physical_line_count(raw: bytes) -> int:
    if not raw:
        return 0
    return raw.count(b"\n") if raw.endswith(b"\n") else raw.count(b"\n") + 1


def _recover_format_record(path: Path, hit: CandidateHit, segmenter: FormatSegmenter) -> Record:
    continuation_kind = str((segmenter.continuation or {}).get("kind") or "")
    if continuation_kind:
        raise LocalRecoveryUnsupported(
            f"prototype does not locally recover continuation kind {continuation_kind!r}"
        )
    if not segmenter.multiline:
        return _single_line_record(path, hit, RawTextSegmenter(mode="line"))

    start = _find_previous_format_start(path, hit, segmenter)
    end = _find_next_format_start(path, hit, segmenter)
    with path.open("rb") as handle:
        handle.seek(start)
        raw = handle.read(end - start)
    prefix_len = max(0, hit.byte_start - start)
    start_line = hit.line_number - raw[:prefix_len].count(b"\n")
    text = raw.decode("utf-8", errors="replace")
    pairs = [
        (start_line + index, line)
        for index, line in enumerate(text.splitlines(keepends=True))
    ]
    records = list(segmenter.segment_lines(iter(pairs)))
    if len(records) != 1:
        raise LocalRecoveryUnsupported(
            f"local format recovery produced {len(records)} records for range {start}-{end}"
        )
    return records[0]


def recover_record(path: Path, hit: CandidateHit, segmenter: Segmenter) -> Record:
    if isinstance(segmenter, JsonLineSegmenter):
        return _single_line_record(path, hit, segmenter)
    if isinstance(segmenter, RawTextSegmenter) and segmenter.mode == "line":
        return _single_line_record(path, hit, segmenter)
    if isinstance(segmenter, FormatSegmenter):
        return _recover_format_record(path, hit, segmenter)
    raise LocalRecoveryUnsupported(type(segmenter).__name__)


def candidate_first_search(
    path: Path,
    query: str,
    *,
    max_evidence: int = 20,
) -> dict[str, object]:
    kind = detect_segmenter_kind(path)
    segmenter = build_segmenter(kind)
    hits, scan_seconds = _timed(lambda: scan_literal(path, query))

    recover_start = time.perf_counter()
    records: list[Record] = []
    unique_ranges: set[tuple[int, int]] = set()

    single_line_fast_path = isinstance(segmenter, JsonLineSegmenter) or (
        isinstance(segmenter, RawTextSegmenter) and segmenter.mode == "line"
    )
    if single_line_fast_path:
        for hit in hits[:max_evidence]:
            records.append(recover_record(path, hit, segmenter))
        match_records = len(hits)
        match_lines = len(hits)
    else:
        for hit in hits:
            record = recover_record(path, hit, segmenter)
            key = (record.start_line, record.end_line)
            if key in unique_ranges:
                continue
            unique_ranges.add(key)
            if len(records) < max_evidence:
                records.append(record)
        match_records = len(unique_ranges)
        match_lines = sum(end - start + 1 for start, end in unique_ranges)

    recover_seconds = time.perf_counter() - recover_start
    return {
        "segmenter": str(kind),
        "status": "ok" if match_records else "no_match",
        "match_records": match_records,
        "match_lines": match_lines,
        "evidence_returned": len(records),
        "ranges": [[record.start_line, record.end_line] for record in records],
        "scan_seconds": round(scan_seconds, 6),
        "recover_seconds": round(recover_seconds, 6),
        "seconds": round(scan_seconds + recover_seconds, 6),
    }


def _legacy_search(path: Path, query: str, max_evidence: int) -> dict[str, object]:
    result = runtime_tools.search(
        path,
        query,
        regex=False,
        snapshot=False,
        max_evidence=max_evidence,
        investigation_path=None,
        cache=False,
    )
    coverage = result.get("coverage") or {}
    evidence = result.get("evidence") or []
    return {
        "status": result.get("status"),
        "match_records": coverage.get("match_records"),
        "match_lines": coverage.get("match_lines"),
        "evidence_returned": coverage.get("evidence_returned"),
        "ranges": [
            [item.get("start_line"), item.get("end_line")]
            for item in evidence
            if isinstance(item, dict)
        ],
    }


def _self_test_format_recovery() -> dict[str, object]:
    content = (
        "2026-09-03 12:00:00 ERROR request failed\n"
        "java.lang.NullPointerException\n"
        "    at Foo.java:123\n"
        "caused by timeout\n"
        "2026-09-03 12:00:01 INFO request ok\n"
        "done\n"
    )
    fd, raw_path = tempfile.mkstemp(prefix="tracecite-local-recovery-", suffix=".log")
    os.close(fd)
    path = Path(raw_path)
    try:
        path.write_text(content, encoding="utf-8")
        segmenter = FormatSegmenter(
            start=r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})",
            timestamp_formats=["%Y-%m-%d %H:%M:%S"],
            multiline=True,
        )
        full_records = list(segmenter.segment_file(path))
        hits = scan_literal(path, "timeout")
        assert len(hits) == 1
        local = recover_record(path, hits[0], segmenter)
        expected = full_records[0]
        assert (local.start_line, local.end_line, local.text) == (
            expected.start_line,
            expected.end_line,
            expected.text,
        )
        return {
            "ok": True,
            "expected_range": [expected.start_line, expected.end_line],
            "local_range": [local.start_line, local.end_line],
        }
    finally:
        path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("file", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-evidence", type=int, default=20)
    args = parser.parse_args()

    source = args.file.expanduser().resolve()
    queries = (
        ("no_match", "statusCode error"),
        ("medium_match", "503"),
        ("high_match", "ts-route-service"),
    )
    payload: dict[str, object] = {
        "source": str(source),
        "bytes": source.stat().st_size,
        "format_local_recovery_self_test": _self_test_format_recovery(),
        "queries": [],
    }
    rows = []
    for label, query in queries:
        legacy, legacy_seconds = _timed(
            lambda q=query: _legacy_search(source, q, args.max_evidence)
        )
        candidate = candidate_first_search(source, query, max_evidence=args.max_evidence)
        parity = {
            "status": legacy.get("status") == candidate.get("status"),
            "match_records": legacy.get("match_records") == candidate.get("match_records"),
            "match_lines": legacy.get("match_lines") == candidate.get("match_lines"),
            "evidence_returned": legacy.get("evidence_returned") == candidate.get("evidence_returned"),
            "ranges": legacy.get("ranges") == candidate.get("ranges"),
        }
        rows.append(
            {
                "label": label,
                "query": query,
                "legacy": {**legacy, "seconds": round(legacy_seconds, 6)},
                "candidate_first": candidate,
                "parity": parity,
                "speedup": round(legacy_seconds / max(float(candidate["seconds"]), 1e-9), 3),
            }
        )
    payload["queries"] = rows
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
