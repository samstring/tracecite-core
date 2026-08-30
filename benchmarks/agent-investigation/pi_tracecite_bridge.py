from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from tracecite.extension.evidence import EntityRef, EvidenceRelation
from tracecite.extension.retrieval import (
    ProviderEvidence,
    RetrieveRequest as ProviderRetrieveRequest,
    RetrieveResult as ProviderRetrieveResult,
)
from tracecite.runtime import (
    AggregateRequest,
    EvidenceRequest,
    QueryTarget,
    RangeTarget,
    RetrievalSessionStore,
    SourceTarget,
    TraversalLimits,
    aggregate,
    materialize,
    replay,
    retrieve,
    traverse,
    verify,
)
from tracecite.runtime.repeated_evidence import attach_matched_existing_evidence


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


def _retrieve(args: argparse.Namespace, session: RetrievalSessionStore) -> dict[str, Any]:
    if args.query:
        target = QueryTarget(
            Path(args.file),
            args.query,
            regex=bool(args.regex),
            snapshot=True,
            max_evidence=args.max_evidence,
        )
    else:
        target = SourceTarget(
            Path(args.file),
            glob=args.glob,
            recursive=bool(args.recursive),
        )
    result = retrieve(EvidenceRequest(target), session=session)
    return attach_matched_existing_evidence(result)


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


def _materialize(args: argparse.Namespace, session: RetrievalSessionStore) -> dict[str, Any]:
    result = materialize(_range_target(args), session=session)
    return attach_matched_existing_evidence(result)


def _replay(args: argparse.Namespace, session: RetrievalSessionStore) -> dict[str, Any]:
    result = replay(_range_target(args), session=session)
    payload = result.to_dict()
    coverage = payload.setdefault("coverage", {})
    coverage.setdefault("replayed_evidence", 1)
    data = payload.setdefault("data", {})
    if "new_text" not in data and "text" in data:
        data["new_text"] = data["text"]
    return payload


def _aggregate(args: argparse.Namespace) -> dict[str, Any]:
    return aggregate(
        AggregateRequest(
            source=Path(args.file),
            query=args.query,
            regex=bool(args.regex),
            operation=args.operation,
            group_regex=args.group_regex or None,
            max_groups=int(args.max_groups),
        )
    )


class _FixtureProvider:
    """Minimal provider adapter for exposing canonical traversal to Pi.

    The fixture format is provider-shaped evidence, not raw-log parsing. It keeps
    traversal operational without teaching Runtime how to choose entities or
    inventing a second traversal model in the adapter.
    """

    def __init__(self, path: Path):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            raise ValueError("provider fixture must be a JSON object")
        self.name = str(payload.get("name") or path.stem or "pi-provider")
        rows = payload.get("evidence") or []
        relations = payload.get("relations") or []
        if not isinstance(rows, list) or not isinstance(relations, list):
            raise ValueError("provider fixture evidence/relations must be arrays")
        self._evidence = tuple(ProviderEvidence.from_mapping(item) for item in rows)
        self._relations = tuple(EvidenceRelation.from_mapping(item) for item in relations)

    @staticmethod
    def _entity_keys(request: ProviderRetrieveRequest) -> set[tuple[str, str, str]]:
        return {item.key for item in request.entities}

    def _selected(self, request: ProviderRetrieveRequest) -> tuple[ProviderEvidence, ...]:
        ids = set(request.evidence_ids)
        entity_keys = self._entity_keys(request)
        selected: list[ProviderEvidence] = []
        for row in self._evidence:
            by_id = bool(ids and row.id in ids)
            by_entity = bool(entity_keys and any(item.key in entity_keys for item in row.entities))
            if by_id or by_entity:
                selected.append(row)
        return tuple(selected)

    def can_handle(self, request: ProviderRetrieveRequest) -> bool:
        return bool(self._selected(request))

    def retrieve(self, request: ProviderRetrieveRequest) -> ProviderRetrieveResult:
        selected_all = self._selected(request)
        selected = selected_all[: request.limit]
        selected_ids = {item.id for item in selected}
        relations = tuple(
            item
            for item in self._relations
            if item.source_id in selected_ids or item.target_id in selected_ids
        )
        return ProviderRetrieveResult(
            status="ok",
            evidence=selected,
            relations=relations,
            coverage={"complete": len(selected_all) <= len(selected)},
            diagnostics={"fixture": True},
        )


def _parse_entities(raw: list[str]) -> tuple[EntityRef, ...]:
    values: list[EntityRef] = []
    for item in raw:
        payload = json.loads(item)
        if not isinstance(payload, Mapping):
            raise ValueError("seed entity must be a JSON object")
        values.append(EntityRef.from_mapping(payload))
    return tuple(values)


def _traverse(args: argparse.Namespace) -> dict[str, Any]:
    provider = _FixtureProvider(Path(args.provider_file).expanduser().resolve())
    limits = TraversalLimits(
        max_depth=int(args.max_depth),
        max_retrievals=int(args.max_retrievals),
        max_evidence=int(args.max_evidence),
        max_wall_seconds=float(args.max_wall_seconds),
        per_request_limit=int(args.per_request_limit),
    )
    result = traverse(
        (provider,),
        seed_evidence_ids=tuple(args.seed_evidence_id or ()),
        seed_entities=_parse_entities(list(args.seed_entity or ())),
        exploration_policy=limits,
    )
    payload = result.to_dict()
    payload["operation"] = "traverse"
    return payload


def _verify(args: argparse.Namespace) -> dict[str, Any]:
    return verify(Path(args.manifest))


def _add_range_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("file")
    parser.add_argument("line", type=int)
    parser.add_argument("--radius", type=int, default=8)
    parser.add_argument("--sha256", default="")
    parser.add_argument("--max-chars", type=int, default=16_000)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Pi-to-TraceCite canonical Evidence Runtime bridge."
    )
    parser.add_argument(
        "--session",
        required=True,
        help="Persistent RetrievalSession anchor; no planner state is created.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    retrieve_parser = sub.add_parser("retrieve")
    retrieve_parser.add_argument("file")
    retrieve_parser.add_argument("--query", default="")
    retrieve_parser.add_argument("--regex", action="store_true")
    retrieve_parser.add_argument("--max-evidence", type=int, default=20)
    retrieve_parser.add_argument("--glob", default="*")
    retrieve_parser.add_argument("--recursive", action="store_true")

    materialize_parser = sub.add_parser("materialize")
    _add_range_args(materialize_parser)

    replay_parser = sub.add_parser("replay")
    _add_range_args(replay_parser)

    aggregate_parser = sub.add_parser("aggregate")
    aggregate_parser.add_argument("file")
    aggregate_parser.add_argument("query")
    aggregate_parser.add_argument("--regex", action="store_true")
    aggregate_parser.add_argument("--operation", choices=("count", "distinct", "group"), default="count")
    aggregate_parser.add_argument("--group-regex", default="")
    aggregate_parser.add_argument("--max-groups", type=int, default=100)

    traverse_parser = sub.add_parser("traverse")
    traverse_parser.add_argument("provider_file")
    traverse_parser.add_argument("--seed-evidence-id", action="append", default=[])
    traverse_parser.add_argument("--seed-entity", action="append", default=[])
    traverse_parser.add_argument("--max-depth", type=int, default=3)
    traverse_parser.add_argument("--max-retrievals", type=int, default=12)
    traverse_parser.add_argument("--max-evidence", type=int, default=500)
    traverse_parser.add_argument("--max-wall-seconds", type=float, default=5.0)
    traverse_parser.add_argument("--per-request-limit", type=int, default=100)

    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("manifest")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    session = _session_store(args.session)
    if args.command == "retrieve":
        payload = _retrieve(args, session)
    elif args.command == "materialize":
        payload = _materialize(args, session)
    elif args.command == "replay":
        payload = _replay(args, session)
    elif args.command == "aggregate":
        payload = _aggregate(args)
    elif args.command == "traverse":
        payload = _traverse(args)
    elif args.command == "verify":
        payload = _verify(args)
    else:  # pragma: no cover - argparse owns command validation
        raise AssertionError(args.command)
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
