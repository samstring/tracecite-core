from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
import time
from pathlib import Path

from tracecite.runtime import tools as runtime_tools
from tracecite_core.matcher import Matcher
from tracecite_core.segmenter import build_segmenter, detect_segmenter_kind
from tracecite_core.text_filter import _count_lines, _extract_record_tokens, record_timestamp, reference_datetime


QUERIES = (
    ("no_match", "statusCode error"),
    ("medium_match", "503"),
    ("high_match", "ts-route-service"),
)


def timed(fn):
    start = time.perf_counter()
    value = fn()
    return value, time.perf_counter() - start


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def profile_scan(path: Path, query: str) -> dict[str, object]:
    kind = detect_segmenter_kind(path)
    seg = build_segmenter(kind)
    matcher = Matcher(re.escape(query))
    ref = reference_datetime(path, segmenter=seg)

    records = 0
    matched = 0
    unmatched = 0
    match_seconds = 0.0
    unmatched_token_seconds = 0.0
    timestamp_seconds = 0.0
    serialize_write_seconds = 0.0
    token_occurrences = 0
    bytes_written = 0

    fd, raw_path = tempfile.mkstemp(prefix="tracecite-profile-records-", suffix=".jsonl")
    os.close(fd)
    out_path = Path(raw_path)
    scan_start = time.perf_counter()
    try:
        with out_path.open("w", encoding="utf-8") as out:
            for record in seg.segment_file(path, encoding="utf-8"):
                records += 1
                t0 = time.perf_counter()
                is_match, term, terms_hit, matched_by = matcher.match_with_components(record.text, ())
                match_seconds += time.perf_counter() - t0

                if not is_match:
                    unmatched += 1
                    t0 = time.perf_counter()
                    tokens = _extract_record_tokens(
                        record.text,
                        header_re=seg.header_strip_re,
                        token_re=seg.token_re,
                    )
                    unmatched_token_seconds += time.perf_counter() - t0
                    token_occurrences += len(tokens)
                    continue

                matched += 1
                t0 = time.perf_counter()
                ts = record_timestamp(record, ref=ref, segmenter=seg)
                timestamp_seconds += time.perf_counter() - t0

                t0 = time.perf_counter()
                row = {
                    "text": record.text if record.text.endswith("\n") else record.text + "\n",
                    "metadata": {
                        "start_line": record.start_line,
                        "end_line": record.end_line,
                        "term": term,
                        "terms": sorted(terms_hit),
                        "matched_by": list(matched_by),
                        "timestamp": ts.isoformat(timespec="milliseconds") if ts is not None else None,
                    },
                }
                encoded = json.dumps(row, ensure_ascii=False) + "\n"
                out.write(encoded)
                bytes_written += len(encoded.encode("utf-8"))
                serialize_write_seconds += time.perf_counter() - t0
    finally:
        scan_seconds = time.perf_counter() - scan_start
        out_path.unlink(missing_ok=True)

    measured = match_seconds + unmatched_token_seconds + timestamp_seconds + serialize_write_seconds
    return {
        "segmenter": str(kind),
        "records": records,
        "matched": matched,
        "unmatched": unmatched,
        "token_occurrences": token_occurrences,
        "bytes_written": bytes_written,
        "scan_seconds": round(scan_seconds, 6),
        "match_seconds": round(match_seconds, 6),
        "unmatched_token_seconds": round(unmatched_token_seconds, 6),
        "timestamp_seconds": round(timestamp_seconds, 6),
        "serialize_write_seconds": round(serialize_write_seconds, 6),
        "segmentation_and_loop_seconds": round(max(0.0, scan_seconds - measured), 6),
    }


def profile_full_search(path: Path, query: str) -> dict[str, object]:
    start = time.perf_counter()
    result = runtime_tools.search(
        path,
        query,
        regex=False,
        snapshot=False,
        max_evidence=20,
        investigation_path=None,
        cache=False,
    )
    elapsed = time.perf_counter() - start
    coverage = result.get("coverage") or {}
    artifacts = result.get("artifacts") or []
    artifact_bytes: dict[str, int] = {}
    for item in artifacts:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "")
        raw = str(item.get("path") or "")
        if not role or not raw:
            continue
        p = Path(raw)
        if p.is_file():
            artifact_bytes[role] = p.stat().st_size
    return {
        "seconds": round(elapsed, 6),
        "status": result.get("status"),
        "match_records": coverage.get("match_records"),
        "match_lines": coverage.get("match_lines"),
        "evidence_returned": coverage.get("evidence_returned"),
        "evidence_truncated": coverage.get("evidence_truncated"),
        "artifact_bytes": artifact_bytes,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("file", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = args.file.expanduser().resolve()
    if not source.is_file():
        raise SystemExit(f"missing source: {source}")

    digest, sha_seconds = timed(lambda: sha256_file(source))
    lines, count_seconds = timed(lambda: _count_lines(source))

    copy_target = Path(tempfile.mktemp(prefix="tracecite-profile-copy-", suffix=source.suffix))
    _, copy_seconds = timed(lambda: shutil.copy2(source, copy_target))
    copy_target.unlink(missing_ok=True)

    rows = []
    for label, query in QUERIES:
        scan = profile_scan(source, query)
        full = profile_full_search(source, query)
        rows.append({"label": label, "query": query, "scan_profile": scan, "full_search": full})

    payload = {
        "source": str(source),
        "bytes": source.stat().st_size,
        "lines": lines,
        "sha256": digest,
        "one_pass_costs": {
            "sha256_seconds": round(sha_seconds, 6),
            "count_lines_seconds": round(count_seconds, 6),
            "copy2_seconds": round(copy_seconds, 6),
        },
        "queries": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
