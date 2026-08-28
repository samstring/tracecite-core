from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
from pathlib import Path
from typing import Any


def _download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "TraceCite-Real-Evidence-Probe/1"})
    with urllib.request.urlopen(request, timeout=360) as response:
        return response.read()


def _probe_case(case: dict[str, Any]) -> dict[str, Any]:
    raw = _download(str(case["url"]))
    text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()
    needles = [str(item) for item in case.get("needles", []) if str(item)]
    results = []
    for needle in needles:
        folded = needle.casefold()
        matches = []
        count = 0
        for line_no, line in enumerate(lines, 1):
            if folded not in line.casefold():
                continue
            count += 1
            if len(matches) < 8:
                matches.append({"line": line_no, "text": line[:800]})
        results.append({"needle": needle, "count": count, "samples": matches})
    return {
        "id": case["id"],
        "url": case["url"],
        "bytes": len(raw),
        "mib": round(len(raw) / (1024 * 1024), 3),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "line_count": len(lines),
        "needles": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe natural public evidence candidates without selecting them")
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    rows = []
    errors = []
    for case in spec.get("candidates", []):
        try:
            rows.append(_probe_case(case))
        except Exception as exc:  # keep probing independent candidates
            errors.append({"id": case.get("id"), "url": case.get("url"), "error": str(exc)})

    payload = {
        "schema_version": 1,
        "candidate_count": len(spec.get("candidates", [])),
        "probed": len(rows),
        "errors": errors,
        "candidates": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
