"""Content-addressed evidence memory for bounded Agent adapters."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping

from tracecite.runtime.tools import expand


LEDGER_SCHEMA_VERSION = 1
_RESULT_ID = re.compile(r"^[0-9a-f]{64}$")


def _canonical_json(payload: Any) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _result_digest(result: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(result).encode("utf-8")).hexdigest()


def _evidence_ref(uri: str) -> str:
    marker = uri.find("#")
    return uri[marker:] if marker >= 0 else uri


class EvidenceLedger:
    """Persist canonical search results outside the model conversation.

    Entries are immutable and content-addressed. Agent-facing messages only
    need the result identifier; the complete canonical Result remains
    available for deterministic expansion and audit.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()

    def _entry_path(self, result_id: str) -> Path:
        if not _RESULT_ID.fullmatch(result_id):
            raise ValueError("result_id must be a 64-character lowercase SHA-256 digest")
        return self.root / result_id[:2] / f"{result_id}.json"

    def store(self, result: Mapping[str, Any]) -> str:
        """Store one canonical search Result and return its content identifier."""

        canonical = dict(result)
        if canonical.get("operation") != "search":
            raise ValueError("EvidenceLedger only stores search Results")
        if canonical.get("status") not in {"ok", "no_match"}:
            raise ValueError("only successful search Results can be stored")

        result_id = _result_digest(canonical)
        path = self._entry_path(result_id)
        record = {
            "schema_version": LEDGER_SCHEMA_VERSION,
            "result_id": result_id,
            "result": canonical,
        }
        encoded = _canonical_json(record)

        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            existing = path.read_text(encoding="utf-8")
            if existing != encoded:
                raise ValueError(f"ledger collision or corruption for {result_id}")
            return result_id

        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{result_id}.",
            suffix=".tmp",
            dir=path.parent,
            text=True,
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()
        return result_id

    def load(self, result_id: str) -> dict[str, Any]:
        """Load and integrity-check one canonical search Result."""

        path = self._entry_path(result_id)
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("schema_version") != LEDGER_SCHEMA_VERSION:
            raise ValueError("unsupported EvidenceLedger schema version")
        if record.get("result_id") != result_id:
            raise ValueError("EvidenceLedger result_id mismatch")
        result = record.get("result")
        if not isinstance(result, Mapping):
            raise ValueError("EvidenceLedger entry has no canonical Result")
        canonical = dict(result)
        if _result_digest(canonical) != result_id:
            raise ValueError("EvidenceLedger entry failed content verification")
        return canonical


def expand_many(
    ledger: EvidenceLedger,
    result_id: str,
    refs: Iterable[str],
    *,
    before: int = 3,
    after: int = 3,
    max_chars: int = 20_000,
) -> dict[str, Any]:
    """Expand several pointers from one immutable ledger result.

    ``max_chars`` bounds aggregate returned context text. Missing or failed
    references remain explicit so an Agent cannot mistake partial expansion
    for complete coverage.
    """

    if max_chars <= 0:
        raise ValueError("max_chars must be greater than zero")
    requested = list(dict.fromkeys(str(ref) for ref in refs if str(ref)))
    if not requested:
        raise ValueError("at least one evidence ref is required")

    search_result = ledger.load(result_id)
    pointers = [
        dict(item)
        for item in search_result.get("evidence") or []
        if isinstance(item, Mapping)
    ]
    index: dict[str, dict[str, Any]] = {}
    for pointer in pointers:
        uri = str(pointer.get("uri") or "")
        if uri:
            index[uri] = pointer
            index[_evidence_ref(uri)] = pointer

    missing: list[str] = []
    failed: list[str] = []
    resolved: list[dict[str, Any]] = []
    before = max(0, before)
    after = max(0, after)
    for ref in requested:
        pointer = index.get(ref)
        if pointer is None:
            missing.append(ref)
            continue
        source_path = str(pointer.get("source_path") or "")
        digest = str(pointer.get("sha256") or "")
        start_line = int(pointer.get("start_line") or 0)
        end_line = int(pointer.get("end_line") or start_line)
        if not source_path or not digest or start_line <= 0 or end_line < start_line:
            failed.append(ref)
            continue
        resolved.append(
            {
                "ref": _evidence_ref(str(pointer.get("uri") or ref)),
                "source_path": source_path,
                "sha256": digest,
                "start": start_line,
                "end": end_line,
                "window_start": max(1, start_line - before),
                "window_end": end_line + after,
            }
        )

    groups: list[dict[str, Any]] = []
    for item in sorted(
        resolved,
        key=lambda row: (
            row["source_path"],
            row["sha256"],
            row["window_start"],
            row["window_end"],
        ),
    ):
        previous = groups[-1] if groups else None
        if (
            previous is not None
            and previous["source_path"] == item["source_path"]
            and previous["sha256"] == item["sha256"]
            and item["window_start"] <= previous["window_end"] + 1
        ):
            previous["members"].append(item)
            previous["selected_start"] = min(previous["selected_start"], item["start"])
            previous["selected_end"] = max(previous["selected_end"], item["end"])
            previous["window_end"] = max(previous["window_end"], item["window_end"])
        else:
            groups.append(
                {
                    "source_path": item["source_path"],
                    "sha256": item["sha256"],
                    "selected_start": item["start"],
                    "selected_end": item["end"],
                    "window_end": item["window_end"],
                    "members": [item],
                }
            )

    contexts: list[dict[str, Any]] = []
    context_by_ref: dict[str, str] = {}
    remaining = max_chars
    for group in groups:
        group_refs = [str(item["ref"]) for item in group["members"]]
        if remaining <= 0:
            failed.extend(ref for ref in group_refs if ref not in failed)
            continue
        expanded = expand(
            group["source_path"],
            group["selected_start"],
            end_line=group["selected_end"],
            before=before,
            after=after,
            expected_sha256=group["sha256"],
            max_chars=remaining,
            cache=False,
        )
        if expanded.get("status") != "ok":
            failed.extend(ref for ref in group_refs if ref not in failed)
            continue
        text = str((expanded.get("data") or {}).get("text") or "")
        coverage = dict(expanded.get("coverage") or {})
        context_id = f"c{len(contexts) + 1}"
        contexts.append(
            {
                "id": context_id,
                "lines": [
                    coverage.get("context_start_line"),
                    coverage.get("context_end_line"),
                ],
                "text": text,
                "truncated": bool(coverage.get("truncated", False)),
            }
        )
        for ref in group_refs:
            context_by_ref[ref] = context_id
        remaining -= len(text)

    evidence_rows = [
        [item["ref"], item["start"], item["end"], context_by_ref[item["ref"]]]
        for item in resolved
        if item["ref"] in context_by_ref
    ]
    any_context_truncated = any(context["truncated"] for context in contexts)

    warnings: list[str] = []
    if missing:
        warnings.append("some refs were not present in the immutable search result")
    if failed:
        warnings.append("some refs could not be expanded within the current budget")
    if any_context_truncated:
        warnings.append("some merged contexts were truncated; rerun those refs more narrowly")
    complete = bool(evidence_rows) and not missing and not failed and not any_context_truncated
    payload: dict[str, Any] = {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "operation": "expand_many",
        "status": "ok" if evidence_rows else "error",
        "outcome": "supported" if complete else "unknown",
        "result_id": result_id,
        "evidence": {
            "columns": ["ref", "start", "end", "context"],
            "rows": evidence_rows,
        },
        "contexts": contexts,
        "coverage": {
            "requested": len(requested),
            "returned": len(evidence_rows),
            "contexts": len(contexts),
            "merged_contexts": max(0, len(evidence_rows) - len(contexts)),
            "missing_refs": missing,
            "failed_refs": failed,
            "text_chars": sum(len(context["text"]) for context in contexts),
            "truncated": bool(missing or failed or any_context_truncated),
        },
    }
    if warnings:
        payload["warnings"] = warnings
    return payload


__all__ = ["EvidenceLedger", "LEDGER_SCHEMA_VERSION", "expand_many"]
