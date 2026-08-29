from __future__ import annotations

import argparse
import json
from pathlib import Path

from tracecite.runtime import EvidenceRequest, QueryTarget, RangeTarget
from tracecite.runtime.retrieval_session import RetrievalSessionStore
from tracecite.runtime.session_retrieval import retrieve_with_session


def _session_store(path: str) -> RetrievalSessionStore:
    requested = Path(path).expanduser().resolve()
    requested.parent.mkdir(parents=True, exist_ok=True)
    session_id = requested.stem or "pi-agent"
    store = RetrievalSessionStore(
        requested.parent,
        session_id,
        namespace="_retrieval_sessions",
        legacy_evidence_context=False,
    )
    store.load()
    return store


def _search(args: argparse.Namespace, session: RetrievalSessionStore) -> dict:
    target = QueryTarget(
        Path(args.file),
        args.query,
        regex=bool(args.regex),
        snapshot=True,
        max_evidence=args.max_evidence,
    )
    return retrieve_with_session(EvidenceRequest(target), session).to_dict()


def _expand(args: argparse.Namespace, session: RetrievalSessionStore) -> dict:
    radius = max(0, int(args.radius))
    target = RangeTarget(
        Path(args.file),
        int(args.line),
        before=radius,
        after=radius,
        expected_sha256=args.sha256 or None,
        max_chars=int(args.max_chars),
    )
    return retrieve_with_session(EvidenceRequest(target), session).to_dict()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Thin Pi-to-TraceCite canonical retrieval bridge."
    )
    parser.add_argument(
        "--session",
        required=True,
        help="Persistent RetrievalSession anchor; no InvestigationState is created.",
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
    session = _session_store(args.session)
    if args.command == "search":
        payload = _search(args, session)
    else:
        payload = _expand(args, session)
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
