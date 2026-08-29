"""Mechanical guidance for closing actionable Evidence gaps.

This module is deliberately domain-neutral. It does not infer a cause or choose
between hypotheses. It post-processes canonical Runtime evidence-integrity state
into explicit correlation constraints and one prioritized mechanical retrieval
action for Agent hosts.
"""

from __future__ import annotations

import copy
import os
import re
from typing import Any, Mapping

from .agent_api import RetrievalResult


def _action_from_gap(gap: Mapping[str, Any]) -> dict[str, Any] | None:
    if gap.get("actionable") is not True:
        return None
    raw = gap.get("recommended_action")
    if not isinstance(raw, Mapping):
        return None
    operation = str(raw.get("operation") or "").strip()
    if not operation:
        return None
    action = {
        key: copy.deepcopy(value)
        for key, value in raw.items()
        if value not in (None, "", [], ())
    }
    action["operation"] = operation
    action["gap_kind"] = str(gap.get("kind") or "").strip() or "evidence_gap"
    source = str(gap.get("source") or "").strip()
    if source:
        action["source"] = source
    return action


def _identity_key(item: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(item.get("source") or "").strip(),
        str(item.get("identifier_key") or "").strip(),
        str(item.get("identifier_value") or "").strip(),
    )


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
    return {
        "kind": "scoped_local_identifier",
        "identifier_key": identifier_key,
        "identifier_value": identifier_value,
        "scoped_entities": entities,
        "sibling_entity_count_observed": sibling_count,
        "source_uniqueness": "disproved" if entity_count >= 2 else "unverified",
        "identifier_only_correlation_safe": False,
        "required_correlation_components": ["scoped_entity", identifier_key],
        "negative_evidence_note": (
            "A source-wide absence of a second explicit identifier association does not prove "
            "that the identifier is globally unique. Preserve the scoped entity together with "
            "the local identifier for correlation unless an external identity contract proves "
            "identifier-only uniqueness."
        ),
    }


def _enrich_identity_contracts(
    data: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[tuple[str, str, str], dict[str, Any]]]:
    enriched = copy.deepcopy(dict(data))
    integrity = enriched.get("evidence_integrity")
    if not isinstance(integrity, Mapping) or not isinstance(
        integrity.get("scoped_identity"), list
    ):
        return enriched, {}

    verification_index: dict[tuple[str, str, str], dict[str, Any]] = {}
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
                verification_index[_identity_key(item)] = item
            rows.append(item)
        scoped_copy["identity_verification"] = rows
        updated.append(scoped_copy)

    integrity_copy = copy.deepcopy(dict(integrity))
    integrity_copy["scoped_identity"] = updated
    enriched["evidence_integrity"] = integrity_copy
    if constraints:
        enriched["correlation_constraints"] = constraints
        enriched["correlation_constraints_note"] = (
            "Mechanical identity safety only. These constraints prevent unsafe identifier-only "
            "correlation; they do not claim that a collision occurred or identify a root cause."
        )
    return enriched, verification_index


def _common_instance_family(values: list[str]) -> str | None:
    """Return a deterministic family prefix from observed instance-like values."""

    values = list(dict.fromkeys(str(value or "").strip() for value in values if str(value or "").strip()))
    if len(values) < 2:
        return None
    original = os.path.commonprefix(values)
    prefix = original.rstrip("0123456789-_.:/")
    # Preserve the shared delimiter before differing numeric/instance suffixes.
    if len(original) > len(prefix) and original[len(prefix) :]:
        prefix = original
    prefix = re.sub(r"\d+$", "", prefix)
    if len(prefix) < 6 or all(value == prefix for value in values):
        return None
    return prefix


def _observed_entities(verification: Mapping[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("entities", "sibling_entities"):
        for row in verification.get(key) or []:
            if not isinstance(row, Mapping):
                continue
            value = str(row.get("entity") or "").strip()
            if value:
                values.append(value)
    return list(dict.fromkeys(values))


def _entity_family_query(verification: Mapping[str, Any]) -> str | None:
    """Derive a scoped sibling-family query only from Runtime-observed entities."""

    return _common_instance_family(_observed_entities(verification))


def _member_family_query(verification: Mapping[str, Any]) -> str | None:
    """Derive an unscoped member-family query from Runtime-observed scoped entities.

    A scoped entity can later appear in logs as a namespace/member without its
    scope prefix. Searching the observed member family is therefore a mechanical
    evidence-navigation step, not a domain or causal inference.
    """

    members: list[str] = []
    for entity in _observed_entities(verification):
        member = entity.split("/", 1)[1] if "/" in entity else entity
        member = member.strip()
        if member:
            members.append(member)
    return _common_instance_family(members)


def _finish_family_scan(gap: dict[str, Any]) -> dict[str, Any]:
    gap["actionable"] = False
    gap.pop("recommended_action", None)
    gap["detail"] = (
        "The bounded sibling-family correlation scan has been completed. Identifier-only "
        "correlation remains unsafe because uniqueness is still not established, but the "
        "Runtime has no further deterministic identity retrieval action to require. Preserve "
        "the scoped entity together with the local identifier when reasoning from the evidence."
    )
    return gap


def _refine_scoped_gap_action(
    gap: dict[str, Any],
    *,
    current_query: str,
    verification: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if (
        str(gap.get("kind") or "") != "scope_uniqueness_unverified"
        or verification is None
    ):
        return gap

    status = str(verification.get("status") or "").strip()
    if status == "multiple_scoped_entities_observed":
        gap["actionable"] = False
        gap.pop("recommended_action", None)
        gap["detail"] = (
            "The same local identifier is directly associated with multiple scoped entities "
            "in the stable source; identifier-only correlation is therefore unsafe."
        )
        return gap

    identifier = str(gap.get("identifier_value") or "").strip()
    entities = [
        str(row.get("entity") or "").strip()
        for row in verification.get("entities") or []
        if isinstance(row, Mapping) and str(row.get("entity") or "").strip()
    ]
    contract = verification.get("identity_contract")
    if isinstance(contract, Mapping):
        gap["correlation_constraint"] = copy.deepcopy(dict(contract))

    if status != "uniqueness_unverified_with_sibling_scope_fanout":
        return gap

    scoped_family = _entity_family_query(verification)
    member_family = _member_family_query(verification)

    if identifier and current_query == identifier and entities:
        entity = entities[0]
        gap["detail"] = (
            f"{gap.get('identifier_key')}={identifier} remains scope-ambiguous after the stable "
            "source identifier scan. Absence of a second explicit association does not establish "
            "global uniqueness; trace the observed scoped entity before using identifier-only "
            "correlation."
        )
        gap["recommended_action"] = {
            "operation": "search",
            "query": entity,
            "purpose": "trace_scoped_entity_references",
        }
        return gap

    if current_query in entities and scoped_family and scoped_family != current_query:
        gap["detail"] = (
            "The observed scoped entity has been traced, but identifier uniqueness remains "
            "unresolved while sibling entities coexist. Search the Runtime-observed scoped "
            "sibling family before closing the identity gap."
        )
        gap["recommended_action"] = {
            "operation": "search",
            "query": scoped_family,
            "purpose": "trace_sibling_entity_family_references",
        }
        return gap

    if scoped_family and current_query == scoped_family:
        if member_family and member_family != scoped_family:
            gap["detail"] = (
                "The scoped sibling family has been traced, but sibling identities can also "
                "appear in runtime evidence without the scope prefix. Search the Runtime-observed "
                "member family once to recover those cross-entity event references."
            )
            gap["recommended_action"] = {
                "operation": "search",
                "query": member_family,
                "purpose": "trace_sibling_member_family_references",
            }
            return gap
        return _finish_family_scan(gap)

    if member_family and current_query == member_family:
        return _finish_family_scan(gap)

    return gap


def prioritize_actionable_retrieval(result: RetrievalResult) -> RetrievalResult:
    if not isinstance(result, RetrievalResult):
        raise TypeError("prioritize_actionable_retrieval requires RetrievalResult")

    canonical = copy.deepcopy(dict(result.canonical_result))
    data, index = _enrich_identity_contracts(canonical.get("data") or {})
    current_query = str(data.get("query") or "").strip()
    rewritten: list[Any] = []
    for raw in canonical.get("missing_evidence") or []:
        if not isinstance(raw, Mapping):
            rewritten.append(copy.deepcopy(raw))
            continue
        gap = copy.deepcopy(dict(raw))
        key = (
            str(gap.get("source") or "").strip(),
            str(gap.get("identifier_key") or "").strip(),
            str(gap.get("identifier_value") or "").strip(),
        )
        rewritten.append(
            _refine_scoped_gap_action(
                gap,
                current_query=current_query,
                verification=index.get(key),
            )
        )
    canonical["missing_evidence"] = rewritten

    gaps = [
        dict(item)
        for item in rewritten
        if isinstance(item, Mapping) and item.get("actionable") is True
    ]
    action = next(
        (value for item in gaps if (value := _action_from_gap(item)) is not None),
        None,
    )
    if action is not None:
        data["actionable_retrieval"] = action
        data["actionable_retrieval_note"] = (
            "Mechanical evidence-gap closure only. Execute this retrieval action before "
            "treating the corresponding integrity gap as closed; it is not a root-cause "
            "recommendation."
        )
        query = str(action.get("query") or "").strip()
        if query:
            existing = [
                str(item)
                for item in canonical.get("next_queries") or []
                if str(item).strip() and str(item) != query
            ]
            canonical["next_queries"] = [query, *existing]
    else:
        data.pop("actionable_retrieval", None)
        data.pop("actionable_retrieval_note", None)

    canonical["data"] = data
    if canonical == result.canonical_result:
        return result
    return RetrievalResult(
        operation=result.operation,
        status=result.status,
        canonical_result=canonical,
        progress=result.progress,
        new_evidence=result.new_evidence,
        repeated_evidence=result.repeated_evidence,
        stop_reason=result.stop_reason,
    )


__all__ = ["prioritize_actionable_retrieval"]
