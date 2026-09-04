"""Deterministic navigation index for high-cardinality text searches.

The index describes the complete matched-record space without deciding which
match is important.  When a search has only a few matches the normal Evidence
pointers remain visible.  Larger match spaces are projected as rule counts and
line locators so the Agent can choose what to materialize next.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping


DEFAULT_INLINE_EVIDENCE_THRESHOLD = 5
DEFAULT_SAMPLE_LINES = 5


def _matched_records_path(canonical: Mapping[str, Any]) -> Path | None:
    for item in canonical.get("artifacts") or []:
        if not isinstance(item, Mapping) or item.get("role") != "matched_records":
            continue
        value = str(item.get("path") or "").strip()
        if value:
            return Path(value)
    return None


def _split_top_level_alternatives(pattern: str) -> list[str]:
    """Conservatively split only top-level regex alternation branches."""

    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    in_class = False
    escaped = False
    for ch in pattern:
        if escaped:
            buf.append(ch)
            escaped = False
            continue
        if ch == "\\":
            buf.append(ch)
            escaped = True
            continue
        if ch == "[" and not in_class:
            in_class = True
            buf.append(ch)
            continue
        if ch == "]" and in_class:
            in_class = False
            buf.append(ch)
            continue
        if not in_class:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth < 0:
                    return [pattern]
            elif ch == "|" and depth == 0:
                part = "".join(buf).strip()
                if not part:
                    return [pattern]
                parts.append(part)
                buf = []
                continue
        buf.append(ch)
    if escaped or in_class or depth != 0:
        return [pattern]
    tail = "".join(buf).strip()
    if not tail:
        return [pattern]
    parts.append(tail)
    if len(parts) <= 1:
        return [pattern]
    try:
        for part in parts:
            re.compile(part)
    except re.error:
        return [pattern]
    return parts


def _rules(query: str, *, regex: bool) -> list[tuple[str, re.Pattern[str] | None]]:
    if not regex:
        return [(query, None)]
    parts = _split_top_level_alternatives(query)
    return [(part, re.compile(part)) for part in parts]


def _append_sample(samples: list[int], line: int, *, limit: int) -> None:
    if line in samples:
        return
    if len(samples) < limit:
        samples.append(line)
        return
    # Keep the earliest locators stable while making the final slot track the
    # latest occurrence.  This is navigation coverage, not relevance ranking.
    samples[-1] = line


def build_evidence_index(
    records_path: Path,
    *,
    query: str,
    regex: bool,
    source: str,
    total_matches: int,
    source_sha256: str = "",
    sample_lines: int = DEFAULT_SAMPLE_LINES,
) -> dict[str, Any] | None:
    """Build a complete rule-level index from the already-produced match artifact."""

    if sample_lines < 1 or not records_path.is_file():
        return None
    rules = _rules(query, regex=regex)
    stats = [
        {
            "rule": rule,
            "count": 0,
            "start_line": None,
            "end_line": None,
            "sample_lines": [],
        }
        for rule, _ in rules
    ]

    with records_path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            try:
                row = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, Mapping):
                continue
            metadata = row.get("metadata") or {}
            if not isinstance(metadata, Mapping):
                continue
            start = metadata.get("start_line")
            end = metadata.get("end_line")
            if not isinstance(start, int) or isinstance(start, bool) or start < 1:
                continue
            if not isinstance(end, int) or isinstance(end, bool) or end < start:
                end = start
            text = str(row.get("text") or "")

            for index, (rule, compiled) in enumerate(rules):
                matched = bool(compiled.search(text)) if compiled is not None else rule in text
                if not matched:
                    continue
                item = stats[index]
                item["count"] = int(item["count"]) + 1
                if item["start_line"] is None:
                    item["start_line"] = start
                item["end_line"] = end
                _append_sample(item["sample_lines"], start, limit=sample_lines)

    entries = [item for item in stats if int(item["count"]) > 0]
    if not entries:
        return None
    payload: dict[str, Any] = {
        "complete": True,
        "navigation_only": True,
        "source": Path(source).name,
        "query": query,
        "regex": bool(regex),
        "total_matches": int(total_matches),
        "entries": entries,
        "note": (
            "Complete rule-level match index; entries are locators, not Evidence. "
            "Choose a rule/line and materialize the referenced source range before citing it."
        ),
    }
    if source_sha256:
        payload["source_sha256"] = source_sha256
    return payload


def project_search_canonical(
    canonical: Mapping[str, Any],
    *,
    query: str,
    regex: bool,
    source: str,
    inline_threshold: int = DEFAULT_INLINE_EVIDENCE_THRESHOLD,
) -> dict[str, Any]:
    """Apply the <=threshold Evidence / >threshold index-only search contract."""

    payload = dict(canonical)
    data = dict(payload.get("data") or {})
    coverage = dict(payload.get("coverage") or {})

    # signal_hints is superseded by the complete rule-level Evidence Index.
    data.pop("signal_hints", None)
    data.pop("signal_hint_note", None)
    coverage.pop("signal_hints_returned", None)

    match_records = coverage.get("match_records")
    if not isinstance(match_records, int) or isinstance(match_records, bool):
        payload["data"] = data
        payload["coverage"] = coverage
        return payload
    if match_records <= inline_threshold:
        coverage["evidence_indexed"] = False
        payload["data"] = data
        payload["coverage"] = coverage
        return payload

    records_path = _matched_records_path(payload)
    if records_path is None:
        payload["data"] = data
        payload["coverage"] = coverage
        return payload
    index = build_evidence_index(
        records_path,
        query=query,
        regex=regex,
        source=source,
        total_matches=match_records,
        source_sha256=str(data.get("source_sha256") or ""),
    )
    if index is None:
        payload["data"] = data
        payload["coverage"] = coverage
        return payload

    # Do not expose a system-selected first-N body alongside the index.  The
    # Agent chooses a locator and explicitly materializes formal Evidence.
    payload["evidence"] = []
    for key in ("text", "new_text", "direct_raw"):
        data.pop(key, None)
    data["evidence_index"] = index
    coverage["evidence_returned"] = 0
    coverage["evidence_truncated"] = False
    coverage["evidence_indexed"] = True
    coverage["evidence_bodies_withheld"] = match_records
    # The Pi compact projection already forwards coverage, so expose the same
    # bounded navigation structure there without requiring an adapter-specific
    # hint channel.
    coverage["evidence_index"] = index
    payload["data"] = data
    payload["coverage"] = coverage
    return payload


__all__ = [
    "DEFAULT_INLINE_EVIDENCE_THRESHOLD",
    "DEFAULT_SAMPLE_LINES",
    "build_evidence_index",
    "project_search_canonical",
]
