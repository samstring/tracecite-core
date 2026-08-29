from __future__ import annotations

import argparse
import json
from pathlib import Path

from tracecite.runtime import (
    EvidenceRequest,
    InvestigationStore,
    QueryTarget,
    RangeTarget,
    retrieve,
)


def _ensure_investigation(path: str) -> Path:
    state_path = Path(path).expanduser().resolve()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    store = InvestigationStore(state_path)
    if state_path.exists():
        store.load()
    else:
        store.create("Pi Agent evidence retrieval session")
    return state_path


def _search(args: argparse.Namespace, state_path: Path) -> dict:
    target = QueryTarget(
        Path(args.file),
        args.query,
        regex=bool(args.regex),
        snapshot=True,
        max_evidence=args.max_evidence,
    )
    return retrieve(
        EvidenceRequest(target, investigation_path=state_path)
    ).to_dict()


def _expand(args: argparse.Namespace, state_path: Path) -> dict:
    radius = max(0, int(args.radius))
    target = RangeTarget(
        Path(args.file),
        int(args.line),
        before=radius,
        after=radius,
        expected_sha256=args.sha256 or None,
        max_chars=int(args.max_chars),
    )
    return retrieve(
        EvidenceRequest(target, investigation_path=state_path)
    ).to_dict()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Thin Pi-to-TraceCite canonical retrieval bridge."
    )
    parser.add_argument(
        "--state",
        required=True,
        help="Persistent InvestigationState used only to retain retrieval progress.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    search = sub.add_parser("search")
    search.add_argument("file")
    search.add_argument("query")
    search.add_argument("--regex", action="store_true")
    search.add_argument("--max-evidence", type=int, default=20)

    expand = sub.add_parser("expand")
    expand.add_argument("file")
    expand.add_argument("line", type=int)
    expand.add_argument("--radius", type=int, default=8)
    expand.add_argument("--sha256", default="")
    expand.add_argument("--max-chars", type=int, default=16_000)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    state_path = _ensure_investigation(args.state)
    if args.command == "search":
        payload = _search(args, state_path)
    else:
        payload = _expand(args, state_path)
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
