"""Agent-facing capability registry shared by Runtime extensions and adapters.

Capabilities describe *what* an installed extension can do.  The registry does
not decide investigation strategy; hosts such as MCP adapters can list the
available capabilities and explicitly execute one under a caller-provided
safety policy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Mapping, Optional, Tuple


CAPABILITY_SAFETY_LEVELS = ("read", "live_source", "live_action")
CAPABILITY_KINDS = ("query", "action")
_CAPABILITY_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]*(?:\.[a-z][a-z0-9_-]*)+$")


class CapabilityError(RuntimeError):
    """Capability registration, lookup, or execution failed."""


@dataclass(frozen=True)
class CapabilitySpec:
    """Stable metadata projected to Agent adapters such as MCP.

    ``input_schema`` is descriptive JSON-Schema-compatible metadata. TraceCite
    intentionally does not implement a second JSON Schema validator here; the
    executor remains responsible for domain argument validation.
    """

    name: str
    kind: str
    description: str
    input_schema: Mapping[str, Any] = field(default_factory=dict)
    safety: str = "read"
    requires_authorization: bool = False

    def __post_init__(self) -> None:
        name = str(self.name).strip().lower()
        kind = str(self.kind).strip().lower()
        safety = str(self.safety).strip().lower()
        description = str(self.description).strip()
        if not _CAPABILITY_NAME_RE.fullmatch(name):
            raise CapabilityError(
                "capability name 必须是至少两段的小写 dotted name，例如 mobile.ios.collect_logs"
            )
        if kind not in CAPABILITY_KINDS:
            raise CapabilityError(f"capability kind 仅支持 {CAPABILITY_KINDS}")
        if safety not in CAPABILITY_SAFETY_LEVELS:
            raise CapabilityError(f"capability safety 仅支持 {CAPABILITY_SAFETY_LEVELS}")
        if not description:
            raise CapabilityError("capability description 不能为空")
        if not isinstance(self.input_schema, Mapping):
            raise CapabilityError("capability input_schema 必须是 mapping")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "safety", safety)
        object.__setattr__(self, "description", description)
        object.__setattr__(self, "input_schema", dict(self.input_schema))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "description": self.description,
            "input_schema": dict(self.input_schema),
            "safety": self.safety,
            "requires_authorization": self.requires_authorization,
        }


CapabilityExecutor = Callable[[Dict[str, Any]], Any]
_CAPABILITIES: Dict[str, Tuple[CapabilitySpec, CapabilityExecutor]] = {}


def register_capability(
    spec: CapabilitySpec,
    executor: CapabilityExecutor,
    *,
    replace: bool = False,
) -> None:
    if not isinstance(spec, CapabilitySpec):
        raise CapabilityError("spec 必须是 CapabilitySpec")
    if not callable(executor):
        raise CapabilityError("capability executor 必须可调用")
    current = _CAPABILITIES.get(spec.name)
    if current is not None and current[1] is not executor and not replace:
        raise CapabilityError(f"capability {spec.name!r} 已注册")
    _CAPABILITIES[spec.name] = (spec, executor)


def get_capability(name: str) -> CapabilitySpec:
    key = str(name).strip().lower()
    try:
        return _CAPABILITIES[key][0]
    except KeyError as exc:
        raise CapabilityError(f"未知 capability {key!r}") from exc


def list_capabilities() -> list[CapabilitySpec]:
    return [_CAPABILITIES[name][0] for name in sorted(_CAPABILITIES)]


def execute_capability(
    name: str,
    arguments: Optional[Mapping[str, Any]] = None,
    *,
    allow_live_source: bool = False,
    allow_live_action: bool = False,
    authorized: bool = False,
) -> Any:
    """Execute one registered capability under explicit host safety grants.

    Live source/action execution is denied by default.  Authorization is a
    separate gate so a capability may require both a live grant and explicit
    user/host authorization.
    """

    key = str(name).strip().lower()
    try:
        spec, executor = _CAPABILITIES[key]
    except KeyError as exc:
        raise CapabilityError(f"未知 capability {key!r}") from exc
    if arguments is None:
        payload: Dict[str, Any] = {}
    elif isinstance(arguments, Mapping):
        payload = dict(arguments)
    else:
        raise CapabilityError("capability arguments 必须是 mapping")

    if spec.safety == "live_source" and not allow_live_source:
        raise CapabilityError(f"capability {key!r} 需要显式 allow_live_source")
    if spec.safety == "live_action" and not allow_live_action:
        raise CapabilityError(f"capability {key!r} 需要显式 allow_live_action")
    if spec.requires_authorization and not authorized:
        raise CapabilityError(f"capability {key!r} 需要显式 authorization")
    return executor(payload)


__all__ = [
    "CAPABILITY_KINDS",
    "CAPABILITY_SAFETY_LEVELS",
    "CapabilityError",
    "CapabilityExecutor",
    "CapabilitySpec",
    "execute_capability",
    "get_capability",
    "list_capabilities",
    "register_capability",
]
