"""Bounded, diagnosis-free retention of useful search candidates.

Search result transport may be much smaller than the complete match set. This
module scans the already-produced matched-record artifact and keeps a tiny set
of line-addressable navigation candidates without turning those hints into
canonical EvidencePointers prematurely.

Selection is deliberately mechanical. Generic severity vocabulary keeps late
fatal/error records visible, while structural signatures compress repeated
records and preserve rare local record/call-stack shapes. No root-cause
vocabulary, component-specific terms, or causal inference is used.

Structural neighborhoods are an internal clustering aid only. Their raw bodies
are never returned to the Agent. All neighborhood, signature, label and hint
sizes are hard-bounded so diversity discovery cannot become an unbounded model
context expansion mechanism.
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
MAX_SIGNAL_SIGNATURE_CAP = 2_048
DEFAULT_SIGNAL_HINT_LIMIT = 4
MAX_SIGNAL_HINT_LIMIT = 8
DEFAULT_STRUCTURAL_NEIGHBORHOOD_RADIUS = 8
MAX_STRUCTURAL_NEIGHBORHOOD_RADIUS = 12
MAX_STRUCTURAL_NEIGHBORHOOD_CHARS = 6_000
STRUCTURAL_SIGNATURE_LINE_LIMIT = 24
STRUCTURAL_SIGNATURE_CHAR_LIMIT = 3_000
HINT_LABEL_CHAR_LIMIT = 160


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
    makes equivalent goroutine/log neighborhoods collapse into one cluster
    without teaching the selector what any particular component means.
    """

    lines: list[str] = []
    chars = 0
    for raw in str(text or "").splitlines():
        value = _normalise_structure_line(raw)
        if not value:
            continue
        remaining = STRUCTURAL_SIGNATURE_CHAR_LIMIT - chars
        if remaining <= 0:
            break
        value = value[:remaining]
        lines.append(value)
        chars += len(value) + 1
        if len(lines) >= STRUCTURAL_SIGNATURE_LINE_LIMIT:
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


def _source_neighborhoods(
    source_path: Path,
    candidates: list[dict[str, Any]],
    *,
    radius: int,
) -> list[str]:
    """Read requested neighborhoods once, with a hard per-candidate char bound.

    The returned strings exist only long enough to compute structural
    fingerprints. They are never copied into navigation hints or Agent output.
    """

    if radius < 0 or not source_path.is_file() or not candidates:
        return [
            str(item.get("text") or "")[:MAX_STRUCTURAL_NEIGHBORHOOD_CHARS]
            for item in candidates
        ]

    intervals: list[tuple[int, int, int]] = []
    for index, item in enumerate(candidates):
        start = int(item["line"])
        end = int(item["end_line"])
        intervals.append((max(1, start - radius), end + radius, index))
    intervals.sort(key=lambda item: (item[0], item[1], item[2]))

    buffers: list[list[str]] = [[] for _ in candidates]
    char_counts = [0 for _ in candidates]
    active: list[tuple[int, int]] = []
    next_interval = 0
    with source_path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_number, raw in enumerate(handle, start=1):
            while next_interval < len(intervals) and intervals[next_interval][0] <= line_number:
                _left, right, index = intervals[next_interval]
                active.append((right, index))
                next_interval += 1
            if active:
                active = [(right, index) for right, index in active if right >= line_number]
                for _right, index in active:
                    remaining = MAX_STRUCTURAL_NEIGHBORHOOD_CHARS - char_counts[index]
                    if remaining <= 0:
                        continue
                    chunk = raw[:remaining]
                    buffers[index].append(chunk)
                    char_counts[index] += len(chunk)
            if next_interval >= len(intervals) and not active:
                break

    return [
        (
            "".join(buffer)
            if buffer
            else str(candidates[index].get("text") or "")[:MAX_STRUCTURAL_NEIGHBORHOOD_CHARS]
        )
        for index, buffer in enumerate(buffers)
    ]


def select_signal_hints(
    records_path: Path,
    *,
    source_path: Path | None = None,
    limit: int = DEFAULT_SIGNAL_HINT_LIMIT,
    signature_cap: int = DEFAULT_SIGNAL_SIGNATURE_CAP,
    neighborhood_radius: int = DEFAULT_STRUCTURAL_NEIGHBORHOOD_RADIUS,
) -> list[dict[str, Any]]:
    """Return bounded high-signal or structurally diverse navigation hints.

    When the original source is available, each match is fingerprinted from a
    small local line neighborhood rather than the matching line alone. This is
    important for stack dumps and multiline incidents where every matching frame
    is identical but the nearby caller/callee chain differs. The neighborhood is
    used only for mechanical clustering; returned hints contain only bounded
    coordinates and a short match label, never the neighborhood body.
    """

    if limit < 1 or limit > MAX_SIGNAL_HINT_LIMIT:
        raise ValueError(f"limit must be in [1, {MAX_SIGNAL_HINT_LIMIT}]")
    if signature_cap < limit or signature_cap > MAX_SIGNAL_SIGNATURE_CAP:
        raise ValueError(
            f"signature_cap must be in [limit, {MAX_SIGNAL_SIGNATURE_CAP}]"
        )
    if neighborhood_radius < 0 or neighborhood_radius > MAX_STRUCTURAL_NEIGHBORHOOD_RADIUS:
        raise ValueError(
            "neighborhood_radius must be in "
            f"[0, {MAX_STRUCTURAL_NEIGHBORHOOD_RADIUS}]"
        )
    if not records_path.is_file():
        return []

    candidates: list[dict[str, Any]] = []
    with records_path.open("r", encoding="utf-8", errors="replace") as handle:
        for ordinal, line in enumerate(handle, start=1):
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, Mapping):
                continue
            text = str(row.get("text") or "")
            metadata = row.get("metadata") or {}
            if not isinstance(metadata, Mapping):
                metadata = {}
            start_line = metadata.get("start_line")
            end_line = metadata.get("end_line")
            if not isinstance(start_line, int) or isinstance(start_line, bool) or start_line < 1:
                continue
            if not isinstance(end_line, int) or isinstance(end_line, bool) or end_line < start_line:
                end_line = start_line
            label = next((item.strip() for item in text.splitlines() if item.strip()), "")[:HINT_LABEL_CHAR_LIMIT]
            if not label:
                continue
            candidates.append(
                {
                    "line": start_line,
                    "end_line": end_line,
                    "severity": signal_severity(text),
                    "label": label,
                    "ordinal": ordinal,
                    "text": text[:MAX_STRUCTURAL_NEIGHBORHOOD_CHARS],
                }
            )

    if not candidates:
        return []

    structural_texts = (
        _source_neighborhoods(
            Path(source_path).expanduser().resolve(),
            candidates,
            radius=neighborhood_radius,
        )
        if source_path is not None
        else [
            str(item.get("text") or "")[:MAX_STRUCTURAL_NEIGHBORHOOD_CHARS]
            for item in candidates
        ]
    )

    clusters: dict[str, dict[str, Any]] = {}
    for candidate, structural_text in zip(candidates, structural_texts):
        signature = structural_signature(structural_text)
        if not signature:
            continue
        severity = max(int(candidate["severity"]), signal_severity(structural_text))
        existing = clusters.get(signature)
        if existing is not None:
            existing["count"] += 1
            existing["severity"] = max(int(existing["severity"]), severity)
            continue

        item = {
            "line": int(candidate["line"]),
            "end_line": int(candidate["end_line"]),
            "severity": severity,
            "count": 1,
            "label": str(candidate["label"])[:HINT_LABEL_CHAR_LIMIT],
            "ordinal": int(candidate["ordinal"]),
        }
        if len(clusters) < signature_cap:
            clusters[signature] = item
            continue

        # Keep the memory bound deterministic while allowing a later unique
        # structure to displace an already-repeated low-severity cluster.
        victim_signature, victim = max(
            clusters.items(),
            key=lambda pair: (
                -int(pair[1]["severity"]),
                int(pair[1]["count"]),
                -int(pair[1]["ordinal"]),
            ),
        )
        victim_severity = int(victim["severity"])
        victim_count = int(victim["count"])
        if severity > victim_severity or (severity == victim_severity and victim_count > 1):
            del clusters[victim_signature]
            clusters[signature] = item

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
            "label": str(item["label"])[:HINT_LABEL_CHAR_LIMIT],
            "kind": "high_signal" if int(item["severity"]) > 0 else "structural_diversity",
            "distinctiveness": round(float(distinctiveness.get(signature, 0.0)), 6),
        }
        for signature, item in selected_pairs
    ]


__all__ = [
    "DEFAULT_SIGNAL_HINT_LIMIT",
    "DEFAULT_SIGNAL_SIGNATURE_CAP",
    "DEFAULT_STRUCTURAL_NEIGHBORHOOD_RADIUS",
    "HINT_LABEL_CHAR_LIMIT",
    "MAX_SIGNAL_HINT_LIMIT",
    "MAX_SIGNAL_SIGNATURE_CAP",
    "MAX_STRUCTURAL_NEIGHBORHOOD_CHARS",
    "MAX_STRUCTURAL_NEIGHBORHOOD_RADIUS",
    "select_signal_hints",
    "signal_severity",
    "signal_signature",
    "structural_signature",
]
