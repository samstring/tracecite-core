"""Bounded evidence-fidelity helpers for canonical Runtime search results.

Search remains pointer-first, but an isolated structured leaf such as
``health: Unhealthy`` can lose meaning when its parent/sibling fields are
removed.  This module preserves a tiny, line-addressable neighborhood only for
search hits that look like structured ``key: value`` leaves.

When that bounded neighborhood exposes a local-looking identifier near a scoped
entity, Runtime may also run the mechanical scoped-identity verifier against the
same stable source.  The verifier can surface an actionable Evidence gap, but
never supplies a diagnosis or root-cause claim.

This module is Runtime evidence work.  Integration projections must not invoke
it or reopen source files.
"""

from __future__ import annotations

import copy
import hashlib
import io
import os
import re
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Mapping

from .evidence_ambiguity import (
    scoped_identity_fanout_hints,
    verify_scoped_identity_gaps,
)


_STRUCTURED_LEAF_RE = re.compile(
    r"^\s*(?:[-*]\s*)?(?P<key>[A-Za-z_][A-Za-z0-9_.-]{1,63})\s*:\s*(?P<value>\S.*)$"
)

DEFAULT_STRUCTURED_CONTEXT_HITS = 8
DEFAULT_STRUCTURED_CONTEXT_BEFORE = 4
DEFAULT_STRUCTURED_CONTEXT_AFTER = 2
DEFAULT_STRUCTURED_CONTEXT_CHARS = 720
DEFAULT_SEARCH_IDENTITY_SOURCES = 2
DEFAULT_SEARCH_IDENTITY_VERIFICATIONS = 2


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


def _context_text(
    contexts: Mapping[int, list[tuple[int, str]]],
    target_lines: set[int],
) -> str:
    """Reconstruct de-duplicated raw context for evidence-integrity checks."""

    rows: dict[int, str] = {}
    for target in sorted(target_lines):
        for number, text in contexts.get(target) or []:
            rows.setdefault(number, text)
    return "\n".join(rows[number] for number in sorted(rows))


def _compact_identity_verification(item: Mapping[str, Any]) -> dict[str, Any]:
    """Keep only fields that can change an Agent's next correlation action."""

    def compact_entities(values: Any) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for row in values or []:
            if not isinstance(row, Mapping):
                continue
            refs = row.get("references") or []
            result.append(
                {
                    "entity": row.get("entity"),
                    "scope": row.get("scope"),
                    "references": list(refs)[:2],
                }
            )
        return result[:6]

    return {
        "kind": item.get("kind"),
        "identifier_key": item.get("identifier_key"),
        "identifier_value": item.get("identifier_value"),
        "status": item.get("status"),
        "source": item.get("source"),
        "entity_count_observed": item.get("entity_count_observed"),
        "entities": compact_entities(item.get("entities")),
        "sibling_entity_count_observed": item.get("sibling_entity_count_observed"),
        "sibling_entities": compact_entities(item.get("sibling_entities")),
        "finding": item.get("finding"),
        "correlation_requirement": item.get("correlation_requirement"),
        "causal_note": item.get("causal_note"),
    }


def _gap_from_verification(item: Mapping[str, Any]) -> dict[str, Any] | None:
    status = str(item.get("status") or "")
    if status == "multiple_scoped_entities_observed":
        return None
    identifier = str(item.get("identifier_value") or "").strip()
    key = str(item.get("identifier_key") or "").strip()
    if not identifier or not key:
        return None
    return {
        "kind": "scope_uniqueness_unverified",
        "detail": (
            f"{key}={identifier} is visible inside a scoped entity, but its uniqueness "
            "across the relevant identity domain is not established."
        ),
        "actionable": True,
        "identifier_key": key,
        "identifier_value": identifier,
        "source": item.get("source"),
        "recommended_action": {
            "operation": "search",
            "query": identifier,
            "purpose": "verify_identifier_uniqueness_across_scopes",
        },
    }


def _append_unique_gap(result: dict[str, Any], gap: Mapping[str, Any]) -> None:
    rows = [dict(item) for item in result.get("missing_evidence") or [] if isinstance(item, Mapping)]
    identity = (
        str(gap.get("kind") or ""),
        str(gap.get("identifier_key") or ""),
        str(gap.get("identifier_value") or ""),
        str(gap.get("source") or ""),
    )
    for item in rows:
        current = (
            str(item.get("kind") or ""),
            str(item.get("identifier_key") or ""),
            str(item.get("identifier_value") or ""),
            str(item.get("source") or ""),
        )
        if current == identity:
            return
    rows.append(dict(gap))
    result["missing_evidence"] = rows


def _append_next_query(result: dict[str, Any], query: str) -> None:
    value = str(query or "").strip()
    if not value:
        return
    rows = [str(item) for item in result.get("next_queries") or [] if str(item).strip()]
    if value not in rows:
        rows.append(value)
    result["next_queries"] = rows


def _attach_search_identity_integrity(
    result: dict[str, Any],
    *,
    scanned: Mapping[tuple[Path, str], Mapping[int, list[tuple[int, str]]]],
    grouped: Mapping[tuple[Path, str], set[int]],
) -> None:
    """Attach same-turn scoped-ID evidence gaps discovered in enriched search context."""

    integrity_rows: list[dict[str, Any]] = []
    for source_index, (key, target_lines) in enumerate(grouped.items()):
        if source_index >= DEFAULT_SEARCH_IDENTITY_SOURCES:
            break
        path, digest = key
        contexts = scanned.get(key) or {}
        visible_text = _context_text(contexts, target_lines)
        if not visible_text:
            continue
        hints = [
            item
            for item in scoped_identity_fanout_hints(visible_text)
            if item.get("kind") == "scope_uniqueness_unverified"
        ]
        if not hints:
            continue
        try:
            verified = verify_scoped_identity_gaps(
                path,
                visible_text,
                expected_sha256=digest,
                limit=DEFAULT_SEARCH_IDENTITY_VERIFICATIONS,
                entity_limit=6,
                reference_limit=2,
            )
        except (OSError, ValueError):
            verified = []
        compact_verified = [
            _compact_identity_verification(item)
            for item in verified[:DEFAULT_SEARCH_IDENTITY_VERIFICATIONS]
        ]
        integrity_rows.append(
            {
                "source": path.name,
                "scoped_identity_hints": hints[:DEFAULT_SEARCH_IDENTITY_VERIFICATIONS],
                "identity_verification": compact_verified,
            }
        )

        if compact_verified:
            for item in compact_verified:
                gap = _gap_from_verification(item)
                if gap is not None:
                    _append_unique_gap(result, gap)
                    _append_next_query(result, str(item.get("identifier_value") or ""))
        else:
            for hint in hints[:DEFAULT_SEARCH_IDENTITY_VERIFICATIONS]:
                identifier = str(hint.get("identifier_value") or "").strip()
                key_name = str(hint.get("identifier_key") or "").strip()
                if not identifier or not key_name:
                    continue
                _append_unique_gap(
                    result,
                    {
                        "kind": "scope_uniqueness_unverified",
                        "detail": (
                            f"{key_name}={identifier} is visible inside a scoped entity, but "
                            "the stable source could not establish its uniqueness."
                        ),
                        "actionable": True,
                        "identifier_key": key_name,
                        "identifier_value": identifier,
                        "source": path.name,
                        "recommended_action": dict(hint.get("recommended_action") or {}),
                    },
                )
                _append_next_query(result, identifier)

    if not integrity_rows:
        return
    data = dict(result.get("data") or {})
    data["evidence_integrity"] = {
        "scoped_identity": integrity_rows,
        "note": (
            "Evidence-integrity navigation only: a local identifier appears inside a scoped "
            "entity. Verify whether the identifier is unique across relevant sibling scopes "
            "before using identifier-only correlation. Sibling fan-out is not proof of reuse "
            "and does not by itself identify a root cause."
        ),
    }
    result["data"] = data


def enrich_search_leaf_context(
    payload: Mapping[str, Any],
    *,
    max_hits: int = DEFAULT_STRUCTURED_CONTEXT_HITS,
    before: int = DEFAULT_STRUCTURED_CONTEXT_BEFORE,
    after: int = DEFAULT_STRUCTURED_CONTEXT_AFTER,
    max_preview_chars: int = DEFAULT_STRUCTURED_CONTEXT_CHARS,
) -> dict[str, Any]:
    """Preserve bounded parent/sibling context for canonical search leaf hits.

    Only exact, line-addressable search evidence with a local source path and
    matching SHA-256 is eligible. Ordinary prose/log hits are untouched. Any
    integrity/read problem is a conservative no-op so evidence-fidelity work
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
    _attach_search_identity_integrity(result, scanned=scanned, grouped=grouped)
    return result


__all__ = [
    "DEFAULT_SEARCH_IDENTITY_SOURCES",
    "DEFAULT_SEARCH_IDENTITY_VERIFICATIONS",
    "DEFAULT_STRUCTURED_CONTEXT_AFTER",
    "DEFAULT_STRUCTURED_CONTEXT_BEFORE",
    "DEFAULT_STRUCTURED_CONTEXT_CHARS",
    "DEFAULT_STRUCTURED_CONTEXT_HITS",
    "enrich_search_leaf_context",
]
