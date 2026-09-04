"""Persistent immutable SourceVersion views for Agent evidence retrieval.

One RetrievalSession represents one user-question investigation. The first access
to a source binds that question to one immutable QuestionSourceView. Later tool
calls in the same question reuse the exact view without snapshotting or hashing
again.

Across questions, unchanged source fingerprints reuse the previous immutable
snapshot and SHA. Live sources accumulate immutable segments; cooperative
LiveCut is used when a writer participates, otherwise only newly appended bytes
are copied after the first capture.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, TYPE_CHECKING

from tracecite_core.live_cut import cooperative_live_cut
from tracecite_core.segment_store import unique_segment_path
from tracecite_core.state_file import atomic_write_json, read_json, state_lock

from .evidence_identity import SourceVersion

if TYPE_CHECKING:
    from .retrieval_session import RetrievalSessionStore


SOURCE_VIEW_SCHEMA_VERSION = 1
_LIVE_REQUEST_SUFFIX = ".tracecite-cut.request"
_LIVE_DONE_SUFFIX = ".tracecite-cut.done"
_PROBE_BYTES = 64 * 1024


@dataclass(frozen=True)
class SourceFingerprint:
    device: int
    inode: int
    size: int
    mtime_ns: int
    ctime_ns: int

    @classmethod
    def from_stat(cls, stat: os.stat_result) -> "SourceFingerprint":
        return cls(
            device=int(stat.st_dev),
            inode=int(stat.st_ino),
            size=int(stat.st_size),
            mtime_ns=int(stat.st_mtime_ns),
            ctime_ns=int(stat.st_ctime_ns),
        )

    def to_dict(self) -> dict[str, int]:
        return {
            "device": self.device,
            "inode": self.inode,
            "size": self.size,
            "mtime_ns": self.mtime_ns,
            "ctime_ns": self.ctime_ns,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SourceFingerprint":
        return cls(
            device=int(value.get("device") or 0),
            inode=int(value.get("inode") or 0),
            size=int(value.get("size") or 0),
            mtime_ns=int(value.get("mtime_ns") or 0),
            ctime_ns=int(value.get("ctime_ns") or 0),
        )


@dataclass(frozen=True)
class SourceSegment:
    path: str
    sha256: str
    bytes: int
    lines: int
    line_base: int = 1
    source_offset_start: int = 0
    source_offset_end: int = 0

    def __post_init__(self) -> None:
        digest = str(self.sha256 or "").lower()
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise ValueError("source segment sha256 must be 64 lowercase hex characters")
        if self.bytes < 0 or self.lines < 0 or self.line_base < 1:
            raise ValueError("invalid source segment metadata")
        if self.source_offset_start < 0 or self.source_offset_end < self.source_offset_start:
            raise ValueError("invalid source segment byte range")
        object.__setattr__(self, "path", str(Path(self.path).expanduser().resolve()))
        object.__setattr__(self, "sha256", digest)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "bytes": self.bytes,
            "lines": self.lines,
            "line_base": self.line_base,
            "source_offset_start": self.source_offset_start,
            "source_offset_end": self.source_offset_end,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SourceSegment":
        return cls(
            path=str(value.get("path") or ""),
            sha256=str(value.get("sha256") or ""),
            bytes=int(value.get("bytes") or 0),
            lines=int(value.get("lines") or 0),
            line_base=int(value.get("line_base") or 1),
            source_offset_start=int(value.get("source_offset_start") or 0),
            source_offset_end=int(value.get("source_offset_end") or 0),
        )


@dataclass(frozen=True)
class QuestionSourceView:
    source: str
    mode: str
    version_id: str
    segments: tuple[SourceSegment, ...]
    fingerprint: SourceFingerprint
    created_at: str
    reused: bool = False
    question_bound: bool = False

    def __post_init__(self) -> None:
        source = str(Path(self.source).expanduser().resolve())
        mode = str(self.mode or "").lower()
        if mode not in {"static", "mutable", "live"}:
            raise ValueError(f"unsupported source mode: {mode!r}")
        version_id = str(self.version_id or "").lower()
        if len(version_id) != 64 or any(ch not in "0123456789abcdef" for ch in version_id):
            raise ValueError("source view version_id must be a sha256 digest")
        if not self.segments:
            raise ValueError("source view requires at least one immutable segment")
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "version_id", version_id)
        object.__setattr__(self, "segments", tuple(self.segments))

    @property
    def total_bytes(self) -> int:
        return sum(item.bytes for item in self.segments)

    @property
    def total_lines(self) -> int:
        return sum(item.lines for item in self.segments)

    @property
    def source_version(self) -> SourceVersion:
        return SourceVersion(
            namespace="file-view",
            source=self.source,
            kind="generation",
            value=self.version_id,
        )

    @property
    def key(self) -> str:
        return self.source_version.key

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SOURCE_VIEW_SCHEMA_VERSION,
            "source": self.source,
            "mode": self.mode,
            "version_id": self.version_id,
            "source_version": self.source_version.to_dict(),
            "segments": [item.to_dict() for item in self.segments],
            "fingerprint": self.fingerprint.to_dict(),
            "created_at": self.created_at,
            "total_bytes": self.total_bytes,
            "total_lines": self.total_lines,
            "reused": self.reused,
            "question_bound": self.question_bound,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "QuestionSourceView":
        if int(value.get("schema_version") or SOURCE_VIEW_SCHEMA_VERSION) != SOURCE_VIEW_SCHEMA_VERSION:
            raise ValueError("unsupported SourceView schema version")
        raw_segments = value.get("segments") or []
        if not isinstance(raw_segments, list):
            raise ValueError("source view segments must be a list")
        fingerprint = value.get("fingerprint") or {}
        if not isinstance(fingerprint, Mapping):
            raise ValueError("source view fingerprint must be an object")
        return cls(
            source=str(value.get("source") or ""),
            mode=str(value.get("mode") or ""),
            version_id=str(value.get("version_id") or ""),
            segments=tuple(SourceSegment.from_mapping(item) for item in raw_segments if isinstance(item, Mapping)),
            fingerprint=SourceFingerprint.from_mapping(fingerprint),
            created_at=str(value.get("created_at") or ""),
            reused=bool(value.get("reused")),
            question_bound=bool(value.get("question_bound")),
        )


def _source_key(path: Path) -> str:
    return hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:32]


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")


def _view_id(source: Path, mode: str, segments: tuple[SourceSegment, ...]) -> str:
    payload = {
        "source": str(source),
        "mode": mode,
        "segments": [
            {
                "sha256": item.sha256,
                "bytes": item.bytes,
                "lines": item.lines,
                "source_offset_start": item.source_offset_start,
                "source_offset_end": item.source_offset_end,
            }
            for item in segments
        ],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _hash_file(path: Path) -> tuple[str, int, int]:
    digest = hashlib.sha256()
    byte_count = 0
    newline_count = 0
    last_byte = b""
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
            byte_count += len(block)
            newline_count += block.count(b"\n")
            last_byte = block[-1:]
    lines = newline_count + int(byte_count > 0 and last_byte != b"\n")
    return digest.hexdigest(), byte_count, lines


def _hash_range(path: Path, start: int, end: int) -> str:
    digest = hashlib.sha256()
    remaining = max(0, end - start)
    with path.open("rb") as handle:
        handle.seek(start)
        while remaining:
            block = handle.read(min(1024 * 1024, remaining))
            if not block:
                break
            digest.update(block)
            remaining -= len(block)
    if remaining:
        return ""
    return digest.hexdigest()


def _probe(path: Path, captured_size: int) -> tuple[int, str]:
    if captured_size <= 0:
        return 0, hashlib.sha256(b"").hexdigest()
    start = max(0, captured_size - _PROBE_BYTES)
    return start, _hash_range(path, start, captured_size)


def _copy_range(
    source: Path,
    destination: Path,
    *,
    start: int,
    end: int,
) -> SourceSegment:
    if end < start:
        raise ValueError("snapshot byte range is invalid")
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    tmp = Path(tmp_name)
    digest = hashlib.sha256()
    byte_count = 0
    newline_count = 0
    last_byte = b""
    try:
        with os.fdopen(fd, "wb") as output, source.open("rb") as input_handle:
            input_handle.seek(start)
            remaining = end - start
            while remaining:
                block = input_handle.read(min(1024 * 1024, remaining))
                if not block:
                    raise OSError(
                        f"source became shorter while snapshotting: {source}"
                    )
                output.write(block)
                digest.update(block)
                byte_count += len(block)
                newline_count += block.count(b"\n")
                last_byte = block[-1:]
                remaining -= len(block)
            output.flush()
            os.fsync(output.fileno())
        sha = digest.hexdigest()
        final = destination.with_name(f"{destination.stem}-{sha[:16]}{destination.suffix}")
        if final.exists():
            tmp.unlink(missing_ok=True)
        else:
            os.replace(tmp, final)
        lines = newline_count + int(byte_count > 0 and last_byte != b"\n")
        return SourceSegment(
            path=str(final),
            sha256=sha,
            bytes=byte_count,
            lines=lines,
            source_offset_start=start,
            source_offset_end=end,
        )
    finally:
        tmp.unlink(missing_ok=True)


def _complete_line_boundary(path: Path, size: int, floor: int) -> int:
    """Prefer a newline boundary so fallback live segments do not split lines."""
    if size <= floor:
        return floor
    window = min(size - floor, 1024 * 1024)
    start = size - window
    with path.open("rb") as handle:
        handle.seek(start)
        tail = handle.read(window)
    pos = tail.rfind(b"\n")
    if pos < 0:
        return size if floor == 0 else floor
    return start + pos + 1


class SourceVersionStore:
    """Persist and reuse source versions across Agent tool processes."""

    def __init__(self, root: str | Path, *, question_id: str = "") -> None:
        self.root = Path(root).expanduser().resolve()
        self.question_id = str(question_id or "").strip()
        self.cache_dir = self.root / "_source_versions"
        self.sources_dir = self.cache_dir / "sources"
        self.snapshots_dir = self.cache_dir / "snapshots"
        self.live_dir = self.cache_dir / "live"
        self.questions_dir = self.cache_dir / "questions"

    @classmethod
    def for_session(cls, session: "RetrievalSessionStore") -> "SourceVersionStore":
        return cls(session.root, question_id=session.context_id)

    def _source_state_path(self, source: Path) -> Path:
        return self.sources_dir / f"{_source_key(source)}.json"

    def _question_path(self) -> Path | None:
        if not self.question_id:
            return None
        return self.questions_dir / f"{self.question_id}.json"

    def _load_question_view(self, source: Path) -> QuestionSourceView | None:
        path = self._question_path()
        if path is None or not path.is_file():
            return None
        try:
            payload = read_json(path)
        except ValueError:
            return None
        views = payload.get("views") or {}
        if not isinstance(views, Mapping):
            return None
        raw = views.get(str(source))
        if not isinstance(raw, Mapping):
            return None
        try:
            view = QuestionSourceView.from_mapping(raw)
        except (TypeError, ValueError):
            return None
        if all(Path(item.path).is_file() for item in view.segments):
            return replace(view, reused=True, question_bound=True)
        return None

    def _bind_question(self, view: QuestionSourceView) -> QuestionSourceView:
        path = self._question_path()
        bound = replace(view, question_bound=True)
        if path is None:
            return bound
        path.parent.mkdir(parents=True, exist_ok=True)
        with state_lock(path):
            payload: dict[str, Any]
            if path.is_file():
                try:
                    payload = read_json(path)
                except ValueError:
                    payload = {}
            else:
                payload = {}
            views = payload.get("views")
            if not isinstance(views, dict):
                views = {}
            views[view.source] = bound.to_dict()
            atomic_write_json(
                path,
                {
                    "schema_version": SOURCE_VIEW_SCHEMA_VERSION,
                    "question_id": self.question_id,
                    "updated_at": _now(),
                    "views": views,
                },
            )
        return bound

    def _load_source_state(self, source: Path) -> dict[str, Any]:
        path = self._source_state_path(source)
        if not path.is_file():
            return {}
        try:
            payload = read_json(path)
        except ValueError:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _save_source_state(self, source: Path, payload: Mapping[str, Any]) -> None:
        path = self._source_state_path(source)
        path.parent.mkdir(parents=True, exist_ok=True)
        with state_lock(path):
            atomic_write_json(path, dict(payload))

    def resolve(
        self,
        source: str | Path,
        *,
        mode: str = "mutable",
        live_cut_timeout_seconds: float = 0.25,
    ) -> QuestionSourceView:
        path = Path(source).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        resolved_mode = str(mode or "mutable").strip().lower()
        if resolved_mode == "auto":
            resolved_mode = "mutable"
        if resolved_mode not in {"static", "mutable", "live"}:
            raise ValueError("source mode must be static, mutable, live, or auto")

        bound = self._load_question_view(path)
        if bound is not None:
            return bound

        if resolved_mode == "static":
            view = self._resolve_static(path)
        elif resolved_mode == "live":
            view = self._resolve_live(
                path, live_cut_timeout_seconds=max(0.0, live_cut_timeout_seconds)
            )
        else:
            view = self._resolve_mutable(path)
        return self._bind_question(view)

    def _cached_view_if_same(
        self,
        source: Path,
        state: Mapping[str, Any],
        fingerprint: SourceFingerprint,
        *,
        mode: str,
    ) -> QuestionSourceView | None:
        raw = state.get("view")
        prior_fp = state.get("fingerprint")
        if not isinstance(raw, Mapping) or not isinstance(prior_fp, Mapping):
            return None
        try:
            cached_fp = SourceFingerprint.from_mapping(prior_fp)
            view = QuestionSourceView.from_mapping(raw)
        except (TypeError, ValueError):
            return None
        if cached_fp != fingerprint or view.mode != mode:
            return None
        if not all(Path(item.path).is_file() for item in view.segments):
            return None
        return replace(view, reused=True, fingerprint=fingerprint)

    def _resolve_static(self, source: Path) -> QuestionSourceView:
        fingerprint = SourceFingerprint.from_stat(source.stat())
        state = self._load_source_state(source)
        cached = self._cached_view_if_same(source, state, fingerprint, mode="static")
        if cached is not None:
            return cached
        digest, byte_count, lines = _hash_file(source)
        segment = SourceSegment(
            path=str(source),
            sha256=digest,
            bytes=byte_count,
            lines=lines,
            source_offset_start=0,
            source_offset_end=byte_count,
        )
        segments = (segment,)
        view = QuestionSourceView(
            source=str(source),
            mode="static",
            version_id=_view_id(source, "static", segments),
            segments=segments,
            fingerprint=fingerprint,
            created_at=_now(),
        )
        self._save_source_state(
            source,
            {
                "schema_version": SOURCE_VIEW_SCHEMA_VERSION,
                "mode": "static",
                "fingerprint": fingerprint.to_dict(),
                "view": view.to_dict(),
            },
        )
        return view

    def _resolve_mutable(self, source: Path) -> QuestionSourceView:
        for _ in range(3):
            opened_stat = source.stat()
            fingerprint = SourceFingerprint.from_stat(opened_stat)
            state = self._load_source_state(source)
            cached = self._cached_view_if_same(source, state, fingerprint, mode="mutable")
            if cached is not None:
                return cached

            key = _source_key(source)
            base = self.snapshots_dir / key / "snapshot.log"
            segment = _copy_range(
                source,
                base,
                start=0,
                end=fingerprint.size,
            )
            after = SourceFingerprint.from_stat(source.stat())
            if after == fingerprint:
                segments = (replace(segment, line_base=1),)
                view = QuestionSourceView(
                    source=str(source),
                    mode="mutable",
                    version_id=_view_id(source, "mutable", segments),
                    segments=segments,
                    fingerprint=fingerprint,
                    created_at=_now(),
                )
                self._save_source_state(
                    source,
                    {
                        "schema_version": SOURCE_VIEW_SCHEMA_VERSION,
                        "mode": "mutable",
                        "fingerprint": fingerprint.to_dict(),
                        "view": view.to_dict(),
                    },
                )
                return view
        raise RuntimeError(f"source changed repeatedly while snapshotting: {source}")

    def _resolve_live(
        self,
        source: Path,
        *,
        live_cut_timeout_seconds: float,
    ) -> QuestionSourceView:
        before = SourceFingerprint.from_stat(source.stat())
        state = self._load_source_state(source)
        raw_view = state.get("view")
        prior_view: QuestionSourceView | None = None
        if isinstance(raw_view, Mapping):
            try:
                candidate = QuestionSourceView.from_mapping(raw_view)
            except (TypeError, ValueError):
                candidate = None
            if (
                candidate is not None
                and candidate.mode == "live"
                and all(Path(item.path).is_file() for item in candidate.segments)
            ):
                prior_view = candidate

        captured_size = int(state.get("captured_size") or 0)
        probe_start = int(state.get("probe_start") or 0)
        probe_sha = str(state.get("probe_sha256") or "")
        append_compatible = bool(
            prior_view is not None
            and before.device == int(state.get("device") or 0)
            and before.inode == int(state.get("inode") or 0)
            and before.size >= captured_size
            and captured_size >= 0
            and (
                captured_size == 0
                or (
                    probe_sha
                    and _hash_range(source, probe_start, captured_size) == probe_sha
                )
            )
        )

        if append_compatible and before.size == captured_size:
            return replace(prior_view, reused=True, fingerprint=before)

        key = _source_key(source)
        now = datetime.now()
        cut_dir = self.live_dir / key
        cut_dir.mkdir(parents=True, exist_ok=True)
        requested_dest = unique_segment_path(
            cut_dir, now, now, prefix="live", suffix=".log"
        )
        fallback_used = False

        def deserialize(payload: dict[str, Any]) -> SourceSegment:
            raw = str(
                payload.get("segment_path")
                or payload.get("path")
                or payload.get("destination")
                or ""
            ).strip()
            candidate = Path(raw).expanduser().resolve() if raw else requested_dest.resolve()
            if not candidate.is_file():
                raise RuntimeError(f"live cut did not produce a stable segment: {candidate}")
            digest, byte_count, lines = _hash_file(candidate)
            return SourceSegment(
                path=str(candidate),
                sha256=digest,
                bytes=byte_count,
                lines=lines,
                source_offset_start=0,
                source_offset_end=byte_count,
            )

        def fallback_capture() -> SourceSegment:
            nonlocal fallback_used
            fallback_used = True
            floor = captured_size if append_compatible else 0
            boundary = _complete_line_boundary(source, before.size, floor)
            if boundary <= floor and prior_view is None:
                boundary = before.size
            return _copy_range(
                source,
                requested_dest,
                start=floor,
                end=max(floor, boundary),
            )

        captured = cooperative_live_cut(
            source,
            request_suffix=_LIVE_REQUEST_SUFFIX,
            done_suffix=_LIVE_DONE_SUFFIX,
            request_payload={"destination": str(requested_dest)},
            deserialize=deserialize,
            direct_cut=fallback_capture,
            timeout_sec=max(0.05, live_cut_timeout_seconds),
            poll_sec=0.02,
        )

        if captured.bytes == 0 and prior_view is not None:
            Path(captured.path).unlink(missing_ok=True)
            return replace(prior_view, reused=True, fingerprint=before)

        if fallback_used:
            source_offset_start = captured_size if append_compatible else 0
            source_offset_end = source_offset_start + captured.bytes
        else:
            source_offset_start = 0
            source_offset_end = captured.bytes

        if append_compatible and source_offset_start == captured_size:
            previous_segments = prior_view.segments if prior_view is not None else ()
        elif prior_view is not None and before.inode != int(state.get("inode") or 0):
            previous_segments = prior_view.segments
        else:
            previous_segments = ()

        line_base = sum(item.lines for item in previous_segments) + 1
        new_segment = replace(
            captured,
            line_base=line_base,
            source_offset_start=source_offset_start,
            source_offset_end=source_offset_end,
        )
        segments = (*previous_segments, new_segment)

        after = SourceFingerprint.from_stat(source.stat())
        if not fallback_used:
            next_captured_size = 0
        else:
            next_captured_size = source_offset_end

        p_start, p_sha = _probe(source, min(next_captured_size, after.size))
        view = QuestionSourceView(
            source=str(source),
            mode="live",
            version_id=_view_id(source, "live", tuple(segments)),
            segments=tuple(segments),
            fingerprint=before,
            created_at=_now(),
        )
        self._save_source_state(
            source,
            {
                "schema_version": SOURCE_VIEW_SCHEMA_VERSION,
                "mode": "live",
                "fingerprint": before.to_dict(),
                "device": after.device,
                "inode": after.inode,
                "captured_size": next_captured_size,
                "probe_start": p_start,
                "probe_sha256": p_sha,
                "view": view.to_dict(),
            },
        )
        return view


__all__ = [
    "QuestionSourceView",
    "SOURCE_VIEW_SCHEMA_VERSION",
    "SourceFingerprint",
    "SourceSegment",
    "SourceVersionStore",
]
