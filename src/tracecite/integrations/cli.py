"""Command-line interface and bounded Agent adapter for TraceCite.

Default commands serialize the public Runtime Result unchanged. Opt-in compact
views and the Evidence Ledger keep the canonical Result and immutable evidence
recoverable outside the Agent response.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from tracecite import __version__
from tracecite.extension import available_runtimes, get_runtime, load_extensions
from tracecite.runtime.investigation import (
    FINDING_OUTCOMES,
    STOP_KINDS,
    InvestigationStore,
)
from tracecite.runtime.investigation_summary import summarize_investigation
from tracecite.runtime.investigation_compare import (
    compare_investigations,
    timeline_investigation,
)
from tracecite.runtime.schema import AgentResult
from tracecite.runtime.tools import (
    expand,
    probe,
    probe_format,
    run,
    sample,
    search,
    survey,
    verify,
)

from .agent_profile import get_agent_profile, profile_names, render_frame
from .agent_projection import (
    DEFAULT_AGENT_MAX_EVIDENCE,
    DEFAULT_AGENT_MAX_OUTPUT_CHARS,
    DEFAULT_FILTER_MAX_LINE_CHARS,
    apply_survey_brief,
    dedupe_evidence_labels,
    encoded_json,
    lightweight_result,
)
from .evidence_ledger import EvidenceLedger, expand_many as expand_many_from_ledger


MIN_COMPACT_OUTPUT_CHARS = 1024


def _compact_output_chars(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < MIN_COMPACT_OUTPUT_CHARS:
        raise argparse.ArgumentTypeError(
            f"must be at least {MIN_COMPACT_OUTPUT_CHARS} characters"
        )
    return parsed


def _add_investigation_link_args(parser: argparse.ArgumentParser) -> None:
    """Add optional execution-record links without changing old defaults."""

    parser.add_argument(
        "--investigation-path",
        metavar="PATH",
        help="optionally record a bounded execution in an InvestigationState",
    )
    parser.add_argument("--hypothesis-id", metavar="ID")
    parser.add_argument("--test-id", metavar="ID")


def _add_cache_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--no-cache",
        dest="cache",
        action="store_false",
        default=True,
        help="bypass the deterministic cache for this read-only operation",
    )


def build_parser(*, prog: str = "tracecite") -> argparse.ArgumentParser:
    """Build the ``tracecite`` argument parser.

    Defaults mirror the function signatures in :mod:`tracecite.runtime.tools` so
    invoking a command from a shell has the same semantics as calling the tool
    directly.
    """

    parser = argparse.ArgumentParser(
        prog=prog,
        description="Extensible evidence tools for AI agents.",
    )
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    probe_parser = sub.add_parser("probe", help="inspect source files")
    probe_parser.add_argument("input", metavar="INPUT", help="file or directory to inspect")
    probe_parser.add_argument("--glob", default="*", help="directory match pattern (default: *)")
    probe_parser.add_argument(
        "--recursive",
        action="store_true",
        help="recurse into matching subdirectories",
    )
    probe_parser.add_argument(
        "--segmenter",
        default="auto",
        help="record segmenter name (default: auto)",
    )
    _add_investigation_link_args(probe_parser)
    _add_cache_arg(probe_parser)

    search_parser = sub.add_parser("search", help="search one source and return evidence pointers")
    search_parser.add_argument("input", metavar="INPUT", help="source file to search")
    search_parser.add_argument("query", help="literal text or regular expression")
    search_parser.add_argument(
        "--regex",
        action="store_true",
        help="interpret QUERY as a regular expression",
    )
    search_parser.add_argument(
        "--out",
        "--output",
        "--output-path",
        dest="output_path",
        metavar="PATH",
        help="write filtered output to PATH",
    )
    snapshot = search_parser.add_mutually_exclusive_group()
    snapshot.add_argument(
        "--snapshot",
        dest="snapshot",
        action="store_true",
        help="freeze the source before searching (default)",
    )
    snapshot.add_argument(
        "--no-snapshot",
        dest="snapshot",
        action="store_false",
        help="search without first freezing the source",
    )
    search_parser.set_defaults(snapshot=True)
    search_parser.add_argument(
        "--segmenter",
        default="auto",
        help="record segmenter name (default: auto)",
    )
    search_parser.add_argument("--last", metavar="DURATION", help="restrict to the latest duration")
    search_parser.add_argument("--since", metavar="TIME", help="restrict to records since TIME")
    search_parser.add_argument("--until", metavar="TIME", help="restrict to records until TIME")
    search_parser.add_argument(
        "--fold",
        action="store_true",
        help="emit repeated-line template artifacts",
    )
    search_parser.add_argument(
        "--compact",
        action="store_true",
        help=(
            "emit a bounded agent view with reconstructable evidence "
            "URIs, coverage, and recovery metadata"
        ),
    )
    search_parser.add_argument(
        "--max-output-chars",
        type=_compact_output_chars,
        metavar="N",
        help=(
            f"bound the compact JSON document structurally (minimum {MIN_COMPACT_OUTPUT_CHARS}; "
            f"default {DEFAULT_AGENT_MAX_OUTPUT_CHARS} for agent profiles; implies --compact)"
        ),
    )
    search_parser.add_argument(
        "--max-evidence",
        type=int,
        default=None,
        metavar="N",
        help=(
            f"maximum evidence rows in the agent view "
            f"(default {DEFAULT_AGENT_MAX_EVIDENCE} for agent profiles)"
        ),
    )
    search_parser.add_argument(
        "--max-line-chars",
        type=int,
        default=None,
        metavar="N",
        help=(
            f"truncate matched evidence lines to N characters "
            f"(default {DEFAULT_FILTER_MAX_LINE_CHARS} for agent profiles)"
        ),
    )
    search_parser.add_argument(
        "--ledger-dir",
        metavar="DIR",
        help=(
            "store the canonical search Result in a content-addressed Evidence "
            "Ledger (implies --compact)"
        ),
    )
    search_parser.add_argument(
        "--agent-profile",
        choices=profile_names(),
        default="agent",
        help="selected Agent transport profile (default: agent)",
    )
    search_parser.add_argument(
        "--lightweight",
        action="store_true",
        help="omit empty investigation envelope fields from the agent response",
    )
    _add_investigation_link_args(search_parser)
    _add_cache_arg(search_parser)

    survey_parser = sub.add_parser(
        "survey",
        help="summarize an unfamiliar source with bounded streaming statistics",
    )
    survey_parser.add_argument("input", metavar="INPUT", help="source file to survey")
    survey_snapshot = survey_parser.add_mutually_exclusive_group()
    survey_snapshot.add_argument(
        "--snapshot",
        dest="snapshot",
        action="store_true",
        help="freeze the source before surveying (default)",
    )
    survey_snapshot.add_argument(
        "--no-snapshot",
        dest="snapshot",
        action="store_false",
        help="survey without first freezing the source",
    )
    survey_parser.set_defaults(snapshot=True)
    survey_parser.add_argument(
        "--segmenter",
        default="auto",
        help="record segmenter name (default: auto)",
    )
    survey_parser.add_argument("--last", metavar="DURATION", help="restrict to the latest duration")
    survey_parser.add_argument("--since", metavar="TIME", help="restrict to records since TIME")
    survey_parser.add_argument("--until", metavar="TIME", help="restrict to records until TIME")
    survey_parser.add_argument(
        "--max-templates",
        type=int,
        default=20,
        metavar="N",
        help="maximum retained template buckets (default: 20)",
    )
    survey_parser.add_argument(
        "--samples-per-template",
        type=int,
        default=2,
        metavar="N",
        help="maximum immutable samples per template (default: 2)",
    )
    survey_parser.add_argument(
        "--brief",
        action="store_true",
        help="emit a token-efficient survey view without sample text payloads",
    )
    survey_parser.add_argument(
        "--lightweight",
        action="store_true",
        help="omit empty investigation envelope fields from the agent response",
    )
    _add_investigation_link_args(survey_parser)
    _add_cache_arg(survey_parser)

    probe_format_parser = sub.add_parser(
        "probe-format",
        help="probe an unfamiliar log and propose a regex FormatSegmenter config",
    )
    probe_format_parser.add_argument(
        "input", metavar="INPUT", help="source file to probe"
    )
    probe_format_parser.add_argument(
        "--sample-lines",
        type=int,
        default=1000,
        help="max non-empty lines to sample (default: 1000)",
    )
    probe_format_parser.add_argument(
        "--min-coverage",
        type=float,
        default=None,
        help="minimum fraction of sampled lines a candidate must cover",
    )
    _add_investigation_link_args(probe_format_parser)
    _add_cache_arg(probe_format_parser)

    sample_parser = sub.add_parser(
        "sample",
        aliases=["peek"],
        help="sample bounded raw context without a query (peek is an alias)",
    )
    sample_parser.add_argument("input", metavar="INPUT", help="source file to sample")
    sample_parser.add_argument(
        "--strategy",
        choices=("head-tail", "head_tail", "uniform"),
        default="head-tail",
        help="deterministic sampling strategy (default: head-tail)",
    )
    sample_parser.add_argument(
        "--count",
        type=int,
        default=10,
        metavar="N",
        help="maximum selected records (default: 10)",
    )
    sample_parser.add_argument(
        "--max-chars",
        type=int,
        default=8_000,
        metavar="N",
        help="aggregate returned character budget (default: 8000)",
    )
    sample_snapshot = sample_parser.add_mutually_exclusive_group()
    sample_snapshot.add_argument(
        "--snapshot",
        dest="snapshot",
        action="store_true",
        help="freeze the source before sampling (default)",
    )
    sample_snapshot.add_argument(
        "--no-snapshot",
        dest="snapshot",
        action="store_false",
        help="sample without first freezing the source",
    )
    sample_parser.set_defaults(snapshot=True)
    sample_parser.add_argument(
        "--segmenter",
        default="auto",
        help="record segmenter name (default: auto)",
    )
    sample_parser.add_argument("--last", metavar="DURATION", help="restrict to the latest duration")
    sample_parser.add_argument("--since", metavar="TIME", help="restrict to records since TIME")
    sample_parser.add_argument("--until", metavar="TIME", help="restrict to records until TIME")
    _add_investigation_link_args(sample_parser)
    _add_cache_arg(sample_parser)

    expand_parser = sub.add_parser("expand", help="expand context around a cited source line")
    expand_parser.add_argument("source", metavar="SOURCE", help="source file containing the evidence")
    expand_parser.add_argument("start_line", type=int, metavar="START_LINE")
    expand_parser.add_argument("--end-line", type=int, metavar="LINE")
    expand_parser.add_argument("--before", type=int, default=3, metavar="N")
    expand_parser.add_argument("--after", type=int, default=3, metavar="N")
    expand_parser.add_argument(
        "--expected-sha256",
        "--sha256",
        dest="expected_sha256",
        metavar="DIGEST",
        help="require SOURCE to have this SHA-256 digest",
    )
    expand_parser.add_argument("--max-chars", type=int, default=20_000, metavar="N")
    _add_investigation_link_args(expand_parser)
    _add_cache_arg(expand_parser)

    expand_many_parser = sub.add_parser(
        "expand-many",
        help="expand several refs from one immutable Evidence Ledger result",
    )
    expand_many_parser.add_argument("ledger_dir", metavar="LEDGER_DIR")
    expand_many_parser.add_argument("result_id", metavar="RESULT_ID")
    expand_many_parser.add_argument("refs", nargs="+", metavar="REF")
    expand_many_parser.add_argument("--before", type=int, default=3, metavar="N")
    expand_many_parser.add_argument("--after", type=int, default=3, metavar="N")
    expand_many_parser.add_argument(
        "--max-chars",
        type=int,
        default=20_000,
        metavar="N",
        help="aggregate returned context budget (default: 20000)",
    )
    expand_many_parser.add_argument(
        "--max-output-chars",
        type=_compact_output_chars,
        metavar="N",
        help=(
            f"bound the complete JSON response structurally "
            f"(minimum {MIN_COMPACT_OUTPUT_CHARS}; default {DEFAULT_AGENT_MAX_OUTPUT_CHARS})"
        ),
    )
    expand_many_parser.add_argument(
        "--agent-profile",
        choices=("portable-json", "strict-json", "stateful-index", "frame"),
        default="portable-json",
        help="selected Agent transport profile (default: portable-json)",
    )

    verify_parser = sub.add_parser("verify", help="verify a completed evidence manifest")
    verify_parser.add_argument("manifest", metavar="MANIFEST")
    _add_investigation_link_args(verify_parser)

    run_parser = sub.add_parser("run", help="execute a scenario document")
    run_parser.add_argument("scenario", metavar="SCENARIO", help="scenario JSON/YAML path")
    run_parser.add_argument("--base-dir", metavar="PATH", help="base directory for relative paths")
    run_parser.add_argument("--platform", default="", help="optional scenario platform")
    run_parser.add_argument(
        "--runtime",
        default="default",
        help="registered domain runtime (default: default)",
    )
    run_parser.add_argument(
        "--load-extensions",
        action="store_true",
        help="explicitly load installed TraceCite extensions before running",
    )
    _add_investigation_link_args(run_parser)

    investigation_parser = sub.add_parser(
        "investigation",
        help="create and update a versioned InvestigationState document",
    )
    investigation_sub = investigation_parser.add_subparsers(
        dest="investigation_command", required=True
    )

    create_parser = investigation_sub.add_parser("create", help="create an investigation")
    create_parser.add_argument("path", metavar="PATH")
    create_parser.add_argument("question", metavar="QUESTION")
    create_parser.add_argument("--scope-json", "--scope", dest="scope_json", default="{}", metavar="JSON")
    create_parser.add_argument("--scope-file", metavar="PATH")
    create_parser.add_argument("--created-by", default="", metavar="ACTOR")
    create_parser.add_argument("--id", "--investigation-id", dest="investigation_id", metavar="ID")
    create_parser.add_argument(
        "--budget-json",
        "--budget",
        dest="budget_json",
        default="{}",
        metavar="JSON",
        help="optional versioned positive investigation budget policy",
    )

    show_parser = investigation_sub.add_parser("show", help="show and validate an investigation")
    show_parser.add_argument("path", metavar="PATH")

    budget_parser = investigation_sub.add_parser(
        "budget", help="show current investigation budget usage and remaining limits"
    )
    budget_parser.add_argument("path", metavar="PATH")

    summary_parser = investigation_sub.add_parser(
        "summary",
        help="show bounded advisory completeness and next-step categories",
    )
    summary_parser.add_argument("path", metavar="PATH")
    summary_parser.add_argument("--max-items", type=int, default=32, metavar="N")
    summary_parser.add_argument("--max-chars", type=int, default=24_000, metavar="N")

    timeline_parser = investigation_sub.add_parser(
        "timeline",
        help="show a bounded read-only structural event timeline",
    )
    timeline_parser.add_argument("path", metavar="PATH")
    timeline_parser.add_argument("--max-events", type=int, default=128, metavar="N")
    timeline_parser.add_argument("--max-chars", type=int, default=24_000, metavar="N")
    timeline_parser.add_argument("--max-source-bytes", type=int, default=1_048_576, metavar="N")

    compare_parser = investigation_sub.add_parser(
        "compare",
        help="compare two investigation snapshots structurally",
    )
    compare_parser.add_argument("left_path", metavar="LEFT_PATH")
    compare_parser.add_argument("right_path", metavar="RIGHT_PATH")
    compare_parser.add_argument("--max-items", type=int, default=128, metavar="N")
    compare_parser.add_argument("--max-chars", type=int, default=24_000, metavar="N")
    compare_parser.add_argument("--max-source-bytes", type=int, default=1_048_576, metavar="N")

    hypothesis_parser = investigation_sub.add_parser(
        "add-hypothesis", help="add a falsifiable hypothesis"
    )
    hypothesis_parser.add_argument("path", metavar="PATH")
    hypothesis_parser.add_argument("claim", metavar="CLAIM")
    hypothesis_parser.add_argument("--id", "--hypothesis-id", dest="hypothesis_id", metavar="ID")
    hypothesis_parser.add_argument("--rationale", default="", metavar="TEXT")

    test_parser = investigation_sub.add_parser("add-test", help="add a test for a hypothesis")
    test_parser.add_argument("path", metavar="PATH")
    test_parser.add_argument("hypothesis_id", metavar="HYPOTHESIS_ID")
    test_parser.add_argument("intent", metavar="INTENT")
    test_parser.add_argument(
        "--expected-observation",
        "--expected",
        dest="expected_observation",
        required=True,
        metavar="TEXT",
    )
    test_parser.add_argument(
        "--contradicting-observation",
        "--contradicting",
        dest="contradicting_observation",
        required=True,
        metavar="TEXT",
    )
    test_parser.add_argument("--strategy-json", "--strategy", dest="strategy_json", default="{}", metavar="JSON")
    test_parser.add_argument("--id", "--test-id", dest="test_id", metavar="ID")

    finding_parser = investigation_sub.add_parser("add-finding", help="record a finding")
    finding_parser.add_argument("path", metavar="PATH")
    finding_parser.add_argument("hypothesis_id", metavar="HYPOTHESIS_ID")
    finding_parser.add_argument("outcome", choices=sorted(FINDING_OUTCOMES))
    finding_parser.add_argument("summary", metavar="SUMMARY")
    finding_parser.add_argument(
        "--supporting-evidence", action="append", default=[], metavar="REF"
    )
    finding_parser.add_argument(
        "--contradicting-evidence", action="append", default=[], metavar="REF"
    )
    finding_parser.add_argument("--coverage-json", "--coverage", dest="coverage_json", default="{}", metavar="JSON")
    finding_parser.add_argument("--limitation", action="append", default=[], metavar="TEXT")

    candidate_parser = investigation_sub.add_parser(
        "propose-candidate",
        aliases=["propose-knowledge", "propose-knowledge-candidate"],
        help="explicitly propose an eligible Finding through a candidate store",
    )
    candidate_parser.add_argument("path", metavar="PATH")
    candidate_parser.add_argument("finding_id", metavar="FINDING_ID")
    candidate_parser.add_argument(
        "candidate_store_positional",
        nargs="?",
        metavar="CANDIDATE_STORE",
        help="independent KnowledgeGovernanceStore JSON path",
    )
    candidate_parser.add_argument(
        "--candidate-store",
        "--knowledge-store",
        dest="candidate_store",
        metavar="PATH",
    )
    candidate_parser.add_argument("--kind", default="finding", metavar="KIND")
    candidate_parser.add_argument("--domain", default="generic", metavar="DOMAIN")
    candidate_parser.add_argument("--scope", default="global", metavar="SCOPE")
    candidate_parser.add_argument("--created-by", default="", metavar="ACTOR")
    candidate_parser.add_argument("--case-id", default="", metavar="CASE_ID")
    candidate_parser.add_argument(
        "--applicability-json",
        "--applicability",
        dest="applicability_json",
        default="{}",
        metavar="JSON",
    )
    candidate_parser.add_argument(
        "--exclusions-json",
        "--exclusions",
        dest="exclusions_json",
        default="[]",
        metavar="JSON",
    )
    candidate_parser.add_argument(
        "--test-recipes-json",
        "--test-recipes",
        dest="test_recipes_json",
        metavar="JSON",
    )

    stop_parser = investigation_sub.add_parser("stop", help="close an investigation")
    stop_parser.add_argument("path", metavar="PATH")
    stop_parser.add_argument("reason", metavar="REASON")
    stop_parser.add_argument("--kind", choices=sorted(STOP_KINDS), default="completed")

    extension_parser = sub.add_parser(
        "extension", help="inspect or explicitly load installed extensions"
    )
    extension_parser.add_argument(
        "extension_command", choices=("list", "load"), nargs="?", default="list"
    )

    return parser


def _error_payload(operation: str, exc: Exception) -> dict[str, Any]:
    """Return the same broad shape as an Agent result for CLI-level failures."""
    return AgentResult(
        operation=operation,
        status="error",
        outcome="unknown",
        error={"type": type(exc).__name__, "message": str(exc)},
    ).to_dict()


def _link_kwargs(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "investigation_path": Path(args.investigation_path)
        if getattr(args, "investigation_path", None)
        else None,
        "hypothesis_id": getattr(args, "hypothesis_id", None),
        "test_id": getattr(args, "test_id", None),
    }


def _json_object_argument(value: str, *, field_name: str) -> Mapping[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{field_name} 不是合法 JSON: {exc}") from exc
    if not isinstance(parsed, Mapping):
        raise ValueError(f"{field_name} 必须是 JSON 对象")
    return parsed


def _json_argument(value: str, *, field_name: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{field_name} 不是合法 JSON: {exc}") from exc


def _encoded_json(payload: Any) -> str:
    return encoded_json(payload)


def _primary_artifact(artifacts: Any) -> list[dict[str, Any]]:
    rows = [dict(item) for item in artifacts or [] if isinstance(item, Mapping)]
    for role in ("matched_records", "filtered_log"):
        selected = next((item for item in rows if item.get("role") == role), None)
        if selected is not None:
            return [selected]
    return rows[:1]


def _compact_search_result(
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

    if len(_encoded_json(result)) > max_output_chars:
        # Budget trimming may omit labels or pointers. Account for the recovery
        # artifact before trimming so the final fit calculation includes it.
        result["artifacts"] = _primary_artifact(original_artifacts)

    content_trimmed = False
    label_index = evidence_columns.index("label")
    while len(_encoded_json(result)) > max_output_chars:
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
        len(_encoded_json(result)) > max_output_chars
        and all(not row[label_index] for row in evidence_rows)
    ):
        evidence_columns.pop(label_index)
        for row in evidence_rows:
            row.pop(label_index)

    evidence_removed = False
    while evidence_rows and len(_encoded_json(result)) > max_output_chars:
        if not evidence_removed:
            coverage["evidence_truncated"] = True
            evidence_removed = True
        evidence_rows.pop()
        coverage["evidence_returned"] = len(evidence_rows)

    while result.get("next_queries") and len(_encoded_json(result)) > max_output_chars:
        coverage["next_queries_truncated"] = True
        result["next_queries"].pop()

    if len(_encoded_json(result)) > max_output_chars:
        raise ValueError(
            f"compact search result cannot fit within {max_output_chars} characters"
        )
    return result


def _fit_expand_many_result(
    payload: Mapping[str, Any],
    *,
    max_output_chars: int | None,
) -> dict[str, Any]:
    """Fit an expandable Ledger response without ever slicing serialized JSON."""

    result = copy.deepcopy(dict(payload))
    if max_output_chars is None or len(_encoded_json(result)) <= max_output_chars:
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

    while len(_encoded_json(result)) > max_output_chars:
        candidates = [item for item in contexts if str(item.get("text") or "")]
        if not candidates:
            break
        item = max(candidates, key=lambda row: len(str(row.get("text") or "")))
        text = str(item.get("text") or "")
        over = len(_encoded_json(result)) - max_output_chars
        item["text"] = text[: max(0, len(text) - max(1, over + 16))]
        item["truncated"] = True

    failed_refs = list(coverage.get("failed_refs") or [])
    context_index = evidence_columns.index("context") if "context" in evidence_columns else -1
    ref_index = evidence_columns.index("ref") if "ref" in evidence_columns else -1
    while contexts and len(_encoded_json(result)) > max_output_chars:
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
    if len(_encoded_json(result)) > max_output_chars:
        raise ValueError(
            f"expand-many result cannot fit within {max_output_chars} characters"
        )
    return result


def _investigation_snapshot(store: InvestigationStore, result: Any = None) -> dict[str, Any]:
    payload = store.load().to_dict()
    if result is not None:
        payload["result"] = result
    return payload


def _invoke(args: argparse.Namespace) -> Mapping[str, Any]:
    """Call the tool selected by parsed ``args``."""

    if args.command == "probe":
        return probe(
            Path(args.input),
            glob=args.glob,
            recursive=args.recursive,
            segmenter=args.segmenter,
            cache=args.cache,
            **_link_kwargs(args),
        )
    if args.command == "search":
        selected_profile = getattr(args, "agent_profile", "agent")
        agent_transport = selected_profile in {
            "agent",
            "portable-json",
            "strict-json",
            "stateful-index",
            "frame",
        }
        max_evidence = (
            args.max_evidence
            if args.max_evidence is not None
            else (DEFAULT_AGENT_MAX_EVIDENCE if agent_transport else None)
        )
        max_line_chars = (
            args.max_line_chars
            if args.max_line_chars is not None
            else (DEFAULT_FILTER_MAX_LINE_CHARS if agent_transport else None)
        )
        if max_evidence is not None and max_evidence < 1:
            raise ValueError("max-evidence must be at least 1")
        if max_line_chars is not None and max_line_chars < 1:
            raise ValueError("max-line-chars must be at least 1")
        return search(
            Path(args.input),
            args.query,
            regex=args.regex,
            output_path=Path(args.output_path) if args.output_path else None,
            snapshot=args.snapshot,
            segmenter=args.segmenter,
            last=args.last,
            since=args.since,
            until=args.until,
            fold=args.fold,
            max_evidence=max_evidence,
            max_line_chars=max_line_chars,
            cache=args.cache,
            **_link_kwargs(args),
        )
    if args.command == "survey":
        return survey(
            Path(args.input),
            snapshot=args.snapshot,
            segmenter=args.segmenter,
            last=args.last,
            since=args.since,
            until=args.until,
            max_templates=args.max_templates,
            samples_per_template=args.samples_per_template,
            cache=args.cache,
            **_link_kwargs(args),
        )
    if args.command == "probe-format":
        return probe_format(
            Path(args.input),
            sample_lines=args.sample_lines,
            min_coverage=args.min_coverage,
            cache=args.cache,
            **_link_kwargs(args),
        )
    if args.command in {"sample", "peek"}:
        return sample(
            Path(args.input),
            strategy=args.strategy,
            count=args.count,
            max_chars=args.max_chars,
            snapshot=args.snapshot,
            segmenter=args.segmenter,
            last=args.last,
            since=args.since,
            until=args.until,
            cache=args.cache,
            **_link_kwargs(args),
        )
    if args.command == "expand":
        return expand(
            Path(args.source),
            args.start_line,
            end_line=args.end_line,
            before=args.before,
            after=args.after,
            expected_sha256=args.expected_sha256,
            max_chars=args.max_chars,
            cache=args.cache,
            **_link_kwargs(args),
        )
    if args.command == "expand-many":
        return expand_many_from_ledger(
            EvidenceLedger(Path(args.ledger_dir)),
            args.result_id,
            args.refs,
            before=args.before,
            after=args.after,
            max_chars=args.max_chars,
        )
    if args.command == "verify":
        return verify(Path(args.manifest), **_link_kwargs(args))
    if args.command == "run":
        if args.load_extensions:
            load_extensions(strict=False)
        runtime = get_runtime(args.runtime)
        return run(
            Path(args.scenario),
            base_dir=Path(args.base_dir) if args.base_dir else None,
            platform=args.platform,
            runtime=runtime,
            **_link_kwargs(args),
        )
    if args.command == "investigation":
        if args.investigation_command == "compare":
            return compare_investigations(
                Path(args.left_path),
                Path(args.right_path),
                max_items=args.max_items,
                max_output_chars=args.max_chars,
                max_source_bytes=args.max_source_bytes,
            )
        store = InvestigationStore(Path(args.path))
        if args.investigation_command == "create":
            scope: Mapping[str, Any]
            if args.scope_file:
                scope_payload = json.loads(Path(args.scope_file).read_text(encoding="utf-8"))
                if not isinstance(scope_payload, Mapping):
                    raise ValueError("scope-file 顶层必须是 JSON 对象")
                scope = scope_payload
            else:
                scope = _json_object_argument(args.scope_json, field_name="scope-json")
            budget_policy = _json_object_argument(
                args.budget_json, field_name="budget-json"
            )
            created = store.create(
                args.question,
                scope=scope,
                created_by=args.created_by,
                investigation_id=args.investigation_id,
                budget_policy=budget_policy,
            )
            return created.to_dict()
        if args.investigation_command == "show":
            return store.load().to_dict()
        if args.investigation_command == "budget":
            return store.budget_status()
        if args.investigation_command == "summary":
            return summarize_investigation(
                store,
                max_items=args.max_items,
                max_output_chars=args.max_chars,
            )
        if args.investigation_command == "timeline":
            return timeline_investigation(
                store,
                max_events=args.max_events,
                max_output_chars=args.max_chars,
                max_source_bytes=args.max_source_bytes,
            )
        if args.investigation_command == "add-hypothesis":
            item = store.add_hypothesis(
                args.claim,
                hypothesis_id=args.hypothesis_id,
                rationale=args.rationale,
            )
            return _investigation_snapshot(store, item)
        if args.investigation_command == "add-test":
            item = store.add_test(
                args.hypothesis_id,
                args.intent,
                expected_observation=args.expected_observation,
                contradicting_observation=args.contradicting_observation,
                strategy=_json_object_argument(args.strategy_json, field_name="strategy-json"),
                test_id=args.test_id,
            )
            return _investigation_snapshot(store, item)
        if args.investigation_command == "add-finding":
            item = store.add_finding(
                args.hypothesis_id,
                args.outcome,
                args.summary,
                supporting_evidence=args.supporting_evidence,
                contradicting_evidence=args.contradicting_evidence,
                coverage=_json_object_argument(args.coverage_json, field_name="coverage-json"),
                limitations=args.limitation,
            )
            return _investigation_snapshot(store, item)
        if args.investigation_command in {
            "propose-candidate",
            "propose-knowledge",
            "propose-knowledge-candidate",
        }:
            candidate_store = args.candidate_store or args.candidate_store_positional
            if not candidate_store:
                raise ValueError(
                    "propose-candidate 必须提供独立候选库路径（位置参数或 --candidate-store）"
                )
            recipes = (
                _json_argument(args.test_recipes_json, field_name="test-recipes-json")
                if args.test_recipes_json
                else None
            )
            candidate = store.propose_knowledge_candidate(
                args.finding_id,
                governance_store_path=Path(candidate_store),
                kind=args.kind,
                domain=args.domain,
                scope=args.scope,
                created_by=args.created_by or None,
                case_id=args.case_id or None,
                applicability=_json_argument(
                    args.applicability_json,
                    field_name="applicability-json",
                ),
                exclusions=_json_argument(
                    args.exclusions_json,
                    field_name="exclusions-json",
                ),
                test_recipes=recipes,
            )
            result = candidate.to_dict()
            links = _investigation_snapshot(store).get("knowledge_candidates", [])
            result["investigation"] = next(
                (item for item in links if item.get("candidate_id") == candidate.id),
                links[-1] if links else {},
            )
            return result
        if args.investigation_command == "stop":
            return store.stop(args.reason, kind=args.kind).to_dict()
        raise ValueError(f"unknown investigation command: {args.investigation_command!r}")
    if args.command == "extension":
        discovered = (
            load_extensions(strict=False)
            if args.extension_command == "load"
            else []
        )
        failed = [row for row in discovered if row.get("status") == "failed"]
        return AgentResult(
            operation="extension",
            status="partial" if failed else "ok",
            outcome="unknown" if failed else "not_assessed",
            warnings=[
                f"{row.get('name')}: {row.get('error')}" for row in failed
            ],
            data={
                "loaded": discovered,
                "runtimes": available_runtimes(),
                "explicit_load": args.extension_command == "load",
            },
        ).to_dict()
    raise ValueError(f"unknown command: {args.command!r}")


def _print_payload(payload: Any, *, compact: bool = False, frame: bool = False) -> None:
    """Print one deterministic Agent response to stdout."""

    if frame:
        print(render_frame(payload if isinstance(payload, Mapping) else {}))
        return
    print(_encoded_json(payload))


def main(
    argv: Sequence[str] | None = None,
    *,
    prog: str = "tracecite",
) -> int:
    """Run the Agent CLI and return a process exit status.

    ``no_match`` is intentionally successful: a zero-result search is a valid
    evidence outcome.  Only the structured ``error`` status maps to exit code 1.
    """

    args = build_parser(prog=prog).parse_args(argv)
    profile_name = getattr(args, "agent_profile", "agent")
    profile = get_agent_profile(profile_name)
    if args.command == "search" and getattr(args, "compact", False) and profile_name == "canonical":
        profile = get_agent_profile("portable-json")
    max_output_chars = getattr(args, "max_output_chars", None)
    if max_output_chars is None and args.command in {"search", "expand-many"}:
        if args.command == "search" and profile.transport != "canonical-json":
            max_output_chars = DEFAULT_AGENT_MAX_OUTPUT_CHARS
        elif args.command == "expand-many":
            max_output_chars = DEFAULT_AGENT_MAX_OUTPUT_CHARS
        args.max_output_chars = max_output_chars
    profile_error = (
        f"agent profile {profile.name!r} requires --ledger-dir"
        if args.command == "search" and profile.requires_ledger and args.ledger_dir is None
        else None
    )
    compact = bool(
        (args.command == "search" and (
            profile.transport != "canonical-json"
            or args.max_output_chars is not None
            or args.ledger_dir is not None
        ))
        or args.command == "expand-many"
    )
    frame = profile.transport == "frame"
    try:
        if profile_error:
            raise ValueError(profile_error)
        payload = _invoke(args)
        if args.command == "search" and args.ledger_dir is not None:
            result_id = EvidenceLedger(Path(args.ledger_dir)).store(payload)
            payload = copy.deepcopy(dict(payload))
            data = dict(payload.get("data") or {})
            data["result_id"] = result_id
            if profile.compact_history:
                data["compact_history"] = True
                data["history_mode"] = "ledger"
            payload["data"] = data
        if args.command == "survey" and getattr(args, "brief", False):
            payload = apply_survey_brief(payload)
        if args.command == "search" and compact:
            payload = _compact_search_result(
                payload,
                max_output_chars=args.max_output_chars,
            )
        elif args.command == "expand-many":
            payload = _fit_expand_many_result(
                payload,
                max_output_chars=args.max_output_chars,
            )
        if getattr(args, "lightweight", False):
            payload = lightweight_result(payload)
        if frame and args.max_output_chars is not None:
            rendered = render_frame(payload)
            if len(rendered) > args.max_output_chars:
                raise ValueError(
                    f"frame result cannot fit within {args.max_output_chars} characters"
                )
    except Exception as exc:  # keep the command boundary machine-readable
        payload = _error_payload(args.command, exc)
    _print_payload(payload, compact=compact, frame=frame)
    return 1 if isinstance(payload, Mapping) and payload.get("status") == "error" else 0


if __name__ == "__main__":
    raise SystemExit(main())
