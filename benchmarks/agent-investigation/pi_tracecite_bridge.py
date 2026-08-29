from __future__ import annotations

import argparse
import json
import tempfile
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


def _range_target(args: argparse.Namespace) -> RangeTarget:
    radius = max(0, int(args.radius))
    return RangeTarget(
        Path(args.file),
        int(args.line),
        before=radius,
        after=radius,
        expected_sha256=args.sha256 or None,
        max_chars=int(args.max_chars),
    )


def _expand(args: argparse.Namespace, session: RetrievalSessionStore) -> dict:
    target = _range_target(args)
    if not args.replay:
        return retrieve_with_session(EvidenceRequest(target), session).to_dict()

    # Replay is an explicit Agent request to re-materialize old evidence.  Use a
    # throw-away retrieval session so replay does not turn old evidence into new
    # evidence in the caller's main session or disturb its novelty accounting.
    with tempfile.TemporaryDirectory(prefix="tracecite-replay-") as root:
        replay_session = RetrievalSessionStore(
            root,
            "replay",
            namespace="_retrieval_sessions",
            legacy_evidence_context=False,
        )
        payload = retrieve_with_session(EvidenceRequest(target), replay_session).to_dict()

    coverage = dict(payload.get("coverage") or {})
    replayed = len(payload.get("evidence") or [])
    coverage["replayed_evidence"] = replayed
    coverage["new_evidence"] = 0
    payload["coverage"] = coverage

    data = dict(payload.get("data") or {})
    data["replayed"] = True
    if isinstance(data.get("text"), str):
        data["new_text"] = data["text"]
    payload["data"] = data
    return payload


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
    expand.add_argument(
        "--replay",
        action="store_true",
        help="Explicitly re-materialize previously seen context without marking it new.",
    )
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
