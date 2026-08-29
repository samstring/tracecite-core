"""Bounded evidence-fidelity helpers for Agent-facing search projections.

Search is intentionally pointer-first, but an isolated structured leaf such as
``health: Unhealthy`` can invert meaning when its parent/sibling fields are
removed.  This module preserves a tiny, line-addressable neighborhood only for
search hits that look like structured ``key: value`` leaves.

The canonical Runtime result remains unchanged.  This is transport fidelity,
not diagnosis: no root-cause, entity, or causal interpretation is added.
"""

from __future__ import annotations

import copy
import hashlib
import os
import re
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Mapping


_STRUCTURED_LEAF_RE = re.compile(
    r"^\s*(?:[-*]\s*)?(?P<key>[A-Za-z_][A-Za-z0-9_.-]{1,63})\s*:\s*(?P<value>\S.*)$"
)

DEFAULT_STRUCTURED_CONTEXT_HITS = 8
DEFAULT_STRUCTURED_CONTEXT_BEFORE = 4
DEFAULT_STRUCTURED_CONTEXT_AFTER = 2
DEFAULT_STRUCTURED_CONTEXT_CHARS = 720


def _fingerprint(stat: os.stat_result) -> tuple[int, int, int, int, int]:
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)


def _structured_leaf(label: str) -> bool:
    first = next((line.strip() for line in str(label or "").splitlines() if line.strip()), "")
    if not first or len(first) > 512:
        return False
    match = _STRUCTURED_LEAF_RE.match(first)
    return bool(match and match.group("value").strip())


def _bounded_preview(
    source_name: str,
    rows: list[tuple[int, str]],
    *,
    max_chars: int,
) -> str:
    pieces: list[str] = []
    used = 0
    for number, text in rows:
        normalized = text.strip()
        if not normalized:
            continue
        piece = f"{source_name}:{number} {normalized}"
        extra = len(piece) + (3 if pieces else 0)
        if pieces and used + extra > max_chars:
            break
        if not pieces and len(piece) > max_chars:
            piece = piece[:max_chars]
            extra = len(piece)
        pieces.append(piece)
        used += extra
    return " | ".join(pieces)


def _scan_contexts(
    path: Path,
    targets: set[int],
    *,
    expected_sha256: str,
    before: int,
    after: int,
) -> dict[int, list[tuple[int, str]]]:
    """Return tiny neighborhoods for target lines from one stable source version."""

    if not targets:
        return {}
    digest = hashlib.sha256()
    contexts: dict[int, list[tuple[int, str]]] = {line: [] for line in targets}
    recent: deque[tuple[int, str]] = deque(maxlen=max(1, before + 1))
    pending: dict[int, int] = {}

    with path.open("rb") as binary:
        opened = os.fstat(binary.fileno())
        for block in iter(lambda: binary.read(1024 * 1024), b""):
            digest.update(block)
        if digest.hexdigest().lower() != expected_sha256.lower():
            return {}
        binary.seek(0)
        import io

        text = io.TextIOWrapper(binary, encoding="utf-8", errors="replace", newline=None)
        try:
            for number, raw in enumerate(text, start=1):
                line_text = raw.rstrip("\r\n")
                for target, remaining in list(pending.items()):
                    if remaining <= 0:
                        pending.pop(target, None)
                        continue
                    contexts[target].append((number, line_text))
                    remaining -= 1
                    if remaining <= 0:
                        pending.pop(target, None)
                    else:
                        pending[target] = remaining

                recent.append((number, line_text))
                if number in targets:
                    start = max(1, number - before)
                    contexts[number] = [row for row in recent if row[0] >= start]
                    if after > 0:
                        pending[number] = after

                if number > max(targets) + after and not pending:
                    break
            read_complete = os.fstat(binary.fileno())
            current_path = path.stat()
        finally:
            text.detach()

    if _fingerprint(opened) != _fingerprint(read_complete):
        return {}
    if _fingerprint(opened) != _fingerprint(current_path):
        return {}
    return contexts


def enrich_search_leaf_context(
    payload: Mapping[str, Any],
    *,
    max_hits: int = DEFAULT_STRUCTURED_CONTEXT_HITS,
    before: int = DEFAULT_STRUCTURED_CONTEXT_BEFORE,
    after: int = DEFAULT_STRUCTURED_CONTEXT_AFTER,
    max_preview_chars: int = DEFAULT_STRUCTURED_CONTEXT_CHARS,
) -> dict[str, Any]:
    """Preserve bounded parent/sibling context for structured search leaf hits.

    Only exact, line-addressable search evidence with a local source path and
    matching SHA-256 is eligible.  Ordinary prose/log hits are untouched.  Any
    integrity/read problem is a conservative no-op so an optional projection
    can never make canonical retrieval fail.
    """

    result = copy.deepcopy(dict(payload))
    if result.get("operation") != "search":
        return result
    if max_hits < 1 or before < 0 or after < 0 or max_preview_chars < 80:
        raise ValueError("structured context bounds are invalid")

    evidence = result.get("evidence")
    if not isinstance(evidence, list):
        return result

    candidates: list[tuple[int, dict[str, Any], Path, str, int]] = []
    for index, item in enumerate(evidence):
        if len(candidates) >= max_hits:
            break
        if not isinstance(item, Mapping):
            continue
        row = dict(item)
        start = row.get("start_line")
        end = row.get("end_line")
        if not isinstance(start, int) or isinstance(start, bool) or start < 1:
            continue
        if end not in (None, start):
            continue
        label = str(row.get("label") or "")
        if not _structured_leaf(label):
            continue
        source_path = str(row.get("source_path") or "").strip()
        digest = str(row.get("sha256") or "").strip()
        if not source_path or not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
            continue
        path = Path(source_path).expanduser().resolve()
        candidates.append((index, row, path, digest.lower(), start))

    if not candidates:
        return result

    grouped: dict[tuple[Path, str], set[int]] = defaultdict(set)
    for _index, _row, path, digest, line in candidates:
        grouped[(path, digest)].add(line)

    scanned: dict[tuple[Path, str], dict[int, list[tuple[int, str]]]] = {}
    for key, lines in grouped.items():
        path, digest = key
        try:
            if not path.is_file():
                continue
            scanned[key] = _scan_contexts(
                path,
                lines,
                expected_sha256=digest,
                before=before,
                after=after,
            )
        except (OSError, ValueError):
            continue

    enriched = 0
    output = [dict(item) if isinstance(item, Mapping) else item for item in evidence]
    for index, row, path, digest, line in candidates:
        rows = scanned.get((path, digest), {}).get(line) or []
        if len(rows) <= 1:
            continue
        preview = _bounded_preview(path.name, rows, max_chars=max_preview_chars)
        if not preview:
            continue
        original = str(row.get("label") or "").strip()
        updated = dict(row)
        updated["label"] = f"{original} || nearby: {preview}"
        output[index] = updated
        enriched += 1

    if not enriched:
        return result
    result["evidence"] = output
    coverage = dict(result.get("coverage") or {})
    coverage["structured_context_enriched"] = enriched
    result["coverage"] = coverage
    return result


__all__ = [
    "DEFAULT_STRUCTURED_CONTEXT_AFTER",
    "DEFAULT_STRUCTURED_CONTEXT_BEFORE",
    "DEFAULT_STRUCTURED_CONTEXT_CHARS",
    "DEFAULT_STRUCTURED_CONTEXT_HITS",
    "enrich_search_leaf_context",
]
