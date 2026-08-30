"""Compatibility layer for evidence-integrity enrichment.

Historically this module also turned Evidence gaps into a prioritized next
retrieval action. That crossed the Runtime boundary: TraceCite should expose
Evidence, provenance, coverage, uncertainty, and mechanical identity-safety
facts, while the Agent decides what to investigate next.

The old public function name is retained temporarily for compatibility, but it
no longer plans, ranks, or recommends retrieval actions.
"""

from __future__ import annotations

import copy
from typing import Any, Mapping

from .agent_api import RetrievalResult
from .evidence_view import evidence_only


def _observed_sibling_entities(
    item: Mapping[str, Any],
    *,
    limit: int = 8,
    reference_limit: int = 3,
) -> list[dict[str, Any]]:
    """Project bounded sibling identities already observed by verification.

    These rows are navigation/provenance facts only. A sibling entity being
    present in the same source family does not establish that it reuses the
    ambiguous identifier or that it contributes to a failure.
    """

    rows: list[dict[str, Any]] = []
    for raw in item.get("sibling_entities") or []:
        if not isinstance(raw, Mapping):
            continue
        entity = str(raw.get("entity") or "").strip()
        if not entity:
            continue
        references = [
            str(value).strip()
            for value in raw.get("references") or []
            if str(value).strip()
        ]
        row: dict[str, Any] = {"entity": entity}
        scope = str(raw.get("scope") or "").strip()
        if scope:
            row["scope"] = scope
        occurrence_count = raw.get("occurrence_count")
        if isinstance(occurrence_count, int) and not isinstance(occurrence_count, bool):
            row["occurrence_count"] = occurrence_count
        if references:
            row["references"] = references[:reference_limit]
        rows.append(row)
        if len(rows) >= limit:
            break
    return rows


def _scoped_identity_contract(item: Mapping[str, Any]) -> dict[str, Any] | None:
    if str(item.get("kind") or "") != "scoped_identifier_verification":
        return None
    identifier_key = str(item.get("identifier_key") or "").strip()
    identifier_value = str(item.get("identifier_value") or "").strip()
    if not identifier_key or not identifier_value:
        return None
    entity_count = int(item.get("entity_count_observed") or 0)
    sibling_count = int(item.get("sibling_entity_count_observed") or 0)
    entities = [
        str(row.get("entity") or "").strip()
        for row in item.get("entities") or []
        if isinstance(row, Mapping) and str(row.get("entity") or "").strip()
    ]
    observed_siblings = _observed_sibling_entities(item)
    return {
        "kind": "scoped_local_identifier",
        "identifier_key": identifier_key,
        "identifier_value": identifier_value,
        "scoped_entities": entities,
        "observed_sibling_entities": observed_siblings,
        "observed_sibling_entities_truncated": max(0, sibling_count - len(observed_siblings)),
        "sibling_entity_count_observed": sibling_count,
        "source_uniqueness": "disproved" if entity_count >= 2 else "unverified",
        "identifier_only_correlation_safe": False,
        "required_correlation_components": ["scoped_entity", identifier_key],
        "unsafe_correlation_key": [identifier_key],
        "minimum_safe_correlation_key": ["scoped_entity", identifier_key],
        "scope_fanout_observed": sibling_count > 1,
        "negative_evidence_note": (
            "A source-wide absence of a second explicit identifier association does not prove "
            "that the identifier is globally unique. Preserve the scoped entity together with "
            "the local identifier when interpreting the evidence unless an external identity "
            "contract proves identifier-only uniqueness."
        ),
        "sibling_entity_note": (
            "Observed sibling entities are source-family navigation facts with bounded provenance. "
            "Their presence does not prove that they reuse this identifier."
        ),
    }


def _enrich_identity_contracts(data: Mapping[str, Any]) -> dict[str, Any]:
    enriched = copy.deepcopy(dict(data))
    integrity = enriched.get("evidence_integrity")
    if not isinstance(integrity, Mapping) or not isinstance(
        integrity.get("scoped_identity"), list
    ):
        return enriched

    constraints: list[dict[str, Any]] = []
    updated: list[Any] = []
    for scoped in integrity.get("scoped_identity") or []:
        if not isinstance(scoped, Mapping):
            updated.append(copy.deepcopy(scoped))
            continue
        scoped_copy = copy.deepcopy(dict(scoped))
        source = str(scoped_copy.get("source") or "").strip()
        rows: list[Any] = []
        for raw in scoped_copy.get("identity_verification") or []:
            if not isinstance(raw, Mapping):
                rows.append(copy.deepcopy(raw))
                continue
            item = copy.deepcopy(dict(raw))
            item.setdefault("source", source)
            contract = _scoped_identity_contract(item)
            if contract is not None:
                item["identity_contract"] = contract
                constraints.append(copy.deepcopy(contract))
            rows.append(item)
        scoped_copy["identity_verification"] = rows
        updated.append(scoped_copy)

    integrity_copy = copy.deepcopy(dict(integrity))
    integrity_copy["scoped_identity"] = updated
    enriched["evidence_integrity"] = integrity_copy
    if constraints:
        enriched["correlation_constraints"] = constraints
        enriched["correlation_constraints_note"] = (
            "Mechanical identity-safety facts only. These constraints describe when "
            "identifier-only correlation is unsafe and expose bounded sibling-identity "
            "navigation facts; they do not prescribe an investigation step or identify a root cause."
        )
    return enriched


def prioritize_actionable_retrieval(result: RetrievalResult) -> RetrievalResult:
    """Compatibility name: enrich evidence facts, but never plan retrieval."""

    if not isinstance(result, RetrievalResult):
        raise TypeError("prioritize_actionable_retrieval requires RetrievalResult")

    canonical = copy.deepcopy(dict(result.canonical_result))
    canonical["data"] = _enrich_identity_contracts(canonical.get("data") or {})
    enriched = RetrievalResult(
        operation=result.operation,
        status=result.status,
        canonical_result=canonical,
        progress=result.progress,
        new_evidence=result.new_evidence,
        repeated_evidence=result.repeated_evidence,
        stop_reason=result.stop_reason,
    )
    return evidence_only(enriched)


__all__ = ["prioritize_actionable_retrieval"]
