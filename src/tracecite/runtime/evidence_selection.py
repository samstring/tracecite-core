"""Bounded, diagnosis-free retention of useful search candidates.

Search result transport may be much smaller than the complete match set. This
module scans the already-produced matched-record artifact and keeps a tiny set
of line-addressable navigation candidates without turning those hints into
canonical EvidencePointers prematurely.

Selection is deliberately mechanical. Generic severity vocabulary keeps late
fatal/error records visible, while structural signatures compress repeated
records and preserve rare call-stack/log shapes. No root-cause vocabulary,
component-specific terms, or causal inference is used.
"""

from __future__ import annotations

from collections import Counter
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
_HEX_RE = re.compile(r"\b(?:0x[0-9a-f]+|[0-9a-f]{8,})\b", re.IGNORECASE)
_UUID_RE = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
_NUMBER_RE = re.compile(r"(?<![A-Za-z])[-+]?\d+(?![A-Za-z])")
_SPACE_RE = re.compile(r"[ \t]+")
DEFAULT_SIGNAL_SIGNATURE_CAP = 256
DEFAULT_SIGNAL_HINT_LIMIT = 4
_STRUCTURAL_LINE_LIMIT = 24
_STRUCTURAL_CHAR_LIMIT = 3_000


def signal_severity(text: str) -> int:
    for severity, pattern in _SIGNAL_PATTERNS:
        if pattern.search(text):
            return severity
    return 0


def _normalise_structure_line(text: str) -> str:
    value = text.casefold().strip()
    value = _UUID_RE.sub("<uuid>", value)
    value = _IP_RE.sub("<ip>", value)
    value = _HEX_RE.sub("<hex>", value)
    value = _NUMBER_RE.sub("<num>", value)
    value = _SPACE_RE.sub(" ", value).strip()
    return value


def structural_signature(text: str) -> str:
    """Return a bounded signature that preserves record/call-stack structure.

    Volatile IDs, addresses, line numbers and counters are normalized, while
    function names, states, messages and frame ordering remain visible. This
    makes dozens of equivalent goroutine/log records collapse into one cluster
    without teaching the selector what any particular component means.
    """

    lines: list[str] = []
    chars = 0
    for raw in str(text or "").splitlines():
        value = _normalise_structure_line(raw)
        if not value:
            continue
        remaining = _STRUCTURAL_CHAR_LIMIT - chars
        if remaining <= 0:
            break
        value = value[:remaining]
        lines.append(value)
        chars += len(value) + 1
        if len(lines) >= _STRUCTURAL_LINE_LIMIT:
            break
    return "\n".join(lines)


def signal_signature(text: str) -> str:
    """Backward-compatible single-line-ish normalized signature."""

    value = _normalise_structure_line(text)
    return value[:600]


def _feature_lines(signature: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(line for line in signature.splitlines() if line))


def _distinctiveness(clusters: Mapping[str, Mapping[str, Any]]) -> dict[str, float]:
    """Score structures by how uncommon their normalized frame/message lines are."""

    feature_frequency: Counter[str] = Counter()
    for signature, item in clusters.items():
        count = max(1, int(item.get("count") or 1))
        for feature in _feature_lines(signature):
            feature_frequency[feature] += count

    scores: dict[str, float] = {}
    for signature in clusters:
        features = _feature_lines(signature)
        if not features:
            scores[signature] = 0.0
            continue
        contributions = sorted(
            (1.0 / max(1, feature_frequency[feature]) for feature in features),
            reverse=True,
        )[:12]
        scores[signature] = sum(contributions)
    return scores


def select_signal_hints(
    records_path: Path,
    *,
    limit: int = DEFAULT_SIGNAL_HINT_LIMIT,
    signature_cap: int = DEFAULT_SIGNAL_SIGNATURE_CAP,
) -> list[dict[str, Any]]:
    """Return bounded high-signal or structurally diverse navigation hints.

    Repeated records are clustered by normalized full-record structure. High
    severity clusters remain first. Within the same severity, rarer structures
    rank ahead of frequent duplicates, so a one-off call-stack branch is not
    hidden behind dozens of equivalent matches. Returned rows remain navigation
    hints only; callers must materialize them before citing them as Evidence.
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
            signature = structural_signature(text)
            if not signature:
                continue
            severity = signal_severity(text)
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

            # Keep the memory bound deterministic while allowing a later unique
            # structure to displace an already-repeated low-severity cluster.
            victim_signature, victim = max(
                clusters.items(),
                key=lambda item: (
                    -int(item[1]["severity"]),
                    int(item[1]["count"]),
                    -int(item[1]["ordinal"]),
                ),
            )
            victim_severity = int(victim["severity"])
            victim_count = int(victim["count"])
            if severity > victim_severity or (severity == victim_severity and victim_count > 1):
                del clusters[victim_signature]
                clusters[signature] = candidate

    distinctiveness = _distinctiveness(clusters)
    selected_pairs = sorted(
        clusters.items(),
        key=lambda pair: (
            -int(pair[1]["severity"]),
            int(pair[1]["count"]),
            -float(distinctiveness.get(pair[0], 0.0)),
            int(pair[1]["ordinal"]),
        ),
    )[:limit]
    return [
        {
            "line": int(item["line"]),
            "end_line": int(item["end_line"]),
            "severity": int(item["severity"]),
            "count": int(item["count"]),
            "label": str(item["label"]),
            "kind": "high_signal" if int(item["severity"]) > 0 else "structural_diversity",
            "distinctiveness": round(float(distinctiveness.get(signature, 0.0)), 6),
        }
        for signature, item in selected_pairs
    ]


__all__ = [
    "DEFAULT_SIGNAL_HINT_LIMIT",
    "DEFAULT_SIGNAL_SIGNATURE_CAP",
    "select_signal_hints",
    "signal_severity",
    "signal_signature",
    "structural_signature",
]
