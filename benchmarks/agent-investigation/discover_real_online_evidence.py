#!/usr/bin/env python3
"""Discover natural text-log evidence in the same public CI run as scale cases.

This script is deliberately discovery-only. It never rewrites, concatenates, pads,
truncates, or auto-selects benchmark evidence. The benchmark manifest must still
pin the exact original public object that a case uses.
"""

from __future__ import annotations

import argparse
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

MIB = 1024 * 1024
DEFAULT_MANIFEST = Path("benchmarks/agent-investigation/real-online-scale-10.json")
TEXT_LOG_SUFFIXES = (".log", ".txt", ".out")
BUILD_ID_RE = re.compile(r"^\d{16,}$")


def classify_size(size: int) -> str:
    if size < MIB:
        return "small"
    if size <= 10 * MIB:
        return "medium_1_10m"
    if size <= 50 * MIB:
        return "large_10_50m"
    return "over_50m"


def _bucket_object_from_url(url: str) -> tuple[str, str] | None:
    parsed = urllib.parse.urlparse(url)
    if parsed.netloc == "prow.k8s.io":
        parts = [part for part in parsed.path.split("/") if part]
        try:
            marker = parts.index("gs")
        except ValueError:
            return None
        if marker < 1 or parts[marker - 1] != "view" or len(parts) <= marker + 2:
            return None
        return parts[marker + 1], "/".join(parts[marker + 2 :])

    if parsed.netloc == "storage.googleapis.com":
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) < 2:
            return None
        return parts[0], "/".join(parts[1:])

    return None


def derive_run_prefix(case: dict[str, Any]) -> tuple[str, str] | None:
    """Return (bucket, run-prefix) ending immediately after the Prow build id."""
    for key in ("evidence_view", "evidence_url"):
        raw = str(case.get(key) or "")
        parsed = _bucket_object_from_url(raw)
        if not parsed:
            continue
        bucket, object_name = parsed
        parts = [part for part in object_name.split("/") if part]
        for index, part in enumerate(parts):
            if BUILD_ID_RE.fullmatch(part):
                return bucket, "/".join(parts[: index + 1]) + "/"
    return None


def _read_json(url: str, timeout: int = 60) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "tracecite-real-online-evidence-discovery/1"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def list_run_objects(bucket: str, prefix: str, *, max_pages: int = 30) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    page_token: str | None = None

    for _ in range(max_pages):
        params = {
            "prefix": prefix,
            "maxResults": "1000",
            "fields": "items(name,size),nextPageToken",
        }
        if page_token:
            params["pageToken"] = page_token
        endpoint = (
            "https://storage.googleapis.com/storage/v1/b/"
            + urllib.parse.quote(bucket, safe="")
            + "/o?"
            + urllib.parse.urlencode(params)
        )
        payload = _read_json(endpoint)
        objects.extend(payload.get("items") or [])
        page_token = payload.get("nextPageToken")
        if not page_token:
            return objects

    raise RuntimeError(
        f"object listing exceeded {max_pages} pages for gs://{bucket}/{prefix}; "
        "refusing to silently return a partial discovery result"
    )


def public_object_url(bucket: str, name: str) -> str:
    return (
        "https://storage.googleapis.com/"
        + urllib.parse.quote(bucket, safe="")
        + "/"
        + urllib.parse.quote(name, safe="/")
    )


def summarize_candidates(bucket: str, prefix: str, objects: list[dict[str, Any]]) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for item in objects:
        name = str(item.get("name") or "")
        if not name.lower().endswith(TEXT_LOG_SUFFIXES):
            continue
        try:
            size = int(item.get("size") or 0)
        except (TypeError, ValueError):
            continue
        if size <= 0:
            continue
        candidates.append(
            {
                "name": name,
                "bytes": size,
                "mib": round(size / MIB, 3),
                "size_bucket": classify_size(size),
                "url": public_object_url(bucket, name),
            }
        )

    candidates.sort(key=lambda row: (-int(row["bytes"]), str(row["name"])))
    grouped: dict[str, list[dict[str, Any]]] = {
        "small": [],
        "medium_1_10m": [],
        "large_10_50m": [],
        "over_50m": [],
    }
    for candidate in candidates:
        grouped[str(candidate["size_bucket"])].append(candidate)

    # Keep the discovery artifact reviewable while retaining every medium/large
    # candidate that matters for benchmark selection. Small and >50 MiB lists are
    # diagnostic only and are capped.
    grouped["small"] = grouped["small"][:20]
    grouped["over_50m"] = grouped["over_50m"][:20]

    return {
        "bucket": bucket,
        "run_prefix": prefix,
        "listed_object_count": len(objects),
        "text_log_count": len(candidates),
        "candidate_counts": {
            key: len([row for row in candidates if row["size_bucket"] == key])
            for key in grouped
        },
        "candidates": grouped,
    }


def discover(manifest: dict[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for case in manifest.get("cases") or []:
        case_id = str(case.get("id") or "")
        row: dict[str, Any] = {
            "id": case_id,
            "purpose": case.get("purpose"),
            "selected_evidence_url": case.get("evidence_url"),
            "errors": [],
        }
        run = derive_run_prefix(case)
        if not run:
            row["status"] = "not_applicable"
            row["note"] = "case is not backed by a discoverable Prow/GCS run"
            rows.append(row)
            continue

        bucket, prefix = run
        try:
            objects = list_run_objects(bucket, prefix)
            row.update(summarize_candidates(bucket, prefix, objects))
            row["status"] = "ok"
        except Exception as exc:  # discovery should preserve per-case diagnostics
            row["status"] = "error"
            row["errors"].append(str(exc))
        rows.append(row)

    medium_case_count = sum(
        1
        for row in rows
        if row.get("status") == "ok"
        and int((row.get("candidate_counts") or {}).get("medium_1_10m") or 0) > 0
    )
    large_case_count = sum(
        1
        for row in rows
        if row.get("status") == "ok"
        and int((row.get("candidate_counts") or {}).get("large_10_50m") or 0) > 0
    )
    return {
        "schema_version": 1,
        "selection_policy": {
            "auto_select": False,
            "synthetic_padding": False,
            "concatenation": False,
            "truncation_for_size": False,
            "rule": "Only natural original .log/.txt/.out objects from the same public incident run are reported. The manifest must explicitly pin the chosen evidence object.",
        },
        "case_count": len(rows),
        "cases_with_medium_candidates": medium_case_count,
        "cases_with_large_candidates": large_case_count,
        "discovery_error_count": sum(1 for row in rows if row.get("status") == "error"),
        "cases": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    report = discover(manifest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
