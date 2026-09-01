"""Mechanical source-line coordinates for bounded Evidence rows.

This module exposes where Evidence lives, not what the Evidence means.  It may
report exact source/range facts and bounded line-distance facts between rows in
the same source.  It never reports relevance, relatedness, causality, diagnosis,
or a combined association score.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence


DEFAULT_POSITION_PEER_LIMIT = 3
MAX_POSITION_PEER_LIMIT = 8


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


def attach_source_line_coordinates(
    rows: Sequence[Mapping[str, Any]],
    *,
    default_source_path: str | Path | None = None,
    start_field: str = "start_line",
    end_field: str = "end_line",
    peer_limit: int = DEFAULT_POSITION_PEER_LIMIT,
) -> list[dict[str, Any]]:
    """Copy rows and attach bounded, diagnosis-free source-line geometry.

    ``peer_distances`` contains only rows from the same resolved source.  Peers
    are ordered by the mechanical line gap, then by source position, solely to
    keep the returned metadata bounded and deterministic.  A small gap is not a
    claim of semantic relation.
    """

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
            line_gap, direction, overlaps = _range_distance(
                start,
                end,
                peer_start,
                peer_end,
            )
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
    "DEFAULT_POSITION_PEER_LIMIT",
    "MAX_POSITION_PEER_LIMIT",
    "attach_source_line_coordinates",
]
