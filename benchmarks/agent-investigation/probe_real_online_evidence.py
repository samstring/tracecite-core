from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import urllib.request
import zipfile
from pathlib import Path
from typing import Any


def _download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "TraceCite-Real-Evidence-Probe/1"})
    with urllib.request.urlopen(request, timeout=360) as response:
        return response.read()


def _probe_text(payload: bytes, needles: list[str]) -> dict[str, Any]:
    text = payload.decode("utf-8", errors="replace")
    lines = text.splitlines()
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
        "bytes": len(payload),
        "mib": round(len(payload) / (1024 * 1024), 3),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "line_count": len(lines),
        "needles": results,
    }


def _probe_zip(raw: bytes, needles: list[str]) -> dict[str, Any]:
    members: list[dict[str, Any]] = []
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            payload = archive.read(info)
            row = {
                "name": info.filename,
                "compressed_bytes": info.compress_size,
                **_probe_text(payload, needles),
            }
            members.append(row)
    return {
        "archive_kind": "zip",
        "member_count": len(members),
        "members": members,
    }


def _probe_gzip(raw: bytes, needles: list[str]) -> dict[str, Any]:
    payload = gzip.decompress(raw)
    return {
        "archive_kind": "gzip",
        "member_count": 1,
        "members": [{"name": "<gzip-payload>", **_probe_text(payload, needles)}],
    }


def _probe_case(case: dict[str, Any]) -> dict[str, Any]:
    raw = _download(str(case["url"]))
    needles = [str(item) for item in case.get("needles", []) if str(item)]
    archive_kind = str(case.get("archive_kind") or "").lower()
    row: dict[str, Any] = {
        "id": case["id"],
        "url": case["url"],
        "bytes": len(raw),
        "mib": round(len(raw) / (1024 * 1024), 3),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
    if archive_kind == "zip":
        row.update(_probe_zip(raw, needles))
    elif archive_kind in {"gz", "gzip"}:
        row.update(_probe_gzip(raw, needles))
    else:
        row.update(_probe_text(raw, needles))
    return row


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
