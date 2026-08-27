"""Stable public contracts between TraceCite and domain extensions.

The objects in this module are deliberately independent from Agent transport
formats.  Domain extensions describe facts and capabilities; Runtime remains
free to change orchestration, context projection, token policy, MCP adapters,
and other host-facing implementation details without requiring extension
rewrites.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Generic, Mapping, Optional, Tuple, TypeVar, Union

from tracecite.runtime.capabilities import CapabilityExecutor, CapabilitySpec


EXTENSION_PROTOCOL_VERSION = "2"
CAPABILITY_PROTOCOL_VERSIONS: Mapping[str, int] = {
    "core.plugins": 1,
    "agent.capability": 1,
    "runtime.assertion": 1,
    "runtime.report": 1,
    "runtime.scenario": 1,
}


class ContractError(ValueError):
    """A public extension contract is malformed."""


def _required_text(value: Any, field_name: str, *, limit: int = 512) -> str:
    text = str(value or "").strip()
    if not text:
        raise ContractError(f"{field_name} 不能为空")
    if len(text) > limit:
        raise ContractError(f"{field_name} 长度不能超过 {limit}")
    return text


def _optional_text(value: Any, field_name: str, *, limit: int = 512) -> str:
    text = str(value or "").strip()
    if len(text) > limit:
        raise ContractError(f"{field_name} 长度不能超过 {limit}")
    return text


def _non_negative(value: Optional[int], field_name: str) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContractError(f"{field_name} 必须是非负整数")
    return value


@dataclass(frozen=True)
class EvidenceRef:
    """Domain-facing reference to evidence without binding to Agent URI syntax."""

    source_id: str
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    digest: str = ""
    digest_algorithm: str = "sha256"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        source_id = _required_text(self.source_id, "evidence.source_id", limit=1024)
        start = self.start_line
        end = self.end_line
        if start is not None and (isinstance(start, bool) or not isinstance(start, int) or start <= 0):
            raise ContractError("evidence.start_line 必须是正整数")
        if end is not None and (isinstance(end, bool) or not isinstance(end, int) or end <= 0):
            raise ContractError("evidence.end_line 必须是正整数")
        if end is not None and start is None:
            raise ContractError("evidence.end_line 不能脱离 start_line")
        if start is not None and end is not None and end < start:
            raise ContractError("evidence.end_line 不能小于 start_line")
        if not isinstance(self.metadata, Mapping):
            raise ContractError("evidence.metadata 必须是 mapping")
        object.__setattr__(self, "source_id", source_id)
        object.__setattr__(self, "digest", _optional_text(self.digest, "evidence.digest", limit=512))
        object.__setattr__(
            self,
            "digest_algorithm",
            _required_text(self.digest_algorithm, "evidence.digest_algorithm", limit=64).lower(),
        )
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_id": self.source_id,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "digest": self.digest,
            "digest_algorithm": self.digest_algorithm,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class Coverage:
    """Portable completeness metadata shared by domain capabilities."""

    complete: Optional[bool] = None
    scanned: Optional[int] = None
    returned: Optional[int] = None
    omitted: Optional[int] = None
    truncated: bool = False
    reasons: Tuple[str, ...] = ()
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.complete is not None and not isinstance(self.complete, bool):
            raise ContractError("coverage.complete 必须是 bool 或 null")
        if not isinstance(self.details, Mapping):
            raise ContractError("coverage.details 必须是 mapping")
        object.__setattr__(self, "scanned", _non_negative(self.scanned, "coverage.scanned"))
        object.__setattr__(self, "returned", _non_negative(self.returned, "coverage.returned"))
        object.__setattr__(self, "omitted", _non_negative(self.omitted, "coverage.omitted"))
        object.__setattr__(self, "reasons", tuple(str(item)[:256] for item in self.reasons if str(item)))
        object.__setattr__(self, "details", dict(self.details))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "complete": self.complete,
            "scanned": self.scanned,
            "returned": self.returned,
            "omitted": self.omitted,
            "truncated": bool(self.truncated),
            "reasons": list(self.reasons),
            "details": dict(self.details),
        }


@dataclass(frozen=True)
class DomainEvent:
    """Small cross-domain fact model; relevance is intentionally not stored here."""

    type: str
    timestamp: str = ""
    severity: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)
    evidence: Tuple[EvidenceRef, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.attributes, Mapping):
            raise ContractError("event.attributes 必须是 mapping")
        refs = tuple(self.evidence)
        if any(not isinstance(item, EvidenceRef) for item in refs):
            raise ContractError("event.evidence 只能包含 EvidenceRef")
        object.__setattr__(self, "type", _required_text(self.type, "event.type", limit=256).lower())
        object.__setattr__(self, "timestamp", _optional_text(self.timestamp, "event.timestamp", limit=128))
        object.__setattr__(self, "severity", _optional_text(self.severity, "event.severity", limit=64).lower())
        object.__setattr__(self, "attributes", dict(self.attributes))
        object.__setattr__(self, "evidence", refs)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "timestamp": self.timestamp,
            "severity": self.severity,
            "attributes": dict(self.attributes),
            "evidence": [item.to_dict() for item in self.evidence],
        }


@dataclass(frozen=True)
class SourceDescriptor:
    id: str
    kind: str
    mutable: bool = False
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.attributes, Mapping):
            raise ContractError("source.attributes 必须是 mapping")
        object.__setattr__(self, "id", _required_text(self.id, "source.id", limit=1024))
        object.__setattr__(self, "kind", _required_text(self.kind, "source.kind", limit=128).lower())
        object.__setattr__(self, "attributes", dict(self.attributes))


@dataclass(frozen=True)
class SourceCursor:
    """Opaque source progress token owned by the supplying domain capability."""

    source_id: str
    token: Any

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_id", _required_text(self.source_id, "cursor.source_id", limit=1024))


T = TypeVar("T")


@dataclass(frozen=True)
class SourceChunk(Generic[T]):
    source: SourceDescriptor
    records: Tuple[T, ...] = ()
    next_cursor: Optional[SourceCursor] = None
    coverage: Coverage = field(default_factory=Coverage)

    def __post_init__(self) -> None:
        if not isinstance(self.source, SourceDescriptor):
            raise ContractError("source_chunk.source 必须是 SourceDescriptor")
        if self.next_cursor is not None and self.next_cursor.source_id != self.source.id:
            raise ContractError("source_chunk.next_cursor 必须属于同一个 source")
        if not isinstance(self.coverage, Coverage):
            raise ContractError("source_chunk.coverage 必须是 Coverage")
        object.__setattr__(self, "records", tuple(self.records))


@dataclass(frozen=True)
class CapabilityResult(Generic[T]):
    """Uniform execution envelope for extension capabilities.

    ``status`` is execution status only. Epistemic outcomes such as supported,
    contradicted, or unknown remain Runtime Finding semantics.
    """

    status: str
    value: Optional[T] = None
    evidence: Tuple[EvidenceRef, ...] = ()
    coverage: Coverage = field(default_factory=Coverage)
    diagnostics: Tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        status = str(self.status or "").strip().lower()
        if status not in {"ok", "error"}:
            raise ContractError("capability_result.status 仅支持 ok / error")
        refs = tuple(self.evidence)
        if any(not isinstance(item, EvidenceRef) for item in refs):
            raise ContractError("capability_result.evidence 只能包含 EvidenceRef")
        if not isinstance(self.coverage, Coverage):
            raise ContractError("capability_result.coverage 必须是 Coverage")
        diagnostics = tuple(dict(item) for item in self.diagnostics)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "evidence", refs)
        object.__setattr__(self, "diagnostics", diagnostics)


@dataclass(frozen=True)
class ExtensionManifest:
    id: str
    version: str
    domain: str
    description: str = ""
    protocol_version: str = EXTENSION_PROTOCOL_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _required_text(self.id, "extension.id", limit=256).lower())
        object.__setattr__(self, "version", _required_text(self.version, "extension.version", limit=128))
        object.__setattr__(self, "domain", _required_text(self.domain, "extension.domain", limit=128).lower())
        object.__setattr__(self, "description", _optional_text(self.description, "extension.description", limit=1024))
        protocol = _required_text(self.protocol_version, "extension.protocol_version", limit=32)
        if protocol != EXTENSION_PROTOCOL_VERSION:
            raise ContractError(
                f"extension protocol 需要 {EXTENSION_PROTOCOL_VERSION}，实际为 {protocol}"
            )
        object.__setattr__(self, "protocol_version", protocol)


@dataclass(frozen=True)
class CorePluginCapability:
    name: str
    register: Callable[[Any], None]
    version: int = 1
    kind: str = field(init=False, default="core.plugins")

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _required_text(self.name, "core_plugin.name", limit=256).lower())
        if not callable(self.register):
            raise ContractError("core_plugin.register 必须可调用")
        _validate_capability_version(self.kind, self.version)


@dataclass(frozen=True)
class AgentCapability:
    spec: CapabilitySpec
    executor: CapabilityExecutor
    version: int = 1
    kind: str = field(init=False, default="agent.capability")

    def __post_init__(self) -> None:
        if not isinstance(self.spec, CapabilitySpec):
            raise ContractError("agent capability spec 必须是 CapabilitySpec")
        if not callable(self.executor):
            raise ContractError("agent capability executor 必须可调用")
        _validate_capability_version(self.kind, self.version)

    @property
    def name(self) -> str:
        return self.spec.name


@dataclass(frozen=True)
class AssertionCapability:
    name: str
    evaluator: Any
    version: int = 1
    kind: str = field(init=False, default="runtime.assertion")

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _required_text(self.name, "assertion.name", limit=256).lower())
        if not callable(self.evaluator):
            raise ContractError("assertion.evaluator 必须可调用")
        _validate_capability_version(self.kind, self.version)


@dataclass(frozen=True)
class ReportCapability:
    name: str
    outputter: Any
    version: int = 1
    kind: str = field(init=False, default="runtime.report")

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _required_text(self.name, "report.name", limit=256).lower())
        if not callable(self.outputter):
            raise ContractError("report.outputter 必须可调用")
        _validate_capability_version(self.kind, self.version)


@dataclass(frozen=True)
class ScenarioCapability:
    """Domain scenario support without exposing ScenarioRuntime as extension API."""

    name: str
    load_profile: Optional[Callable[..., Any]] = None
    resolve_scenario_pattern: Optional[Callable[..., str]] = None
    context_files: Optional[Callable[..., Any]] = None
    loaded_plugins: Optional[Callable[..., Any]] = None
    runtime_versions: Optional[Callable[..., Any]] = None
    allow_live_source: bool = False
    allow_actions: bool = False
    version: int = 1
    kind: str = field(init=False, default="runtime.scenario")

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _required_text(self.name, "scenario.name", limit=256).lower())
        for field_name in (
            "load_profile",
            "resolve_scenario_pattern",
            "context_files",
            "loaded_plugins",
            "runtime_versions",
        ):
            value = getattr(self, field_name)
            if value is not None and not callable(value):
                raise ContractError(f"scenario.{field_name} 必须可调用或为 null")
        _validate_capability_version(self.kind, self.version)


ExtensionContribution = Union[
    CorePluginCapability,
    AgentCapability,
    AssertionCapability,
    ReportCapability,
    ScenarioCapability,
]


def _validate_capability_version(kind: str, version: int) -> None:
    if isinstance(version, bool) or not isinstance(version, int) or version <= 0:
        raise ContractError("capability version 必须是正整数")
    supported = CAPABILITY_PROTOCOL_VERSIONS.get(kind)
    if supported is None:
        raise ContractError(f"未知 capability kind: {kind}")
    if version != supported:
        raise ContractError(f"capability {kind} 需要版本 {supported}，实际为 {version}")


@dataclass(frozen=True)
class TraceCiteExtension:
    manifest: ExtensionManifest
    capabilities: Tuple[ExtensionContribution, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.manifest, ExtensionManifest):
            raise ContractError("extension.manifest 必须是 ExtensionManifest")
        capabilities = tuple(self.capabilities)
        supported_types = (
            CorePluginCapability,
            AgentCapability,
            AssertionCapability,
            ReportCapability,
            ScenarioCapability,
        )
        if any(not isinstance(item, supported_types) for item in capabilities):
            raise ContractError("extension.capabilities 含有未知 capability 类型")
        identities = set()
        for item in capabilities:
            identity = (item.kind, item.name)
            if identity in identities:
                raise ContractError(f"extension capability 重复: {item.kind}:{item.name}")
            identities.add(identity)
        object.__setattr__(self, "capabilities", capabilities)

    def capability_summary(self) -> Tuple[Dict[str, Any], ...]:
        return tuple(
            {"kind": item.kind, "name": item.name, "version": item.version}
            for item in self.capabilities
        )


__all__ = [
    "EXTENSION_PROTOCOL_VERSION",
    "CAPABILITY_PROTOCOL_VERSIONS",
    "ContractError",
    "EvidenceRef",
    "Coverage",
    "DomainEvent",
    "SourceDescriptor",
    "SourceCursor",
    "SourceChunk",
    "CapabilityResult",
    "ExtensionManifest",
    "CorePluginCapability",
    "AgentCapability",
    "AssertionCapability",
    "ReportCapability",
    "ScenarioCapability",
    "ExtensionContribution",
    "TraceCiteExtension",
]
