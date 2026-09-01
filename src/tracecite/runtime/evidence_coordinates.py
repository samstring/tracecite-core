"""Mechanical source-line geometry for bounded Evidence rows.

This module exposes where Evidence lives, not what the Evidence means. It may
report exact line-distance facts between a current row and evidence blocks the
Agent previously materialized. It never reports relevance, relatedness,
causality, diagnosis, or a combined association score.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping, Sequence


DEFAULT_POSITION_PEER_LIMIT = 3
MAX_POSITION_PEER_LIMIT = 8
DEFAULT_SEEN_RANGE_LIMIT = 2
MAX_SEEN_RANGE_LIMIT = 4
DEFAULT_EVIDENCE_NEIGHBOR_LIMIT = 2
MAX_EVIDENCE_NEIGHBOR_LIMIT = 8
DEFAULT_EVIDENCE_NEIGHBOR_RADIUS_LINES = 500
MAX_EVIDENCE_NEIGHBOR_RADIUS_LINES = 100_000
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_KEY_SHA256_RE = re.compile(r"@sha256:([0-9a-f]{64})$")


def _positive_line(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return None
    return value


def _source_path(row: Mapping[str, Any], default_source_path: str | Path | None) -> str:
    raw = str(row.get("source_path") or "").strip()
    if not raw and default_source_path is not None:
        raw = str(default_source_path).strip()
    if not raw:
        return ""
    return str(Path(raw).expanduser().resolve())


def _sha256(value: object) -> str:
    digest = str(value or "").strip().lower()
    return digest if _SHA256_RE.fullmatch(digest) else ""


def _range_distance(
    left_start: int,
    left_end: int,
    right_start: int,
    right_end: int,
) -> tuple[int, str, bool]:
    """Return uncovered line gap, peer direction, and overlap from left to right."""

    if right_end < left_start:
        return left_start - right_end - 1, "before", False
    if right_start > left_end:
        return right_start - left_end - 1, "after", False
    return 0, "overlap", True


def _coordinate_fields(value: object) -> tuple[str, str, int, int] | None:
    if isinstance(value, Mapping):
        ref = str(value.get("ref") or "").strip()
        digest = _sha256(value.get("source_sha256"))
        start = _positive_line(value.get("start_line"))
        end = _positive_line(value.get("end_line"))
    else:
        ref = str(getattr(value, "ref", "") or "").strip()
        digest = _sha256(getattr(value, "source_sha256", ""))
        start = _positive_line(getattr(value, "start_line", None))
        end = _positive_line(getattr(value, "end_line", None))
    if not ref or not digest or start is None:
        return None
    if end is None or end < start:
        end = start
    return ref, digest, start, end


def attach_seen_evidence_distances(
    rows: Sequence[Mapping[str, Any]],
    seen_coordinates: Sequence[object],
    *,
    default_sha256: str | None = None,
    start_field: str = "start_line",
    end_field: str = "end_line",
    radius_lines: int = DEFAULT_EVIDENCE_NEIGHBOR_RADIUS_LINES,
    neighbor_limit: int = DEFAULT_EVIDENCE_NEIGHBOR_LIMIT,
) -> list[dict[str, Any]]:
    """Attach sparse distance facts to previously materialized Evidence blocks.

    Only immutable SHA256-identical coordinate spaces are compared. Candidates
    outside ``radius_lines`` are omitted, then at most ``neighbor_limit`` nearest
    materialized blocks are returned. Ordering by line gap is only a mechanical
    size bound; it is not a semantic relevance score.

    The current row already carries its own ``start_line`` / ``end_line`` and
    usually ``sha256``, so ``position`` only contains the additional neighbor
    facts to avoid repeating coordinates and inflating Agent context.
    """

    if (
        isinstance(radius_lines, bool)
        or not isinstance(radius_lines, int)
        or radius_lines < 0
        or radius_lines > MAX_EVIDENCE_NEIGHBOR_RADIUS_LINES
    ):
        raise ValueError(
            "radius_lines must be in "
            f"[0, {MAX_EVIDENCE_NEIGHBOR_RADIUS_LINES}]"
        )
    if (
        isinstance(neighbor_limit, bool)
        or not isinstance(neighbor_limit, int)
        or neighbor_limit < 0
        or neighbor_limit > MAX_EVIDENCE_NEIGHBOR_LIMIT
    ):
        raise ValueError(
            f"neighbor_limit must be in [0, {MAX_EVIDENCE_NEIGHBOR_LIMIT}]"
        )

    normalized_seen = [
        item
        for item in (_coordinate_fields(value) for value in seen_coordinates)
        if item is not None
    ]
    fallback_digest = _sha256(default_sha256)
    copied = [dict(row) for row in rows]
    if not normalized_seen or neighbor_limit == 0:
        return copied

    for row in copied:
        start = _positive_line(row.get(start_field))
        if start is None:
            continue
        end = _positive_line(row.get(end_field))
        if end is None or end < start:
            end = start
        digest = _sha256(row.get("sha256")) or fallback_digest
        if not digest:
            continue

        neighbors: list[tuple[int, int, str, dict[str, Any]]] = []
        for ref, seen_digest, seen_start, seen_end in normalized_seen:
            if seen_digest != digest:
                continue
            line_gap, direction, _overlaps = _range_distance(
                start,
                end,
                seen_start,
                seen_end,
            )
            if line_gap > radius_lines:
                continue
            neighbors.append(
                (
                    line_gap,
                    seen_start,
                    ref,
                    {
                        "ref": ref,
                        "range": [seen_start, seen_end],
                        "line_gap": line_gap,
                        "direction": direction,
                    },
                )
            )
        if not neighbors:
            continue
        neighbors.sort(key=lambda item: (item[0], item[1], item[2]))
        row["position"] = {
            "coordinate_space": "source_line_sha256",
            "nearest_seen": [item[3] for item in neighbors[:neighbor_limit]],
        }
    return copied


def _covered_ranges_by_sha256(
    covered_ranges: Mapping[str, Sequence[tuple[int, int]]],
) -> dict[str, tuple[tuple[int, int], ...]]:
    """Index persisted covered ranges by immutable content identity.

    This compatibility helper is retained for callers that only have coverage
    state. Agent-facing retrieval should prefer explicit materialized Evidence
    coordinates so merged coverage ranges do not erase Evidence identity.
    """

    indexed: dict[str, list[tuple[int, int]]] = {}
    for source_key, ranges in covered_ranges.items():
        match = _SOURCE_KEY_SHA256_RE.search(str(source_key or "").strip().lower())
        if match is None:
            continue
        digest = match.group(1)
        bucket = indexed.setdefault(digest, [])
        for start, end in ranges:
            if (
                isinstance(start, bool)
                or isinstance(end, bool)
                or not isinstance(start, int)
                or not isinstance(end, int)
                or start < 1
                or end < start
            ):
                continue
            bucket.append((start, end))

    result: dict[str, tuple[tuple[int, int], ...]] = {}
    for digest, values in indexed.items():
        ordered = sorted(set(values))
        merged: list[tuple[int, int]] = []
        for start, end in ordered:
            if not merged or start > merged[-1][1] + 1:
                merged.append((start, end))
            else:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        result[digest] = tuple(merged)
    return result


def attach_seen_range_distances(
    rows: Sequence[Mapping[str, Any]],
    covered_ranges: Mapping[str, Sequence[tuple[int, int]]],
    *,
    default_sha256: str | None = None,
    start_field: str = "start_line",
    end_field: str = "end_line",
    range_limit: int = DEFAULT_SEEN_RANGE_LIMIT,
) -> list[dict[str, Any]]:
    """Compatibility projection against merged materialized coverage ranges."""

    if (
        isinstance(range_limit, bool)
        or not isinstance(range_limit, int)
        or range_limit < 0
        or range_limit > MAX_SEEN_RANGE_LIMIT
    ):
        raise ValueError(f"range_limit must be in [0, {MAX_SEEN_RANGE_LIMIT}]")

    indexed = _covered_ranges_by_sha256(covered_ranges)
    fallback_digest = _sha256(default_sha256)
    copied = [dict(row) for row in rows]
    for row in copied:
        start = _positive_line(row.get(start_field))
        if start is None:
            continue
        end = _positive_line(row.get(end_field))
        if end is None or end < start:
            end = start
        digest = _sha256(row.get("sha256")) or fallback_digest
        if not digest:
            continue
        seen = indexed.get(digest, ())
        distances: list[tuple[int, int, dict[str, Any]]] = []
        for seen_start, seen_end in seen:
            line_gap, direction, overlaps = _range_distance(
                start,
                end,
                seen_start,
                seen_end,
            )
            distances.append(
                (
                    line_gap,
                    seen_start,
                    {
                        "start_line": seen_start,
                        "end_line": seen_end,
                        "line_gap": line_gap,
                        "direction": direction,
                        "overlaps": overlaps,
                    },
                )
            )
        distances.sort(key=lambda item: (item[0], item[1]))
        row["position"] = {
            "coordinate_space": "source_line_sha256",
            "source_sha256": digest,
            "start_line": start,
            "end_line": end,
            "span_lines": end - start + 1,
            "seen_range_total": len(seen),
            "nearest_seen_ranges": [item[2] for item in distances[:range_limit]],
        }
    return copied


def attach_source_line_coordinates(
    rows: Sequence[Mapping[str, Any]],
    *,
    default_source_path: str | Path | None = None,
    start_field: str = "start_line",
    end_field: str = "end_line",
    peer_limit: int = DEFAULT_POSITION_PEER_LIMIT,
) -> list[dict[str, Any]]:
    """Attach same-response line geometry as a low-level compatibility primitive."""

    if (
        isinstance(peer_limit, bool)
        or not isinstance(peer_limit, int)
        or peer_limit < 0
        or peer_limit > MAX_POSITION_PEER_LIMIT
    ):
        raise ValueError(f"peer_limit must be in [0, {MAX_POSITION_PEER_LIMIT}]")

    copied = [dict(row) for row in rows]
    coordinates: list[tuple[int, str, int, int, str] | None] = []
    for index, row in enumerate(copied):
        start = _positive_line(row.get(start_field))
        if start is None:
            coordinates.append(None)
            continue
        end = _positive_line(row.get(end_field))
        if end is None or end < start:
            end = start
        source = _source_path(row, default_source_path)
        if not source:
            coordinates.append(None)
            continue
        uri = str(row.get("uri") or "").strip()
        coordinates.append((index, source, start, end, uri))

    for current in coordinates:
        if current is None:
            continue
        index, source, start, end, _uri = current
        peers: list[tuple[int, int, int, dict[str, Any]]] = []
        for candidate in coordinates:
            if candidate is None or candidate[0] == index or candidate[1] != source:
                continue
            peer_index, _peer_source, peer_start, peer_end, peer_uri = candidate
            line_gap, direction, overlaps = _range_distance(start, end, peer_start, peer_end)
            peer: dict[str, Any] = {
                "start_line": peer_start,
                "end_line": peer_end,
                "line_gap": line_gap,
                "direction": direction,
                "overlaps": overlaps,
            }
            if peer_uri:
                peer["uri"] = peer_uri
            peers.append((line_gap, peer_start, peer_index, peer))

        peers.sort(key=lambda item: (item[0], item[1], item[2]))
        copied[index]["position"] = {
            "coordinate_space": "source_line",
            "source_path": source,
            "start_line": start,
            "end_line": end,
            "span_lines": end - start + 1,
            "peer_total": len(peers),
            "peer_distances": [item[3] for item in peers[:peer_limit]],
        }

    return copied


__all__ = [
    "DEFAULT_EVIDENCE_NEIGHBOR_LIMIT",
    "DEFAULT_EVIDENCE_NEIGHBOR_RADIUS_LINES",
    "DEFAULT_POSITION_PEER_LIMIT",
    "DEFAULT_SEEN_RANGE_LIMIT",
    "MAX_EVIDENCE_NEIGHBOR_LIMIT",
    "MAX_EVIDENCE_NEIGHBOR_RADIUS_LINES",
    "MAX_POSITION_PEER_LIMIT",
    "MAX_SEEN_RANGE_LIMIT",
    "attach_seen_evidence_distances",
    "attach_seen_range_distances",
    "attach_source_line_coordinates",
]
