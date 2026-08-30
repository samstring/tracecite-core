from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from tracecite.runtime import EvidenceRequest, QueryTarget, RangeTarget
from tracecite.runtime.repeated_evidence import attach_matched_existing_evidence
from tracecite.runtime.retrieval_session import RetrievalSessionStore
from tracecite.runtime.retrieval_telemetry import RetrievalSessionTelemetry
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


def _attach_progress(payload: dict, progress: dict[str, int]) -> dict:
    data = dict(payload.get("data") or {})
    data["session_progress"] = dict(progress)
    payload["data"] = data
    return payload


def _search(args: argparse.Namespace, session: RetrievalSessionStore) -> dict:
    target = QueryTarget(
        Path(args.file),
        args.query,
        regex=bool(args.regex),
        snapshot=True,
        max_evidence=args.max_evidence,
    )
    result = retrieve_with_session(EvidenceRequest(target), session)
    payload = attach_matched_existing_evidence(result)
    progress = RetrievalSessionTelemetry(session).record_search(
        source=str(Path(args.file).expanduser().resolve()),
        query=str(args.query),
        regex=bool(args.regex),
        result=payload,
    )
    return _attach_progress(payload, progress)


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
    telemetry = RetrievalSessionTelemetry(session)
    if not args.replay:
        result = retrieve_with_session(EvidenceRequest(target), session)
        payload = attach_matched_existing_evidence(result)
        return _attach_progress(payload, telemetry.record_expand())

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
    return _attach_progress(payload, telemetry.record_expand())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Pi-to-TraceCite retrieval bridge with mechanical session telemetry."
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
