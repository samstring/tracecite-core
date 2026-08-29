"""Shared transport-only projections over canonical Runtime results.

Projection must never discover new Evidence, reopen source files, or perform
identity verification.  Runtime owns retrieval/materialization/integrity;
integrations only select and encode an already-canonical view.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any, Callable, Mapping, Union

from tracecite.runtime.evidence_ambiguity import scoped_identity_fanout_hints

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


def attach_ambiguity_hints(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Compatibility helper for callers that explicitly request text-only hints.

    This function is intentionally pure: it examines only text already present
    in ``payload`` and performs no source I/O.  The built-in ``project`` path no
    longer calls it; canonical Runtime retrieval owns integrity observations.
    """

    result = copy.deepcopy(dict(payload))
    data = dict(result.get("data") or {})
    text = data.get("text")
    if not isinstance(text, str) or not text:
        return result
    hints = scoped_identity_fanout_hints(text)
    if not hints:
        return result
    data["ambiguity_hints"] = hints
    data["ambiguity_hint_note"] = (
        "Navigation only: multiple sibling scoped entities are visible in this raw evidence. "
        "Keep scope attached to identifiers and verify uniqueness before correlating them; "
        "this hint does not identify a root cause."
    )
    result["data"] = data
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


def _primary_artifact(artifacts: Any) -> list[dict[str, Any]]:
    rows = [dict(item) for item in artifacts or [] if isinstance(item, Mapping)]
    for role in ("matched_records", "filtered_log"):
        selected = next((item for item in rows if item.get("role") == role), None)
        if selected is not None:
            return [selected]
    return rows[:1]


def compact_search_result(
    payload: Mapping[str, Any],
    *,
    max_output_chars: int | None = None,
) -> dict[str, Any]:
    """Project a canonical search Result into a bounded agent-facing view.

    The canonical Runtime result, cache entry, investigation recording, and
    artifacts remain unchanged. The projection removes repeated pointer fields,
    hoists the immutable source and URI base once, trims descriptive coverage,
    and only exposes an artifact path when it is needed to recover omitted
    evidence.
    """

    result = copy.deepcopy(dict(payload))
    if result.get("operation") != "search":
        return result

    original_evidence = [
        dict(item)
        for item in result.get("evidence") or []
        if isinstance(item, Mapping)
    ]
    sources: set[tuple[str, str]] = set()
    for item in original_evidence:
        source_path = str(item.get("source_path") or "")
        digest = str(item.get("sha256") or "")
        if source_path and digest:
            sources.add((source_path, digest))

    shared_source = next(iter(sources)) if len(sources) == 1 else None
    uri_base = (
        f"evidence://sha256/{shared_source[1]}"
        if shared_source is not None
        else None
    )
    evidence_columns = (
        ["ref", "start", "end", "label"]
        if shared_source is not None
        else ["uri", "source_path", "sha256", "start", "end", "label"]
    )
    evidence_rows: list[list[Any]] = []
    for item in original_evidence:
        uri = str(item.get("uri") or "")
        if uri_base is not None and uri.startswith(f"{uri_base}#"):
            identity = uri[len(uri_base) :]
            row = [
                identity,
                item.get("start_line"),
                item.get("end_line"),
                item.get("label") or "",
            ]
        elif uri and shared_source is not None:
            row = [
                uri,
                item.get("start_line"),
                item.get("end_line"),
                item.get("label") or "",
            ]
        elif uri:
            identity = uri
            row = [
                identity,
                item.get("source_path"),
                item.get("sha256"),
                item.get("start_line"),
                item.get("end_line"),
                item.get("label") or "",
            ]
        else:
            continue
        evidence_rows.append(row)

    data = dict(result.get("data") or {})
    data["view"] = "compact"
    if shared_source is not None:
        source_path, digest = shared_source
        data["evidence_source"] = {
            "path": source_path,
            "sha256": digest,
            "uri_base": uri_base,
        }
    result["data"] = data
    result["evidence"] = {
        "columns": evidence_columns,
        "rows": evidence_rows,
    }

    original_coverage = dict(result.get("coverage") or {})
    keep_coverage = (
        "scoped_lines",
        "match_records",
        "match_lines",
        "evidence_returned",
        "evidence_truncated",
    )
    coverage = {
        key: original_coverage[key]
        for key in keep_coverage
        if key in original_coverage
    }
    coverage["evidence_available"] = int(
        original_coverage.get("match_records") or len(original_evidence)
    )
    coverage["evidence_returned"] = len(evidence_rows)
    coverage["evidence_truncated"] = bool(
        original_coverage.get("evidence_truncated", False)
    )
    label_index = evidence_columns.index("label") if "label" in evidence_columns else -1
    if label_index >= 0:
        dedupe_evidence_labels(evidence_rows, label_index=label_index, coverage=coverage)
    result["coverage"] = coverage

    original_artifacts = result.get("artifacts") or []
    result["artifacts"] = (
        _primary_artifact(original_artifacts)
        if coverage["evidence_truncated"]
        else []
    )

    if max_output_chars is None:
        return result

    if len(encoded_json(result)) > max_output_chars:
        # Budget trimming may omit labels or pointers. Account for the recovery
        # artifact before trimming so the final fit calculation includes it.
        result["artifacts"] = _primary_artifact(original_artifacts)

    content_trimmed = False
    label_index = evidence_columns.index("label")
    while len(encoded_json(result)) > max_output_chars:
        labeled = next(
            (row for row in reversed(evidence_rows) if row[label_index]),
            None,
        )
        if labeled is None:
            break
        if not content_trimmed:
            coverage["evidence_content_truncated"] = True
            content_trimmed = True
        labeled[label_index] = ""

    if (
        len(encoded_json(result)) > max_output_chars
        and all(not row[label_index] for row in evidence_rows)
    ):
        evidence_columns.pop(label_index)
        for row in evidence_rows:
            row.pop(label_index)

    evidence_removed = False
    while evidence_rows and len(encoded_json(result)) > max_output_chars:
        if not evidence_removed:
            coverage["evidence_truncated"] = True
            evidence_removed = True
        evidence_rows.pop()
        coverage["evidence_returned"] = len(evidence_rows)

    while result.get("next_queries") and len(encoded_json(result)) > max_output_chars:
        coverage["next_queries_truncated"] = True
        result["next_queries"].pop()

    if len(encoded_json(result)) > max_output_chars:
        raise ValueError(
            f"compact search result cannot fit within {max_output_chars} characters"
        )
    return result


def fit_expand_many_result(
    payload: Mapping[str, Any],
    *,
    max_output_chars: int | None,
) -> dict[str, Any]:
    """Fit an expandable Ledger response without ever slicing serialized JSON."""

    result = copy.deepcopy(dict(payload))
    if max_output_chars is None or len(encoded_json(result)) <= max_output_chars:
        return result

    coverage = dict(result.get("coverage") or {})
    result["coverage"] = coverage
    coverage["output_truncated"] = True
    coverage["truncated"] = True
    result["outcome"] = "unknown"
    contexts = [dict(item) for item in result.get("contexts") or []]
    result["contexts"] = contexts
    evidence = dict(result.get("evidence") or {})
    evidence_columns = list(evidence.get("columns") or [])
    evidence_rows = [list(row) for row in evidence.get("rows") or []]
    evidence = {"columns": evidence_columns, "rows": evidence_rows}
    result["evidence"] = evidence

    while len(encoded_json(result)) > max_output_chars:
        candidates = [item for item in contexts if str(item.get("text") or "")]
        if not candidates:
            break
        item = max(candidates, key=lambda row: len(str(row.get("text") or "")))
        text = str(item.get("text") or "")
        over = len(encoded_json(result)) - max_output_chars
        item["text"] = text[: max(0, len(text) - max(1, over + 16))]
        item["truncated"] = True

    failed_refs = list(coverage.get("failed_refs") or [])
    context_index = evidence_columns.index("context") if "context" in evidence_columns else -1
    ref_index = evidence_columns.index("ref") if "ref" in evidence_columns else -1
    while contexts and len(encoded_json(result)) > max_output_chars:
        removed = contexts.pop()
        context_id = str(removed.get("id") or "")
        retained_rows: list[list[Any]] = []
        for row in evidence_rows:
            if context_index >= 0 and str(row[context_index]) == context_id:
                ref = str(row[ref_index]) if ref_index >= 0 else ""
                if ref and ref not in failed_refs:
                    failed_refs.append(ref)
            else:
                retained_rows.append(row)
        evidence_rows[:] = retained_rows
        coverage["failed_refs"] = failed_refs
        coverage["returned"] = len(evidence_rows)
        coverage["contexts"] = len(contexts)
        coverage["merged_contexts"] = max(0, len(evidence_rows) - len(contexts))

    coverage["text_chars"] = sum(
        len(str(context.get("text") or "")) for context in contexts
    )
    if not evidence_rows:
        result["status"] = "error"
    if len(encoded_json(result)) > max_output_chars:
        raise ValueError(
            f"expand-many result cannot fit within {max_output_chars} characters"
        )
    return result



def project(
    payload: Mapping[str, Any],
    *,
    profile: ProjectionProfile = "agent",
    max_output_chars: int | None = None,
) -> dict[str, Any]:
    """Project canonical Runtime output through the single transport owner.

    Runtime owns Evidence acquisition, materialization and integrity. This
    function owns structural transport shaping only. Named Agent transports
    (portable/stateful/frame) share the same columnar JSON structure; frame
    rendering is a final encoding step in ``agent_profile.render_frame``.
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
    if name in {"full", "canonical"}:
        return canonical
    if name == "survey-brief":
        return apply_survey_brief(canonical)
    if name == "lightweight":
        return lightweight_result(canonical)
    if name in {"agent", "portable-json", "strict-json", "stateful-index", "frame"}:
        operation = str(canonical.get("operation") or "")
        if operation == "search":
            return compact_search_result(canonical, max_output_chars=max_output_chars)
        if operation == "expand_many":
            return fit_expand_many_result(canonical, max_output_chars=max_output_chars)
        if name == "agent":
            return lightweight_result(apply_survey_brief(canonical))
        return canonical
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
    "attach_ambiguity_hints",
    "compact_filter_payload",
    "compact_search_result",
    "fit_expand_many_result",
    "dedupe_evidence_labels",
    "dedupe_survey_coverage",
    "encoded_json",
    "lightweight_result",
    "prefer_smaller_agent_view",
    "project",
]
