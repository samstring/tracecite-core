"""Versioned, domain-neutral identity primitives for Evidence Runtime.

Identity is deliberately layered. A provider record, a real-world event, and a
reduction/group identity are not interchangeable. Provenance follows record
identity; correlation may additionally use event identity; grouping is only a
projection identity and must never replace provenance.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping


SourceVersionKind = Literal["sha256", "cursor", "generation", "mutable"]


def _text(value: object, name: str, *, limit: int = 1024, allow_empty: bool = False) -> str:
    resolved = str(value or "").strip()
    if not resolved and not allow_empty:
        raise ValueError(f"{name} must be non-empty")
    if len(resolved) > limit:
        raise ValueError(f"{name} exceeds {limit} characters")
    return resolved


@dataclass(frozen=True)
class SourceVersion:
    """One observable version of a source.

    ``sha256`` is the canonical immutable file/snapshot identity. ``cursor``
    and ``generation`` are for live/remote sources that provide their own
    stable version boundary. ``mutable`` is explicitly non-immutable and must
    never be used for zero-read coverage hard stops.
    """

    namespace: str
    source: str
    kind: SourceVersionKind
    value: str = ""

    def __post_init__(self) -> None:
        if self.kind not in {"sha256", "cursor", "generation", "mutable"}:
            raise ValueError(f"unsupported source version kind: {self.kind!r}")
        namespace = _text(self.namespace, "source namespace", limit=128).lower()
        source = _text(self.source, "source", limit=2048)
        value = _text(
            self.value,
            "source version value",
            limit=2048,
            allow_empty=self.kind == "mutable",
        )
        if self.kind == "sha256":
            lower = value.lower()
            if len(lower) != 64 or any(ch not in "0123456789abcdef" for ch in lower):
                raise ValueError("sha256 source version must be 64 hex characters")
            value = lower
        if self.kind != "mutable" and not value:
            raise ValueError(f"{self.kind} source version requires a value")
        object.__setattr__(self, "namespace", namespace)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "value", value)

    @property
    def immutable(self) -> bool:
        return self.kind in {"sha256", "cursor", "generation"}

    @property
    def key(self) -> str:
        suffix = self.value if self.value else "live"
        return f"{self.namespace}:{self.source}@{self.kind}:{suffix}"

    def to_dict(self) -> dict[str, object]:
        return {
            "namespace": self.namespace,
            "source": self.source,
            "version": {"kind": self.kind, "value": self.value},
            "immutable": self.immutable,
            "key": self.key,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "SourceVersion":
        version = value.get("version") or {}
        if not isinstance(version, Mapping):
            raise ValueError("source version must be a mapping")
        return cls(
            namespace=str(value.get("namespace") or ""),
            source=str(value.get("source") or ""),
            kind=str(version.get("kind") or "mutable"),  # type: ignore[arg-type]
            value=str(version.get("value") or ""),
        )


@dataclass(frozen=True)
class EvidenceIdentity:
    """Identity layers for one evidence record.

    ``record_id`` is required and owns provenance. ``event_id`` may correlate
    multiple provider records that describe the same real-world occurrence.
    ``group_id`` identifies a reducer/group projection only; it is never a
    substitute for record or source identity.
    """

    record_id: str
    source_version: SourceVersion
    event_id: str = ""
    group_id: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.source_version, SourceVersion):
            raise ValueError("source_version must be SourceVersion")
        object.__setattr__(self, "record_id", _text(self.record_id, "record id", limit=2048))
        object.__setattr__(
            self,
            "event_id",
            _text(self.event_id, "event id", limit=2048, allow_empty=True),
        )
        object.__setattr__(
            self,
            "group_id",
            _text(self.group_id, "group id", limit=2048, allow_empty=True),
        )

    @property
    def record_key(self) -> tuple[str, str]:
        return self.source_version.key, self.record_id

    @property
    def event_key(self) -> tuple[str, str] | None:
        return (self.source_version.namespace, self.event_id) if self.event_id else None

    @property
    def group_key(self) -> str | None:
        return self.group_id or None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "record_id": self.record_id,
            "source_version": self.source_version.to_dict(),
        }
        if self.event_id:
            payload["event_id"] = self.event_id
        if self.group_id:
            payload["group_id"] = self.group_id
        return payload


def file_source_version(source_path: str, sha256: str) -> SourceVersion:
    """Create the canonical version identity used by immutable file evidence."""

    return SourceVersion(
        namespace="file",
        source=str(source_path),
        kind="sha256",
        value=str(sha256),
    )


def pointer_source_key(pointer: Mapping[str, object]) -> str | None:
    """Return a versioned source key for a persisted EvidencePointer mapping."""

    source_path = str(pointer.get("source_path") or "").strip()
    sha256 = str(pointer.get("sha256") or "").strip()
    if not source_path or not sha256:
        return None
    try:
        return file_source_version(source_path, sha256).key
    except ValueError:
        return None


__all__ = [
    "EvidenceIdentity",
    "SourceVersion",
    "SourceVersionKind",
    "file_source_version",
    "pointer_source_key",
]
