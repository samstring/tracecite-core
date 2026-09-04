"""Lookup immutable SHA metadata already owned by SourceVersionStore."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping

from tracecite_core.state_file import read_json


def _views_from_payload(payload: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    direct = payload.get("view")
    if isinstance(direct, Mapping):
        yield direct
    views = payload.get("views")
    if isinstance(views, Mapping):
        for item in views.values():
            if isinstance(item, Mapping):
                yield item


def managed_segment_sha(
    path: str | Path,
    *,
    root: str | Path | None = None,
) -> str | None:
    """Return cached SHA only when SourceVersionStore owns this exact path.

    Both the latest per-source cache and question-bound historical views are
    searched so previously cited immutable snapshots remain replayable after a
    newer source version is established.
    """

    target = Path(path).expanduser().resolve()
    cache_roots: list[Path] = []
    if root is not None:
        cache_roots.append(Path(root).expanduser().resolve() / "_source_versions")

    for parent in (target.parent, *target.parents):
        if parent.name == "_source_versions":
            cache_roots.append(parent)
            break

    seen: set[Path] = set()
    for cache_root in cache_roots:
        cache_root = cache_root.resolve()
        if cache_root in seen:
            continue
        seen.add(cache_root)
        state_files: list[Path] = []
        for directory in (cache_root / "sources", cache_root / "questions"):
            if directory.is_dir():
                state_files.extend(directory.glob("*.json"))
        for state_path in state_files:
            try:
                payload = read_json(state_path)
            except (OSError, ValueError):
                continue
            if not isinstance(payload, Mapping):
                continue
            for view in _views_from_payload(payload):
                segments = view.get("segments") or []
                if not isinstance(segments, list):
                    continue
                for item in segments:
                    if not isinstance(item, Mapping):
                        continue
                    raw_path = str(item.get("path") or "").strip()
                    digest = str(item.get("sha256") or "").strip().lower()
                    if not raw_path or len(digest) != 64:
                        continue
                    try:
                        candidate = Path(raw_path).expanduser().resolve()
                    except OSError:
                        continue
                    if candidate == target and all(
                        ch in "0123456789abcdef" for ch in digest
                    ):
                        return digest
    return None


__all__ = ["managed_segment_sha"]
