from __future__ import annotations

import argparse
import hashlib
import json
import os
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
    EvidenceShellPolicy,
    EvidenceShellRequest,
    QueryTarget,
    RangeTarget,
    RetrievalSessionStore,
    SourceTarget,
    TraversalLimits,
    aggregate,
    materialize,
    replay,
    retrieve,
    run_evidence_shell,
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


def _positive_env_int(name: str, default: int) -> int:
    raw = str(os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _shell_policy() -> EvidenceShellPolicy:
    """Read host/user policy. Agent tool arguments cannot override it."""

    return EvidenceShellPolicy(
        max_evidence_tokens=_positive_env_int("TRACECITE_MAX_EVIDENCE_TOKENS", 12_000),
        max_evidence_bytes=_positive_env_int("TRACECITE_MAX_EVIDENCE_BYTES", 64 * 1024),
    )


def _valid_sha256(value: object) -> str:
    digest = str(value or "").strip().lower()
    if len(digest) == 64 and all(ch in "0123456789abcdef" for ch in digest):
        return digest
    return ""


def _payload_sha256(payload: Mapping[str, Any], source: Path) -> str:
    direct = _valid_sha256(payload.get("sha256"))
    if direct:
        return direct

    rows = payload.get("evidence")
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, Mapping):
                digest = _valid_sha256(row.get("sha256"))
                if digest:
                    return digest

    data = payload.get("data")
    if isinstance(data, Mapping):
        source_sha = _valid_sha256(data.get("source_sha256"))
        if source_sha:
            return source_sha
        source_version = data.get("source_version")
        if isinstance(source_version, Mapping):
            version = source_version.get("version")
            if isinstance(version, Mapping):
                digest = _valid_sha256(version.get("value"))
                if digest:
                    return digest
        sources = data.get("sources")
        if isinstance(sources, list):
            resolved = source.resolve()
            for row in sources:
                if not isinstance(row, Mapping):
                    continue
                raw_path = str(row.get("path") or "").strip()
                if raw_path and Path(raw_path).expanduser().resolve() != resolved:
                    continue
                digest = _valid_sha256(row.get("sha256"))
                if digest:
                    return digest

    if source.is_file():
        hasher = hashlib.sha256()
        with source.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                hasher.update(chunk)
        return hasher.hexdigest()
    return ""


def _directory_source_identity_evidence(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Project SourceTarget directory results as metadata-only evidence pointers."""

    data = payload.get("data")
    if not isinstance(data, Mapping):
        return []
    rows = data.get("sources")
    if not isinstance(rows, list):
        return []

    pointers: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        source_path = str(row.get("path") or "").strip()
        if not source_path:
            continue
        source_path = str(Path(source_path).expanduser().resolve())
        digest = _valid_sha256(row.get("sha256"))
        size = row.get("size")
        segmenter = str(row.get("segmenter") or "").strip()
        name = Path(source_path).name

        label = [f"source={name}", f"access_file={source_path}"]
        if isinstance(size, int) and not isinstance(size, bool):
            label.append(f"bytes={size}")
        if digest:
            label.append(f"sha256={digest}")
        if segmenter:
            label.append(f"segmenter={segmenter}")
        label.append("use access_file for later TraceCite calls")

        pointers.append(
            {
                "uri": (
                    f"tracecite-source://sha256/{digest}"
                    if digest
                    else f"tracecite-source://path/{name}"
                ),
                "source_path": source_path,
                "sha256": digest or None,
                "label": " ".join(label),
                "metadata_only": True,
            }
        )
    return pointers


def _file_access_identity_evidence(
    requested: Path,
    payload: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Return the stable file argument separately from immutable evidence refs."""

    if not requested.is_file():
        return None
    source_path = str(requested.expanduser().resolve())
    digest = _payload_sha256(payload, requested)
    name = Path(source_path).name
    label = [
        f"follow_up_file={source_path}",
        f"source={name}",
    ]
    if digest:
        label.append(f"sha256={digest}")
    label.append("snapshot refs are citations, not file paths")
    label.append("reuse follow_up_file for later TraceCite calls")
    return {
        "uri": (
            f"tracecite-access://sha256/{digest}"
            if digest
            else f"tracecite-access://path/{name}"
        ),
        "source_path": source_path,
        "sha256": digest or None,
        "label": " ".join(label),
        "metadata_only": True,
    }


def _append_identity_evidence(payload: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    existing = payload.get("evidence")
    payload["evidence"] = [*(existing if isinstance(existing, list) else []), *rows]


def _retrieve(args: argparse.Namespace, session: RetrievalSessionStore) -> dict[str, Any]:
    requested = Path(args.file)

    if args.query and not requested.is_dir():
        target = QueryTarget(
            requested,
            args.query,
            regex=bool(args.regex),
            snapshot=True,
        )
    else:
        target = SourceTarget(
            requested,
            glob=args.glob,
            recursive=bool(args.recursive),
        )
    result = retrieve(EvidenceRequest(target), session=session)
    payload = attach_matched_existing_evidence(result)

    if requested.is_dir():
        identities = _directory_source_identity_evidence(payload)
        _append_identity_evidence(payload, identities)
        if identities:
            data = payload.setdefault("data", {})
            if isinstance(data, dict):
                data["source_identity_projection"] = True
    elif requested.is_file():
        access = _file_access_identity_evidence(requested, payload)
        if access is not None:
            _append_identity_evidence(payload, [access])
            data = payload.setdefault("data", {})
            if isinstance(data, dict):
                data["follow_up_access_file"] = access["source_path"]

    return payload


def _run_shell(args: argparse.Namespace, session: RetrievalSessionStore) -> dict[str, Any]:
    return run_evidence_shell(
        EvidenceShellRequest(
            source=Path(args.file),
            program=args.program,
            segmenter=args.segmenter,
            last=args.last or None,
            since=args.since or None,
            until=args.until or None,
            fold=bool(args.fold),
        ),
        policy=_shell_policy(),
        session=session,
    )


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
    """Minimal provider adapter for exposing canonical traversal to Pi."""

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
    retrieve_parser.add_argument("--glob", default="*")
    retrieve_parser.add_argument("--recursive", action="store_true")

    run_parser = sub.add_parser("run")
    run_parser.add_argument("file")
    run_parser.add_argument("program")
    run_parser.add_argument("--segmenter", default="auto")
    run_parser.add_argument("--last", default="")
    run_parser.add_argument("--since", default="")
    run_parser.add_argument("--until", default="")
    run_parser.add_argument("--fold", action="store_true")

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
    elif args.command == "run":
        payload = _run_shell(args, session)
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
