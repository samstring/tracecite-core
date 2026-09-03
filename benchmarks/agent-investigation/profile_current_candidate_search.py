from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from tracecite.runtime import tools as runtime_tools

QUERIES = (
    ("no_match", "statusCode error"),
    ("medium_match", "503"),
    ("high_match", "ts-route-service"),
)


def run_search(path: Path, query: str) -> dict[str, object]:
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
    return {
        "query": query,
        "seconds": round(elapsed, 6),
        "status": result.get("status"),
        "match_records": coverage.get("match_records"),
        "match_lines": coverage.get("match_lines"),
        "evidence_returned": coverage.get("evidence_returned"),
        "evidence_truncated": coverage.get("evidence_truncated"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("file", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = args.file.expanduser().resolve()
    payload = {
        "source": str(source),
        "bytes": source.stat().st_size,
        "lines": sum(1 for _ in source.open("rb")),
        "queries": [
            {"label": label, **run_search(source, query)}
            for label, query in QUERIES
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
