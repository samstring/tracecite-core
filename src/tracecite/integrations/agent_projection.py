"""Shared agent-facing projections over canonical tool results."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any, Callable, Mapping, Union

DEFAULT_AGENT_MAX_OUTPUT_CHARS = 12_000
DEFAULT_FILTER_MAX_LINE_CHARS = 1024
DEFAULT_AGENT_MAX_EVIDENCE = 30
Projection = Callable[[Mapping[str, Any]], Mapping[str, Any]]
ProjectionProfile = Union[str, Projection]
_LINE_PREFIX_RE = re.compile(r"^(?P<line>\d+):\s?(?P<text>.*)$")


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


def _compact_progress(progress: Mapping[str, Any]) -> dict[str, Any]:
    """Keep only progress fields that can change the Agent's next action."""

    compact: dict[str, Any] = {}
    for key in ("coverage_status", "readiness"):
        value = progress.get(key)
        if value not in (None, "", "unknown"):
            compact[key] = value

    for key in (
        "frontier_exhausted",
        "source_complete",
        "scope_exhausted",
        "retrieval_complete",
        "ready_for_reasoning",
    ):
        if progress.get(key) is True:
            compact[key] = True

    for key in ("actionable_gaps", "consecutive_no_growth"):
        value = progress.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            compact[key] = value

    delta = progress.get("delta")
    if isinstance(delta, Mapping):
        delta_view = {
            key: value
            for key, value in delta.items()
            if key == "grew" or bool(value)
        }
        if delta_view:
            compact["delta"] = delta_view

    requirements = progress.get("requirements")
    if isinstance(requirements, Mapping) and int(requirements.get("total") or 0) > 0:
        compact["requirements"] = dict(requirements)

    stop = progress.get("stop")
    if isinstance(stop, Mapping):
        recommended = bool(stop.get("recommended"))
        reason = str(stop.get("reason") or "")
        if recommended or (reason and reason != "evidence_grew"):
            compact["stop"] = dict(stop)
    return compact


def _compact_routing(routing: Mapping[str, Any]) -> dict[str, Any]:
    """Expose route semantics without repeating router accounting every turn."""

    return {
        key: copy.deepcopy(routing[key])
        for key in ("mode", "next_mode", "reasons")
        if key in routing and routing[key] not in (None, "", [], ())
    }


def _qualify_expand_text(result: dict[str, Any]) -> None:
    """Make expand lines self-citing without a redundant visible-line-ref list."""

    if result.get("operation") != "expand":
        return
    data = dict(result.get("data") or {})
    text = data.get("text")
    if not isinstance(text, str) or not text:
        return
    evidence = result.get("evidence") or []
    source_name = ""
    if isinstance(evidence, list):
        first = next((item for item in evidence if isinstance(item, Mapping)), None)
        if isinstance(first, Mapping):
            source_name = Path(str(first.get("source_path") or "")).name
    if not source_name:
        return

    qualified: list[str] = []
    changed = False
    for line in text.splitlines():
        match = _LINE_PREFIX_RE.match(line)
        if match is None:
            qualified.append(line)
            continue
        qualified.append(f"{source_name}:{match.group('line')} {match.group('text')}")
        changed = True
    if changed:
        data["text"] = "\n".join(qualified) + ("\n" if text.endswith("\n") else "")
        data.pop("visible_line_refs", None)
        result["data"] = data


def lightweight_result(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Drop recoverable bookkeeping from the Agent transport view.

    Canonical results, InvestigationState and evidence artifacts keep the full
    accounting. The Agent only needs evidence, provenance, actionable progress
    and stop/routing semantics on every turn; repeating cache/budget/revision
    bookkeeping grows conversation context without improving reasoning.
    """

    result = copy.deepcopy(dict(payload))
    for key in (
        "hypotheses",
        "verification",
        "artifacts",
        "missing_evidence",
        "next_queries",
        "warnings",
    ):
        if not result.get(key):
            result.pop(key, None)

    # The linked InvestigationState remains canonical/recoverable outside the
    # model turn. IDs/revision/path do not help the Agent interpret evidence.
    result.pop("investigation", None)

    data = dict(result.get("data") or {})
    for key in (
        "run_id",
        "manifest_path",
        "manifest_sha256",
        "input_lineage",
        "budget",
        "cache",
    ):
        data.pop(key, None)

    progress = data.get("progress")
    if isinstance(progress, Mapping):
        compact_progress = _compact_progress(progress)
        if compact_progress:
            data["progress"] = compact_progress
        else:
            data.pop("progress", None)

    routing = data.get("routing")
    if isinstance(routing, Mapping):
        compact_routing = _compact_routing(routing)
        if compact_routing:
            data["routing"] = compact_routing
        else:
            data.pop("routing", None)

    if data:
        result["data"] = data
    else:
        result.pop("data", None)

    _qualify_expand_text(result)
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
