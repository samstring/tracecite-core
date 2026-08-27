# -*- coding: utf-8 -*-
"""通用段 manifest：登记 rename/archive 产生的稳定文件段。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from .state_file import atomic_write_json, read_json, state_lock

MANIFEST_FILENAME = "manifest.json"


class SegmentStoreError(RuntimeError):
    pass


@dataclass
class StoredSegment:
    start: str
    end: str
    path: str
    bytes: int
    lines: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "start": self.start,
            "end": self.end,
            "path": self.path,
            "bytes": self.bytes,
            "lines": self.lines,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StoredSegment":
        return cls(
            start=str(data["start"]),
            end=str(data["end"]),
            path=str(data["path"]),
            bytes=int(data.get("bytes", 0)),
            lines=int(data.get("lines", 0)),
        )


def manifest_path(store_dir: Path, *, filename: str = MANIFEST_FILENAME) -> Path:
    return Path(store_dir) / filename


def load_segments(
    store_dir: Path,
    *,
    filename: str = MANIFEST_FILENAME,
) -> List[StoredSegment]:
    path = manifest_path(store_dir, filename=filename)
    if not path.is_file():
        return []
    try:
        data = read_json(path)
    except ValueError as exc:
        raise SegmentStoreError(str(exc)) from exc
    segments = data.get("segments") or []
    if not isinstance(segments, list):
        raise SegmentStoreError(f"manifest segments 必须是数组: {path}")
    return [StoredSegment.from_dict(item) for item in segments]


def _save_segments_unlocked(
    store_dir: Path,
    segments: List[StoredSegment],
    *,
    filename: str = MANIFEST_FILENAME,
) -> None:
    store_dir = Path(store_dir)
    store_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        manifest_path(store_dir, filename=filename),
        {
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "segments": [item.to_dict() for item in segments],
        },
    )


def save_segments(
    store_dir: Path,
    segments: List[StoredSegment],
    *,
    filename: str = MANIFEST_FILENAME,
) -> None:
    """Persist a manifest while serializing writers for this manifest."""
    path = manifest_path(store_dir, filename=filename)
    with state_lock(path):
        _save_segments_unlocked(store_dir, segments, filename=filename)


def append_segment(store_dir: Path, segment: StoredSegment, *, filename: str = MANIFEST_FILENAME) -> None:
    """Append one manifest row with the full read-modify-write transaction locked."""
    path = manifest_path(store_dir, filename=filename)
    with state_lock(path):
        rows = load_segments(store_dir, filename=filename)
        rows.append(segment)
        rows.sort(key=lambda item: item.start)
        _save_segments_unlocked(store_dir, rows, filename=filename)


def _stamp(ts: datetime) -> str:
    return ts.strftime("%Y%m%d_%H%M%S")


def unique_segment_path(
    store_dir: Path,
    start: datetime,
    end: datetime,
    *,
    prefix: str,
    suffix: str = ".log",
    reserve: bool = False,
) -> Path:
    """Choose a segment path, optionally reserving it atomically.

    The default preserves the historical check-only API: callers that need to
    claim a path before writing should pass ``reserve=True``.  Reservation
    creates an empty file with ``O_EXCL``; the caller owns that placeholder and
    may open it for writing or remove it on abort.
    """
    store_dir = Path(store_dir)
    store_dir.mkdir(parents=True, exist_ok=True)
    label = f"{prefix}_{_stamp(start)}-{_stamp(end)}" if prefix else f"{_stamp(start)}-{_stamp(end)}"
    candidate = store_dir / f"{label}{suffix}"
    if reserve:
        try:
            fd = os.open(candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(fd)
            return candidate
    elif not candidate.exists():
        return candidate
    n = 1
    while True:
        candidate = store_dir / f"{label}_{n}{suffix}"
        if reserve:
            try:
                fd = os.open(candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                n += 1
                continue
            os.close(fd)
            return candidate
        if not candidate.exists():
            return candidate
        n += 1
