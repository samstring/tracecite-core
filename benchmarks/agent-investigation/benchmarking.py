from __future__ import annotations

import gzip
import hashlib
import io
import json
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Mapping


USER_AGENT = "TraceCite-Offline-Retrieval-Eval/1"


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _download(url: str, target: Path) -> tuple[int, str]:
    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    digest = hashlib.sha256()
    size = 0
    with urllib.request.urlopen(request, timeout=120) as response, target.open("wb") as handle:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)
            digest.update(chunk)
            size += len(chunk)
    return size, digest.hexdigest()


def _extract_payload(source_path: Path, extract: Mapping[str, Any]) -> bytes:
    raw = source_path.read_bytes()
    kind = str(extract.get("kind") or "")
    if kind == "gzip":
        return gzip.decompress(raw)
    if kind == "zip":
        member = str(extract.get("member") or "")
        if not member:
            raise ValueError("zip extraction requires member")
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            return archive.read(member)
    raise ValueError(f"unsupported extraction kind: {kind}")


def prepare_case(case_dir: Path, work_dir: Path) -> dict[str, Any]:
    """Download and verify a benchmark case's original public inputs.

    This helper is intentionally evidence-only: it reads case.json provenance,
    verifies source and extracted SHA-256 values, and never reads gold.json.
    """

    case_dir = case_dir.resolve()
    case = _read_json(case_dir / "case.json")
    case_id = str(case.get("id") or case_dir.name)
    inputs = case.get("inputs")
    if not isinstance(inputs, list) or not inputs:
        raise ValueError(f"{case_id}: case inputs must be a non-empty list")

    case_root = work_dir.resolve() / case_id
    input_root = case_root / "inputs"
    source_root = case_root / ".sources"
    prepared: list[dict[str, Any]] = []

    for index, source in enumerate(inputs):
        if not isinstance(source, Mapping):
            raise ValueError(f"{case_id}: inputs[{index}] must be an object")
        source_id = str(source.get("id") or f"input-{index}")
        url = str(source.get("url") or "")
        filename = str(source.get("filename") or "")
        expected_source_sha = str(source.get("sha256") or "")
        if not url or not filename or len(expected_source_sha) != 64:
            raise ValueError(f"{case_id}: invalid source metadata for {source_id}")

        target = input_root / filename
        extract = source.get("extract")
        download_target = source_root / f"{source_id}.download" if isinstance(extract, Mapping) else target
        source_size, source_sha = _download(url, download_target)
        if source_sha != expected_source_sha:
            download_target.unlink(missing_ok=True)
            raise ValueError(
                f"{case_id}/{source_id}: source sha256 mismatch: expected {expected_source_sha}, got {source_sha}"
            )

        payload_size = source_size
        payload_sha = source_sha
        extraction: dict[str, Any] | None = None
        if isinstance(extract, Mapping):
            payload = _extract_payload(download_target, extract)
            payload_sha = hashlib.sha256(payload).hexdigest()
            expected_payload_sha = str(extract.get("sha256") or "")
            if payload_sha != expected_payload_sha:
                download_target.unlink(missing_ok=True)
                raise ValueError(
                    f"{case_id}/{source_id}: extracted sha256 mismatch: expected {expected_payload_sha}, got {payload_sha}"
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            payload_size = len(payload)
            extraction = {"kind": str(extract.get("kind") or "")}
            if extract.get("member") is not None:
                extraction["member"] = str(extract["member"])
            download_target.unlink(missing_ok=True)

        row: dict[str, Any] = {
            "id": source_id,
            "path": str(target.resolve()),
            "bytes": payload_size,
            "sha256": payload_sha,
            "source_url": url,
            "source_bytes": source_size,
            "source_sha256": source_sha,
        }
        if extraction is not None:
            row["extract"] = extraction
        prepared.append(row)

    manifest = {
        "schema_version": 1,
        "case_id": case_id,
        "inputs": prepared,
    }
    case_root.mkdir(parents=True, exist_ok=True)
    manifest_path = case_root / "prepared.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"status": "ok", "case_id": case_id, "prepared": prepared, "manifest": str(manifest_path)}


__all__ = ["prepare_case"]
