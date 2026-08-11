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
from tracecite.runtime.schema import AgentResult
from tracecite.runtime.tools import expand, probe, run, search, verify


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

    verify_parser = sub.add_parser("verify", help="verify a completed evidence manifest")
    verify_parser.add_argument("manifest", metavar="MANIFEST")

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


def _invoke(args: argparse.Namespace) -> Mapping[str, Any]:
    """Call the tool selected by parsed ``args``."""

    if args.command == "probe":
        return probe(
            Path(args.input),
            glob=args.glob,
            recursive=args.recursive,
            segmenter=args.segmenter,
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
        )
    if args.command == "verify":
        return verify(Path(args.manifest))
    if args.command == "run":
        if args.load_extensions:
            load_extensions(strict=False)
        runtime = get_runtime(args.runtime)
        return run(
            Path(args.scenario),
            base_dir=Path(args.base_dir) if args.base_dir else None,
            platform=args.platform,
            runtime=runtime,
        )
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
