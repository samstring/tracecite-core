"""Capability-selected, lossless Agent transport profiles.

Profiles are integration-only views over canonical Runtime Results. They never
change evidence, artifacts, or Runtime schemas; an unsupported capability
falls back to a portable JSON profile rather than silently dropping evidence.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal, Mapping


TransportFormat = Literal["canonical-json", "columnar-json", "frame"]


@dataclass(frozen=True)
class AgentCapabilities:
    """Capabilities declared by one selected Agent host, not a model name."""

    stateful_history: bool = False
    batch_expand: bool = True
    text_frame: bool = False
    strict_json: bool = False


@dataclass(frozen=True)
class AgentProfile:
    """Token transport policy for one selected analysis Agent."""

    name: str
    transport: TransportFormat
    requires_ledger: bool = False
    compact_history: bool = False
    requires: AgentCapabilities = AgentCapabilities()

    def supports(self, capabilities: AgentCapabilities) -> bool:
        return all(
            not required or available
            for required, available in (
                (self.requires.stateful_history, capabilities.stateful_history),
                (self.requires.batch_expand, capabilities.batch_expand),
                (self.requires.text_frame, capabilities.text_frame),
                (self.requires.strict_json, capabilities.strict_json),
            )
        )


_PROFILES: dict[str, AgentProfile] = {
    "canonical": AgentProfile("canonical", "canonical-json"),
    "agent": AgentProfile("agent", "columnar-json"),
    "portable-json": AgentProfile("portable-json", "columnar-json"),
    "strict-json": AgentProfile(
        "strict-json",
        "columnar-json",
        requires=AgentCapabilities(strict_json=True),
    ),
    "stateful-index": AgentProfile(
        "stateful-index",
        "columnar-json",
        requires_ledger=True,
        compact_history=True,
        requires=AgentCapabilities(stateful_history=True, batch_expand=True),
    ),
    "frame": AgentProfile(
        "frame",
        "frame",
        requires_ledger=True,
        compact_history=True,
        requires=AgentCapabilities(
            stateful_history=True,
            batch_expand=True,
            text_frame=True,
        ),
    ),
}


def profile_names() -> tuple[str, ...]:
    """Return stable built-in profile names for host configuration."""

    return tuple(_PROFILES)


def get_agent_profile(name: str) -> AgentProfile:
    """Return a named built-in profile or fail with valid choices."""

    try:
        return _PROFILES[name]
    except KeyError as exc:
        choices = ", ".join(profile_names())
        raise ValueError(f"unknown agent profile {name!r}; choose one of: {choices}") from exc


def select_agent_profile(
    name: str,
    capabilities: AgentCapabilities | None = None,
) -> AgentProfile:
    """Resolve ``auto`` safely or validate an explicitly selected profile.

    ``auto`` chooses the smallest lossless transport the host explicitly
    declares it can consume: TCF frame first, then stateful columnar JSON,
    then the portable Agent JSON projection. A host that does not declare
    ``text_frame`` therefore never receives TCF unexpectedly.
    """

    available = capabilities or AgentCapabilities()
    if name == "auto":
        if _PROFILES["frame"].supports(available):
            return _PROFILES["frame"]
        if _PROFILES["stateful-index"].supports(available):
            return _PROFILES["stateful-index"]
        return _PROFILES["agent"]
    if name == "portable-json":
        return _PROFILES["portable-json"]
    if name == "agent":
        return _PROFILES["agent"]
    profile = get_agent_profile(name)
    if not profile.supports(available):
        raise ValueError(
            f"agent profile {name!r} requires capabilities not declared by this host"
        )
    return profile


def _clean_cell(value: Any) -> str:
    return str(value if value is not None else "").replace("\t", " ").replace("\n", " ")


def _json_cell(value: Any) -> str:
    """Encode structured frame metadata without inventing a second schema."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def render_frame(payload: Mapping[str, Any]) -> str:
    """Render a compact search or expand-many view as a readable TCF frame.

    The frame is a transport encoding, not a new canonical schema. It carries
    the same columnar rows and Coverage as the JSON view and must also preserve
    decision-critical Evidence metadata such as actionable retrieval gaps,
    correlation constraints, integrity observations, progress and routing.
    Hosts that do not declare ``text_frame`` support fall back to JSON.
    """

    operation = str(payload.get("operation") or "unknown")
    status = str(payload.get("status") or "error")
    outcome = str(payload.get("outcome") or "unknown")
    lines = [f"@TCF 1 {operation} status={status} outcome={outcome}"]
    data = payload.get("data") or {}
    if not isinstance(data, Mapping):
        data = {}

    result_id = str(data.get("result_id") or payload.get("result_id") or "")
    if result_id:
        lines.append(f"@R {result_id}")

    source = data.get("evidence_source") or {}
    if isinstance(source, Mapping) and source.get("uri_base"):
        lines.append(f"@SRC {_clean_cell(source['uri_base'])}")

    coverage = payload.get("coverage") or {}
    if isinstance(coverage, Mapping):
        scalar_coverage = [
            f"{key}={_clean_cell(value)}"
            for key, value in sorted(coverage.items())
            if not isinstance(value, (list, dict))
        ]
        if scalar_coverage:
            lines.append("@COV " + " ".join(scalar_coverage))

    # Compact frame transport must never hide a Runtime-declared evidence or
    # integrity obligation.  These remain structured JSON fragments so the
    # frame is only an encoding choice; it does not reinterpret their meaning.
    frame_metadata = (
        ("@ACT", data.get("actionable_retrieval")),
        ("@CONSTRAINT", data.get("correlation_constraints")),
        ("@INTEGRITY", data.get("evidence_integrity")),
        ("@PROGRESS", data.get("progress")),
        ("@ROUTE", data.get("routing")),
        ("@SIGNAL", data.get("signal_hints")),
        ("@GAP", payload.get("missing_evidence")),
        ("@NEXT", payload.get("next_queries")),
        ("@VERIFY", payload.get("verification")),
    )
    for marker, value in frame_metadata:
        if value not in (None, "", [], {}, ()):
            lines.append(f"{marker} {_json_cell(value)}")

    evidence = payload.get("evidence") or {}
    if isinstance(evidence, Mapping):
        columns = evidence.get("columns") or []
        rows = evidence.get("rows") or []
        if columns:
            lines.append("@E " + "\t".join(_clean_cell(column) for column in columns))
            for row in rows:
                if isinstance(row, list):
                    lines.append("\t".join(_clean_cell(cell) for cell in row))

    contexts = payload.get("contexts") or []
    if isinstance(contexts, list):
        for context in contexts:
            if not isinstance(context, Mapping):
                continue
            context_id = _clean_cell(context.get("id"))
            context_lines = context.get("lines") or []
            start = _clean_cell(context_lines[0] if len(context_lines) > 0 else "")
            end = _clean_cell(context_lines[1] if len(context_lines) > 1 else "")
            truncated = _clean_cell(context.get("truncated", False))
            lines.append(f"@CTX {context_id} {start}-{end} truncated={truncated}")
            lines.extend(str(context.get("text") or "").splitlines())
            lines.append("@ENDCTX")

    warnings = payload.get("warnings") or []
    for warning in warnings:
        lines.append("@WARN " + _clean_cell(warning))
    error = payload.get("error") or {}
    if isinstance(error, Mapping):
        message = error.get("message")
        if message:
            lines.append("@ERR " + _clean_cell(message))
    return "\n".join(lines)


__all__ = [
    "AgentCapabilities",
    "AgentProfile",
    "TransportFormat",
    "get_agent_profile",
    "profile_names",
    "render_frame",
    "select_agent_profile",
]
