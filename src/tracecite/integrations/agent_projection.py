"""Shared agent-facing projections over canonical tool results."""

from __future__ import annotations

import copy
import json
from typing import Any, Callable, Mapping, Union

DEFAULT_AGENT_MAX_OUTPUT_CHARS = 12_000
DEFAULT_FILTER_MAX_LINE_CHARS = 1024
DEFAULT_AGENT_MAX_EVIDENCE = 30
Projection = Callable[[Mapping[str, Any]], Mapping[str, Any]]
ProjectionProfile = Union[str, Projection]


def encoded_json(payload: Any) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def prefer_smaller_agent_view(candidate: Mapping[str, Any], fallback: Mapping[str, Any]) -> dict[str, Any]:
    """Return ``candidate`` only when it is strictly cheaper to serialize.

    Agent-context optimizations are optional projections over recoverable
    canonical data. A projection that saves too little payload to cover its
    own metadata should not make the Agent turn larger. Ties deliberately keep
    the fallback so enabling an optimization never increases model-visible
    transport cost.
    """

    candidate_view = dict(candidate)
    fallback_view = dict(fallback)
    if len(encoded_json(candidate_view)) < len(encoded_json(fallback_view)):
        return candidate_view
    return fallback_view


def dedupe_survey_coverage(coverage: Mapping[str, Any]) -> dict[str, Any]:
    """Collapse synonymous survey coverage keys for agent transport."""

    aliases = {
        "scanned_lines": "lines_scanned",
        "scanned_records": "records_scanned",
        "records_scoped": "scoped_records",
        "lines_scoped": "scoped_lines",
    }
    deduped: dict[str, Any] = {}
    for key, value in coverage.items():
        canonical = aliases.get(key, key)
        if canonical not in deduped:
            deduped[canonical] = value
    return deduped


def apply_survey_brief(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Project a canonical survey Result into a token-efficient agent view."""

    result = copy.deepcopy(dict(payload))
    if result.get("operation") != "survey":
        return result

    data = dict(result.get("data") or {})
    data["brief"] = True
    for template in data.get("top_templates") or []:
        if not isinstance(template, Mapping):
            continue
        for sample in template.get("samples") or []:
            if isinstance(sample, Mapping):
                sample.pop("text", None)
    for key in ("work_input", "snapshot_path"):
        data.pop(key, None)
    result["data"] = data

    evidence = []
    for item in result.get("evidence") or []:
        if not isinstance(item, Mapping):
            continue
        row = dict(item)
        metadata = dict(row.get("metadata") or {})
        metadata.pop("text", None)
        if metadata:
            row["metadata"] = metadata
        else:
            row.pop("metadata", None)
        label = str(row.get("label") or "")
        if label:
            row["label"] = label[:80]
        evidence.append(row)
    result["evidence"] = evidence
    result["coverage"] = dedupe_survey_coverage(result.get("coverage") or {})
    return result


def dedupe_evidence_labels(
    evidence_rows: list[list[Any]],
    *,
    label_index: int,
    coverage: dict[str, Any],
) -> None:
    """Hoist or omit repeated search labels inside compact evidence rows."""

    labels = [
        str(row[label_index])
        for row in evidence_rows
        if label_index < len(row) and row[label_index]
    ]
    if not labels:
        return
    unique = set(labels)
    if len(unique) == 1:
        coverage["shared_label"] = labels[0]
        for row in evidence_rows:
            if label_index < len(row):
                row[label_index] = ""
        return
    previous = None
    for row in evidence_rows:
        if label_index >= len(row):
            continue
        current = row[label_index]
        if current and current == previous:
            row[label_index] = ""
        elif current:
            previous = current


def lightweight_result(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Drop empty investigation envelope fields from agent transport."""

    result = copy.deepcopy(dict(payload))
    for key in ("hypotheses", "verification"):
        if not result.get(key):
            result.pop(key, None)
    artifacts = result.get("artifacts") or []
    if not artifacts:
        result.pop("artifacts", None)
    data = dict(result.get("data") or {})
    for key in ("run_id", "manifest_path", "manifest_sha256", "input_lineage"):
        data.pop(key, None)
    if data:
        result["data"] = data
    else:
        result.pop("data", None)
    return result


def project(
    payload: Mapping[str, Any],
    *,
    profile: ProjectionProfile = "agent",
) -> dict[str, Any]:
    """Project canonical Runtime output for an upper-layer consumer.

    The Runtime owns canonical Evidence and recovery. Integrations own the
    transport view. ``profile='agent'`` applies the conservative built-in
    token projection, ``profile='full'`` returns a detached canonical view,
    and a callable lets Mobile/MCP/third-party hosts define their own view
    without adding another Core API or forking Runtime semantics.
    """

    if not isinstance(payload, Mapping):
        raise TypeError("project payload must be a mapping")
    canonical = copy.deepcopy(dict(payload))
    if callable(profile):
        projected = profile(canonical)
        if not isinstance(projected, Mapping):
            raise TypeError("custom projection must return a mapping")
        return copy.deepcopy(dict(projected))
    name = str(profile or "").strip().lower()
    if name == "full":
        return canonical
    if name == "agent":
        return lightweight_result(apply_survey_brief(canonical))
    raise ValueError(f"unsupported projection profile: {profile!r}")


def compact_filter_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return a bounded mobile filter view; full text stays in records_path."""

    source = dict(payload)
    keep = (
        "match_records",
        "match_lines",
        "scope",
        "time_from",
        "time_to",
        "tag",
        "pattern",
        "records_path",
        "hits_path",
        "templates_path",
        "unmatched_summary",
        "term_usage",
        "lines_truncated",
        "max_line_chars",
    )
    view = {key: source[key] for key in keep if key in source and source[key] is not None}
    view["view"] = "agent"
    view["recovery"] = (
        "Do not Read output_path directly. Use records_path with "
        "tracecite-core search --compact or expand for full lines."
    )
    if source.get("output_path"):
        view["output_path"] = source["output_path"]
    return view


__all__ = [
    "DEFAULT_AGENT_MAX_EVIDENCE",
    "DEFAULT_AGENT_MAX_OUTPUT_CHARS",
    "DEFAULT_FILTER_MAX_LINE_CHARS",
    "Projection",
    "ProjectionProfile",
    "apply_survey_brief",
    "compact_filter_payload",
    "dedupe_evidence_labels",
    "dedupe_survey_coverage",
    "encoded_json",
    "lightweight_result",
    "prefer_smaller_agent_view",
    "project",
]
