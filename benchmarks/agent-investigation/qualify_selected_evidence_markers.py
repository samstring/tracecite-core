from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
from pathlib import Path
from typing import Any

USER_AGENT = "TraceCite-Real-Online-Marker-Qualification/1"


def _download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=360) as response:
        return response.read()


def qualify(manifest_path: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    errors: list[str] = []

    for case in manifest.get("cases") or []:
        markers = [
            str(marker)
            for marker in case.get("evidence_markers") or []
            if str(marker).strip()
        ]
        if not markers:
            continue

        case_id = str(case.get("id") or "")
        min_hits = int(case.get("evidence_marker_min_hits") or len(markers))
        row: dict[str, Any] = {
            "id": case_id,
            "evidence_url": case.get("evidence_url"),
            "marker_count": len(markers),
            "min_hits": min_hits,
            "markers": [],
            "errors": [],
        }

        if min_hits < 1 or min_hits > len(markers):
            row["errors"].append(
                f"evidence_marker_min_hits must be between 1 and {len(markers)}"
            )
            rows.append(row)
            continue

        try:
            raw = _download(str(case.get("evidence_url") or ""))
            digest = hashlib.sha256(raw).hexdigest()
            expected = case.get("expected_sha256")
            if expected and digest != expected:
                row["errors"].append(
                    f"sha256 mismatch: expected {expected}, downloaded {digest}"
                )
            text = raw.decode("utf-8", errors="replace").casefold()
            hits = 0
            for marker in markers:
                hit = marker.casefold() in text
                hits += int(hit)
                row["markers"].append({"marker": marker, "hit": hit})
            row.update(
                {
                    "bytes": len(raw),
                    "mib": round(len(raw) / (1024 * 1024), 3),
                    "sha256": digest,
                    "marker_hits": hits,
                    "marker_recall": round(hits / len(markers), 4),
                }
            )
            if hits < min_hits:
                row["errors"].append(
                    f"selected evidence only matched {hits}/{len(markers)} markers; requires {min_hits}"
                )
        except Exception as exc:
            row["errors"].append(f"qualification failed: {type(exc).__name__}: {exc}")

        rows.append(row)

    if not rows:
        errors.append("manifest has no cases with evidence_markers")

    error_count = len(errors) + sum(len(row["errors"]) for row in rows)
    return {
        "schema_version": 1,
        "manifest": str(manifest_path),
        "qualified_case_count": len(rows),
        "error_count": error_count,
        "errors": errors,
        "cases": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    report = qualify(args.manifest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if report["error_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
