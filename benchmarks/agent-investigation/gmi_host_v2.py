from __future__ import annotations

"""Experimental benchmark host with delta-first Evidence Intelligence transport.

This module deliberately changes only the Agent-facing benchmark projection. The
underlying TraceCite evidence contracts, providers, correlation, exploration,
grouping, and reducer remain unchanged.
"""

import json
from typing import Any, Mapping, Sequence

import gmi_host as base
import openai_host as common
from tracecite.extension.evidence import EntityRef, EvidenceRelation
from tracecite.extension.retrieval import ProviderEvidence, RetrieveRequest


_ORIGINAL_TOOLS_FOR_MODE = common._tools_for_mode
_ORIGINAL_INVESTIGATE = common.ToolRuntime._investigate


def _record_view(record: ProviderEvidence) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": record.id,
        "kind": record.kind,
        "source": record.source,
        "entities": [entity.identity for entity in record.entities],
    }
    for key in ("timestamp", "severity", "label", "evidence_uri"):
        value = getattr(record, key)
        if value:
            payload[key if key != "evidence_uri" else "uri"] = value
    if record.attributes:
        payload["attributes"] = dict(record.attributes)
    return payload


def _relation_view(relation: EvidenceRelation) -> list[Any]:
    return [
        relation.source_id,
        relation.target_id,
        relation.kind,
        relation.entity.identity if relation.entity is not None else "",
        relation.confidence,
    ]


def _entity_views(records: Sequence[ProviderEvidence]) -> list[dict[str, str]]:
    unique: dict[tuple[str, str, str], EntityRef] = {}
    for record in records:
        for entity in record.entities:
            unique.setdefault(entity.key, entity)
    return [
        {
            "namespace": entity.namespace,
            "kind": entity.kind,
            "value": entity.value,
            "identity": entity.identity,
        }
        for entity in sorted(unique.values(), key=lambda item: item.key)
    ]


def _delta_response(
    runtime: common.ToolRuntime,
    records: Sequence[ProviderEvidence],
    relations: Sequence[EvidenceRelation],
    *,
    request: Mapping[str, Any],
) -> str:
    before = set(runtime.accumulated)
    runtime._remember(records, relations)
    new_records = [record for record in records if record.id not in before]
    status = "ok" if new_records else ("known_only" if records else "no_match")
    payload = {
        "status": status,
        "request": dict(request),
        "new_evidence": [_record_view(record) for record in new_records],
        "relations": [_relation_view(relation) for relation in relations],
        "next_entities": _entity_views(records),
        "accumulated_evidence": len(runtime.accumulated),
        "known_evidence_ids": sorted(runtime.accumulated),
    }
    if not records:
        payload["hint"] = (
            "No evidence matched. For evidence_entity, pass namespace/kind/value "
            "exactly as returned by next_entities; do not convert an Evidence ID into an EntityRef."
        )
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _evidence_search_v2(self: common.ToolRuntime, args: Mapping[str, Any]) -> str:
    query = str(args.get("query") or "").casefold().strip()
    if not query:
        raise ValueError("query must be non-empty")
    matches: list[ProviderEvidence] = []
    for provider in self.providers:
        for evidence_id in sorted(provider._by_id):  # benchmark fixture enumeration only
            record = provider.get(evidence_id)
            haystack = json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True).casefold()
            if query in haystack:
                matches.append(record)
    matches = matches[:50]
    for record in matches:
        if not self.seed_ids and record.kind == "crash":
            self.seed_ids.append(record.id)
    return _delta_response(self, matches, (), request={"type": "search", "query": query})


def _evidence_get_v2(self: common.ToolRuntime, args: Mapping[str, Any]) -> str:
    evidence_id = str(args.get("evidence_id") or "").strip()
    if not evidence_id:
        raise ValueError("evidence_id must be non-empty")
    request = RetrieveRequest(evidence_ids=(evidence_id,), limit=100, reason="agent_directed_id")
    matched: list[ProviderEvidence] = []
    relations: list[EvidenceRelation] = []
    for provider in self.providers:
        if provider.can_handle(request):
            result = provider.retrieve(request)
            matched.extend(result.evidence)
            relations.extend(result.relations)
    for record in matched:
        if not self.seed_ids and record.kind == "crash":
            self.seed_ids.append(record.id)
    return _delta_response(
        self,
        matched,
        relations,
        request={"type": "evidence_id", "evidence_id": evidence_id},
    )


def _evidence_entity_v2(self: common.ToolRuntime, args: Mapping[str, Any]) -> str:
    entity = EntityRef(
        str(args.get("kind") or ""),
        str(args.get("value") or ""),
        namespace=str(args.get("namespace") or ""),
    )
    request = RetrieveRequest(entities=(entity,), limit=100, reason="agent_directed_entity")
    matched: list[ProviderEvidence] = []
    relations: list[EvidenceRelation] = []
    for provider in self.providers:
        if provider.can_handle(request):
            result = provider.retrieve(request)
            matched.extend(result.evidence)
            relations.extend(result.relations)
    return _delta_response(
        self,
        matched,
        relations,
        request={"type": "entity", "entity": entity.identity},
    )


def _project_investigation(payload: Mapping[str, Any]) -> dict[str, Any]:
    package = dict(payload.get("package") or {})
    evidence_rows: list[dict[str, Any]] = []
    for raw in package.get("evidence") or []:
        if not isinstance(raw, Mapping):
            continue
        row = {
            key: raw[key]
            for key in ("id", "timestamp", "kind", "severity", "label", "source", "entities", "uri")
            if raw.get(key) not in (None, "", [], {})
        }
        evidence_rows.append(row)

    relation_rows: list[list[Any]] = []
    for raw in package.get("relations") or []:
        if not isinstance(raw, Mapping):
            continue
        entity = raw.get("entity") if isinstance(raw.get("entity"), Mapping) else {}
        entity_parts = [
            str(entity.get("namespace") or ""),
            str(entity.get("kind") or ""),
            str(entity.get("value") or ""),
        ]
        entity_identity = ":".join(part for part in entity_parts if part)
        relation_rows.append(
            [
                raw.get("source_id"),
                raw.get("target_id"),
                raw.get("kind"),
                entity_identity,
                raw.get("confidence"),
            ]
        )

    useful_groups: list[dict[str, Any]] = []
    for raw in package.get("groups") or []:
        if not isinstance(raw, Mapping) or int(raw.get("count") or 0) <= 1:
            continue
        useful_groups.append(
            {
                key: raw[key]
                for key in ("id", "kind", "source", "count", "template", "included_representatives")
                if key in raw
            }
        )

    coverage = dict(payload.get("coverage") or {})
    compact_coverage = {
        key: coverage[key]
        for key in (
            "complete",
            "evidence",
            "sources",
            "retrievals",
            "stop_reason",
            "provider_errors",
            "missing_seed_ids",
            "unsupported_entities",
        )
        if key in coverage
    }
    result: dict[str, Any] = {
        "status": payload.get("status"),
        "stop_reason": payload.get("stop_reason"),
        "coverage": compact_coverage,
        "evidence": evidence_rows,
        "relations": relation_rows,
    }
    if useful_groups:
        result["groups"] = useful_groups
    return result


def _investigate_v2(self: common.ToolRuntime, args: Mapping[str, Any]) -> str:
    raw = _ORIGINAL_INVESTIGATE(self, args)
    payload = json.loads(raw)
    if not isinstance(payload, Mapping):
        return raw
    return json.dumps(_project_investigation(payload), ensure_ascii=False, sort_keys=True)


def _tools_for_mode_v2(mode: str, files: Sequence[Any]) -> list[dict[str, Any]]:
    if mode != "tracecite_intelligence":
        return _ORIGINAL_TOOLS_FOR_MODE(mode, files)
    return [
        common._function_tool(
            "evidence_search",
            "Substring-search provider evidence. Returns only newly discovered evidence plus exact next_entities. Use this to find a seed; do not expect a full package on every call.",
            {"query": {"type": "string"}},
            ["query"],
        ),
        common._function_tool(
            "evidence_get",
            "Retrieve a concrete Evidence ID exactly as shown in new_evidence or known_evidence_ids, for example crash:C123. Evidence IDs are not EntityRefs.",
            {"evidence_id": {"type": "string"}},
            ["evidence_id"],
        ),
        common._function_tool(
            "evidence_entity",
            "Expand one correlation entity. Pass namespace/kind/value exactly from next_entities. Never pass an Evidence ID such as crash:C123 as an EntityRef.",
            {
                "namespace": {"type": "string"},
                "kind": {"type": "string"},
                "value": {"type": "string"},
            },
            ["namespace", "kind", "value"],
        ),
    ]


def _call_v2(self: common.ToolRuntime, name: str, args: Mapping[str, Any]) -> str:
    if self.mode == "tracecite_intelligence":
        if name == "evidence_search":
            return _evidence_search_v2(self, args)
        if name == "evidence_get":
            return _evidence_get_v2(self, args)
        if name == "evidence_entity":
            return _evidence_entity_v2(self, args)
    if self.mode == "tracecite_investigate" and name == "investigate_runtime_evidence":
        return _investigate_v2(self, args)
    return _ORIGINAL_CALL(self, name, args)


_ORIGINAL_CALL = common.ToolRuntime.call
common._tools_for_mode = _tools_for_mode_v2
common.ToolRuntime.call = _call_v2


if __name__ == "__main__":
    try:
        raise SystemExit(base.run())
    except Exception as exc:
        transcript_value = base.os.environ.get("TRACECITE_BENCH_TRANSCRIPT", "").strip()
        if transcript_value:
            try:
                common._append_event(
                    base.Path(transcript_value),
                    {"type": "host_error", "error": type(exc).__name__, "message": str(exc)},
                )
            except Exception:
                pass
        print(f"benchmark host failed: {type(exc).__name__}: {exc}", file=base.os.sys.stderr)
        raise
