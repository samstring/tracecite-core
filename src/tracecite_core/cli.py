"""Standalone CLI for TraceCite Core's pure-text evidence capabilities."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import __version__
from .plugin_sdk import load_entrypoint_plugins, loaded_plugins
from .run import verify_manifest
from .segmenter import available_segmenters, build_segmenter
from .source import resolve_paths
from .text_filter import filter_text


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tracecite-core",
        description="Pure-text evidence extraction for agents.",
    )
    parser.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    filt = sub.add_parser("filter", help="filter a text file into line-addressable evidence")
    filt.add_argument("input")
    filt.add_argument("--grep", required=True, dest="pattern")
    filt.add_argument("--tag")
    filt.add_argument("--out")
    filt.add_argument("--snapshot", action="store_true")
    filt.add_argument("--segmenter", default="rawtext")
    filt.add_argument("--last")
    filt.add_argument("--since")
    filt.add_argument("--until")
    filt.add_argument("--json", action="store_true")

    segment = sub.add_parser("segment", help="inspect record boundaries")
    segment.add_argument("input")
    segment.add_argument("--segmenter", default="rawtext")
    segment.add_argument("--limit", type=int, default=20)

    source = sub.add_parser("source", help="resolve a file, directory, glob, or archive")
    source.add_argument("path")
    source.add_argument("--glob", default="*")
    source.add_argument("--recursive", action="store_true")

    verify = sub.add_parser("verify", help="verify an evidence run manifest")
    verify.add_argument("manifest")

    sub.add_parser("plugin", help="diagnose Core entry-point plugins")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "filter":
        result = filter_text(
            Path(args.input),
            pattern=args.pattern,
            tag=args.tag,
            output_path=Path(args.out) if args.out else None,
            snapshot=args.snapshot,
            segmenter=build_segmenter(args.segmenter),
            last=args.last,
            since=args.since,
            until=args.until,
        )
        payload = result.to_dict()
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"{result.match_records} records -> {result.output_path}")
        return 0 if result.match_records else 2
    if args.command == "segment":
        records = []
        for index, record in enumerate(build_segmenter(args.segmenter).segment_file(Path(args.input))):
            if index >= max(0, args.limit):
                break
            records.append(record.to_dict())
        print(json.dumps({"records": records, "count": len(records)}, ensure_ascii=False, indent=2))
        return 0
    if args.command == "source":
        paths = resolve_paths(args.path, glob=args.glob, recursive=args.recursive)
        print(json.dumps({"paths": [str(path) for path in paths]}, ensure_ascii=False, indent=2))
        return 0
    if args.command == "verify":
        print(json.dumps(verify_manifest(Path(args.manifest)), ensure_ascii=False, indent=2))
        return 0
    if args.command == "plugin":
        discovered = load_entrypoint_plugins(strict=False)
        print(json.dumps({
            "segmenters": available_segmenters(),
            "discovered": discovered,
            "loaded": loaded_plugins(),
        }, ensure_ascii=False, indent=2))
        return 0 if all(item.get("status") != "failed" for item in discovered) else 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

