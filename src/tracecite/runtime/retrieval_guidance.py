"""Mechanical guidance for closing actionable Evidence gaps.

This module is deliberately domain-neutral. It does not infer a cause or choose
between hypotheses. It only turns canonical ``missing_evidence`` entries that
already contain a Runtime-produced ``recommended_action`` into one explicit,
prioritized retrieval action for Agent hosts.

The guidance is transport/retrieval control state:

- only actionable gaps are considered;
- only actions already emitted by canonical Runtime are surfaced;
- no source is reopened and no new Evidence is discovered here;
- heuristic ``next_queries`` remain available, but gap-closing queries are
  moved ahead of them so known integrity work is not buried by generic terms.
"""

from __future__ import annotations

import copy
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


def prioritize_actionable_retrieval(result: RetrievalResult) -> RetrievalResult:
    """Expose one deterministic next retrieval action from known Evidence gaps.

    This is intentionally conservative: it never invents a query/action. The
    selected action is the first actionable gap in canonical order that already
    carries ``recommended_action``. That preserves Runtime ownership of gap
    semantics while giving Agent hosts an unambiguous mechanical next step.
    """

    if not isinstance(result, RetrievalResult):
        raise TypeError("prioritize_actionable_retrieval requires RetrievalResult")

    canonical = copy.deepcopy(dict(result.canonical_result))
    gaps = [
        dict(item)
        for item in canonical.get("missing_evidence") or []
        if isinstance(item, Mapping) and item.get("actionable") is True
    ]
    action = next((value for item in gaps if (value := _action_from_gap(item)) is not None), None)
    if action is None:
        return result

    data = dict(canonical.get("data") or {})
    data["actionable_retrieval"] = action
    data["actionable_retrieval_note"] = (
        "Mechanical evidence-gap closure only. Execute this retrieval action before treating "
        "the corresponding integrity gap as closed; it is not a root-cause recommendation."
    )
    canonical["data"] = data

    query = str(action.get("query") or "").strip()
    if query:
        existing = [
            str(item)
            for item in canonical.get("next_queries") or []
            if str(item).strip() and str(item) != query
        ]
        canonical["next_queries"] = [query, *existing]

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
