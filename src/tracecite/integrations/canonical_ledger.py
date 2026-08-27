"""Generic content-addressed storage for canonical TraceCite artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Mapping


LEDGER_SCHEMA_VERSION = 1
_ID_RE = re.compile(r"^[0-9a-f]{64}$")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _kind(payload: Mapping[str, Any], explicit: str | None) -> str:
    value = str(explicit or payload.get("kind") or payload.get("operation") or "artifact").strip().lower()
    if not value or len(value) > 128:
        raise ValueError("canonical artifact kind must be 1-128 characters")
    return value


class CanonicalLedger:
    """Persist immutable canonical results independent of one operation type."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()

    def _path(self, artifact_id: str) -> Path:
        if not _ID_RE.fullmatch(str(artifact_id)):
            raise ValueError("artifact_id must be a lowercase sha256 digest")
        return self.root / artifact_id[:2] / f"{artifact_id}.json"

    def store(self, payload: Mapping[str, Any], *, kind: str | None = None) -> str:
        if not isinstance(payload, Mapping):
            raise ValueError("canonical payload must be a mapping")
        canonical = dict(payload)
        resolved_kind = _kind(canonical, kind)
        identity = {"kind": resolved_kind, "payload": canonical}
        artifact_id = hashlib.sha256(canonical_json(identity).encode("utf-8")).hexdigest()
        record = {
            "schema_version": LEDGER_SCHEMA_VERSION,
            "artifact_id": artifact_id,
            "kind": resolved_kind,
            "payload": canonical,
        }
        encoded = canonical_json(record)
        path = self._path(artifact_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if path.read_text(encoding="utf-8") != encoded:
                raise ValueError(f"canonical ledger collision or corruption for {artifact_id}")
            return artifact_id
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{artifact_id}.", suffix=".tmp", dir=path.parent, text=True)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return artifact_id

    def load(self, artifact_id: str) -> dict[str, Any]:
        path = self._path(artifact_id)
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("schema_version") != LEDGER_SCHEMA_VERSION:
            raise ValueError("unsupported canonical ledger schema")
        if record.get("artifact_id") != artifact_id:
            raise ValueError("canonical ledger artifact id mismatch")
        payload = record.get("payload")
        if not isinstance(payload, Mapping):
            raise ValueError("canonical ledger record has no payload")
        expected = hashlib.sha256(
            canonical_json({"kind": record.get("kind"), "payload": dict(payload)}).encode("utf-8")
        ).hexdigest()
        if expected != artifact_id:
            raise ValueError("canonical ledger integrity verification failed")
        return {"kind": str(record.get("kind") or ""), "payload": dict(payload)}


__all__ = ["CanonicalLedger", "LEDGER_SCHEMA_VERSION", "canonical_json"]
