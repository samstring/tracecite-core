from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from tracecite.runtime import tools as runtime_tools
from tracecite.runtime.candidate_search import candidate_first_literal_search
from tracecite_core.segmenter import build_segmenter, detect_segmenter_kind


def _timed(fn):
    start = time.perf_counter()
    value = fn()
    return value, time.perf_counter() - start


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


def _candidate_search(path: Path, query: str, max_evidence: int) -> dict[str, object]:
    kind = detect_segmenter_kind(path)
    result = candidate_first_literal_search(
        path,
        query,
        segmenter=build_segmenter(kind),
        max_evidence=max_evidence,
    )
    return {
        "segmenter": str(kind),
        "status": result.status,
        "match_records": result.match_records,
        "match_lines": result.match_lines,
        "evidence_returned": len(result.records),
        "ranges": [[record.start_line, record.end_line] for record in result.records],
        "physical_hit_lines": result.physical_hit_lines,
        "total_lines": result.total_lines,
        "scan_seconds": round(result.scan_seconds, 6),
        "recover_seconds": round(result.recover_seconds, 6),
        "seconds": round(result.scan_seconds + result.recover_seconds, 6),
    }


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
    rows = []
    for label, query in queries:
        legacy, legacy_seconds = _timed(
            lambda q=query: _legacy_search(source, q, args.max_evidence)
        )
        candidate = _candidate_search(source, query, args.max_evidence)
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
                "speedup": round(
                    legacy_seconds / max(float(candidate["seconds"]), 1e-9), 3
                ),
            }
        )

    payload = {
        "source": str(source),
        "bytes": source.stat().st_size,
        "queries": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
