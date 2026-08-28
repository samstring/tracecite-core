"""Bounded, diagnosis-free retention of high-signal search candidates.

Search result transport may be much smaller than the complete match set.  This
module lets Runtime scan the already-produced matched-record artifact and keep
a tiny set of line-addressable incident candidates without turning those hints
into canonical EvidencePointers prematurely.

The selector is deliberately mechanical: generic severity vocabulary, bounded
signature memory, deterministic replacement, and no root-cause inference.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

_SIGNAL_PATTERNS: tuple[tuple[int, re.Pattern[str]], ...] = (
    (
        4,
        re.compile(
            r"panic|fatal|crash(?:ed)?|corrupt(?:ed|ion)?|exception|"
            r"checksum\s+(?:error|mismatch)",
            re.IGNORECASE,
        ),
    ),
    (
        3,
        re.compile(
            r"\berror\b|\bfail(?:ed|ure)?\b|mismatch|timeout|timed\s+out|"
            r"connection\s+reset|broken\s+pipe|refused",
            re.IGNORECASE,
        ),
    ),
    (
        2,
        re.compile(r"unavailable|denied|abort(?:ed)?|\binvalid\b", re.IGNORECASE),
    ),
)
_IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_HEX_RE = re.compile(r"\b[0-9a-f]{8,}\b", re.IGNORECASE)
_NUMBER_RE = re.compile(r"(?<![A-Za-z])[-+]?\d+(?![A-Za-z])")
_SPACE_RE = re.compile(r"\s+")
DEFAULT_SIGNAL_SIGNATURE_CAP = 256
DEFAULT_SIGNAL_HINT_LIMIT = 4


def signal_severity(text: str) -> int:
    for severity, pattern in _SIGNAL_PATTERNS:
        if pattern.search(text):
            return severity
    return 0


def signal_signature(text: str) -> str:
    value = text.casefold()
    value = _IP_RE.sub("<ip>", value)
    value = _HEX_RE.sub("<hex>", value)
    value = _NUMBER_RE.sub("<num>", value)
    value = _SPACE_RE.sub(" ", value).strip()
    return value[:600]


def select_signal_hints(
    records_path: Path,
    *,
    limit: int = DEFAULT_SIGNAL_HINT_LIMIT,
    signature_cap: int = DEFAULT_SIGNAL_SIGNATURE_CAP,
) -> list[dict[str, Any]]:
    """Stream matched-record JSONL and return bounded high-signal line hints.

    Later higher-severity unique signals can evict lower-severity signatures,
    so a fatal/panic near the end of a huge match set is not hidden merely
    because the normal inline result already filled its first-N budget.
    """

    if limit < 1 or signature_cap < limit:
        raise ValueError("signal hint bounds are invalid")
    if not records_path.is_file():
        return []

    clusters: dict[str, dict[str, Any]] = {}
    with records_path.open("r", encoding="utf-8", errors="replace") as handle:
        for ordinal, line in enumerate(handle, start=1):
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, Mapping):
                continue
            text = str(row.get("text") or "")
            severity = signal_severity(text)
            if not severity:
                continue
            metadata = row.get("metadata") or {}
            if not isinstance(metadata, Mapping):
                metadata = {}
            start_line = metadata.get("start_line")
            end_line = metadata.get("end_line")
            if not isinstance(start_line, int) or isinstance(start_line, bool) or start_line < 1:
                continue
            if not isinstance(end_line, int) or isinstance(end_line, bool) or end_line < start_line:
                end_line = start_line
            label = next((item.strip() for item in text.splitlines() if item.strip()), "")[:240]
            if not label:
                continue
            signature = signal_signature(label)
            existing = clusters.get(signature)
            if existing is not None:
                existing["count"] += 1
                existing["severity"] = max(int(existing["severity"]), severity)
                continue

            candidate = {
                "line": start_line,
                "end_line": end_line,
                "severity": severity,
                "count": 1,
                "label": label,
                "ordinal": ordinal,
            }
            if len(clusters) < signature_cap:
                clusters[signature] = candidate
                continue

            victim_signature, victim = min(
                clusters.items(),
                key=lambda item: (
                    int(item[1]["severity"]),
                    -int(item[1]["count"]),
                    -int(item[1]["ordinal"]),
                ),
            )
            if severity > int(victim["severity"]):
                del clusters[victim_signature]
                clusters[signature] = candidate

    selected = sorted(
        clusters.values(),
        key=lambda item: (
            -int(item["severity"]),
            int(item["count"]),
            int(item["ordinal"]),
        ),
    )[:limit]
    return [
        {
            "line": int(item["line"]),
            "end_line": int(item["end_line"]),
            "severity": int(item["severity"]),
            "count": int(item["count"]),
            "label": str(item["label"]),
        }
        for item in selected
    ]


__all__ = [
    "DEFAULT_SIGNAL_HINT_LIMIT",
    "DEFAULT_SIGNAL_SIGNATURE_CAP",
    "select_signal_hints",
    "signal_severity",
    "signal_signature",
]
