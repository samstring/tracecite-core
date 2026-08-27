"""Token-aware Agent projection for correlated canonical evidence."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Any, Mapping

from tracecite.runtime.correlation import CorrelationGraph, EvidenceNode
from tracecite.runtime.grouping import GroupingResult
from tracecite.runtime.reducer import ReductionResult, ScoredEvidence


PACKAGE_SCHEMA_VERSION = 1
DEFAULT_MAX_RECOVERY = 32


def estimate_json_tokens(value: Any) -> int:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return max(1, math.ceil(len(encoded) / 4))


@dataclass(frozen=True)
class EvidencePackage:
    package_id: str
    evidence: tuple[Mapping[str, Any], ...]
    groups: tuple[Mapping[str, Any], ...]
    relations: tuple[Mapping[str, Any], ...]
    coverage: Mapping[str, Any]
    budget: Mapping[str, Any]
    recovery: tuple[Mapping[str, Any], ...] = ()
    schema_version: int = PACKAGE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence", tuple(dict(item) for item in self.evidence))
        object.__setattr__(self, "groups", tuple(dict(item) for item in self.groups))
        object.__setattr__(self, "relations", tuple(dict(item) for item in self.relations))
        object.__setattr__(self, "coverage", dict(self.coverage))
        object.__setattr__(self, "budget", dict(self.budget))
        object.__setattr__(self, "recovery", tuple(dict(item) for item in self.recovery))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "package_id": self.package_id,
            "evidence": [dict(item) for item in self.evidence],
            "groups": [dict(item) for item in self.groups],
            "relations": [dict(item) for item in self.relations],
            "coverage": dict(self.coverage),
            "budget": dict(self.budget),
            "recovery": [dict(item) for item in self.recovery],
        }


def _score_index(reduction: ReductionResult) -> dict[str, ScoredEvidence]:
    return {item.id: item for item in reduction.ranked}


def _compact_node(node: EvidenceNode, score: ScoredEvidence | None) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": node.id,
        "kind": node.kind,
        "source": node.source,
    }
    if node.timestamp:
        row["timestamp"] = node.timestamp
    if node.severity:
        row["severity"] = node.severity
    if node.label:
        row["label"] = node.label[:240]
    if node.evidence_uri:
        row["uri"] = node.evidence_uri
    if node.entities:
        row["entities"] = [item.identity for item in node.entities]
    if score is not None:
        row["score"] = round(score.score, 3)
        if score.reasons:
            row["reasons"] = list(score.reasons)
        if score.group_id:
            row["group_id"] = score.group_id
    return row


def _compact_group(group: Any, included: set[str]) -> dict[str, Any]:
    return {
        "id": group.id,
        "count": group.count,
        "source": group.source,
        "kind": group.kind,
        "template": group.template[:160],
        "included_representatives": [item for item in group.representative_ids if item in included],
        "first_timestamp": group.first_timestamp,
        "last_timestamp": group.last_timestamp,
    }


def _compose_payload(
    *,
    evidence_rows: list[dict[str, Any]],
    graph: CorrelationGraph,
    grouping: GroupingResult,
    reduction: ReductionResult,
    max_tokens: int,
    recovery_limit: int,
) -> dict[str, Any]:
    included = {item["id"] for item in evidence_rows}
    group_ids = {
        grouping.node_to_group[node_id]
        for node_id in included
        if node_id in grouping.node_to_group
    }
    groups = [_compact_group(group, included) for group in grouping.groups if group.id in group_ids]
    relations = [
        relation.to_dict()
        for relation in graph.relations
        if relation.source_id in included and relation.target_id in included
    ]
    omitted_budget_ids = [item for item in reduction.selected_ids if item not in included]
    recovery: list[dict[str, Any]] = []
    for node_id in omitted_budget_ids[:recovery_limit]:
        node = graph.by_id[node_id]
        item: dict[str, Any] = {"id": node_id, "reason": "budget"}
        if node.evidence_uri:
            item["uri"] = node.evidence_uri
        recovery.append(item)
    coverage = {
        "canonical_evidence": len(graph.nodes),
        "group_count": len(grouping.groups),
        "reducer_candidates": reduction.candidate_count,
        "reducer_selected": len(reduction.selected_ids),
        "package_evidence": len(evidence_rows),
        "omitted_non_representative": reduction.omitted_non_representative,
        "omitted_reducer_limit": reduction.omitted_by_limit,
        "omitted_budget": len(omitted_budget_ids),
        "truncated": bool(
            reduction.omitted_non_representative
            or reduction.omitted_by_limit
            or omitted_budget_ids
        ),
    }
    return {
        "schema_version": PACKAGE_SCHEMA_VERSION,
        "evidence": evidence_rows,
        "groups": groups,
        "relations": relations,
        "coverage": coverage,
        "recovery": recovery,
        "budget": {"max_tokens": max_tokens},
    }


def build_evidence_package(
    graph: CorrelationGraph,
    grouping: GroupingResult,
    reduction: ReductionResult,
    *,
    max_tokens: int = 3000,
    recovery_limit: int = DEFAULT_MAX_RECOVERY,
) -> EvidencePackage:
    """Project canonical correlated evidence into a bounded Agent package.

    This function never mutates the graph/grouping/reduction inputs. If the
    complete reduced selection does not fit, lowest-priority selected evidence
    is removed until the serialized package fits the requested budget.
    """

    if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or max_tokens < 256:
        raise ValueError("max_tokens must be an integer >= 256")
    if isinstance(recovery_limit, bool) or recovery_limit < 0:
        raise ValueError("recovery_limit must be non-negative")

    by_id = graph.by_id
    scores = _score_index(reduction)
    selected = [node_id for node_id in reduction.selected_ids if node_id in by_id]
    evidence_rows = [_compact_node(by_id[node_id], scores.get(node_id)) for node_id in selected]

    payload = _compose_payload(
        evidence_rows=evidence_rows,
        graph=graph,
        grouping=grouping,
        reduction=reduction,
        max_tokens=max_tokens,
        recovery_limit=recovery_limit,
    )
    while len(evidence_rows) > 1 and estimate_json_tokens(payload) > max_tokens:
        evidence_rows.pop()
        payload = _compose_payload(
            evidence_rows=evidence_rows,
            graph=graph,
            grouping=grouping,
            reduction=reduction,
            max_tokens=max_tokens,
            recovery_limit=recovery_limit,
        )

    used_tokens = estimate_json_tokens(payload)
    payload["budget"] = {
        "max_tokens": max_tokens,
        "estimated_tokens": used_tokens,
        "within_budget": used_tokens <= max_tokens,
        "estimator": "json_chars_div_4",
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    package_id = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return EvidencePackage(
        package_id=package_id,
        evidence=tuple(payload["evidence"]),
        groups=tuple(payload["groups"]),
        relations=tuple(payload["relations"]),
        coverage=payload["coverage"],
        budget=payload["budget"],
        recovery=tuple(payload["recovery"]),
    )


__all__ = ["EvidencePackage", "PACKAGE_SCHEMA_VERSION", "build_evidence_package", "estimate_json_tokens"]
