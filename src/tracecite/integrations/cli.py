"""Command-line interface for the generic TraceCite Runtime tools.

The command line is deliberately a thin adapter over :mod:`tracecite.runtime.tools`.
The tools already provide the public result envelope, so the CLI only needs to
parse arguments, serialize that envelope, and map an error status to a non-zero
process exit code.
"""

from __future__ import annotations

import argparse
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
from tracecite.runtime.tools import expand, probe, run, sample, search, survey, verify


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
    _add_investigation_link_args(survey_parser)
    _add_cache_arg(survey_parser)

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


def _print_json(payload: Any) -> None:
    """Print one deterministic JSON document to stdout."""

    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))


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
    try:
        payload = _invoke(args)
    except Exception as exc:  # keep the command boundary machine-readable
        payload = _error_payload(args.command, exc)
    _print_json(payload)
    return 1 if isinstance(payload, Mapping) and payload.get("status") == "error" else 0


if __name__ == "__main__":
    raise SystemExit(main())
