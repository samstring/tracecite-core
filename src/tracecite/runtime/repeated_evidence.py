from __future__ import annotations

from typing import Any, Mapping

from .agent_api import RetrievalResult
from .evidence_coordinates import attach_source_line_coordinates


_REPEAT_REF_FIELDS = ("uri", "source_path", "start_line", "end_line", "sha256")


def matched_existing_evidence(
    result: RetrievalResult,
    *,
    limit: int = 50,
) -> tuple[dict[str, Any], ...]:
    """Return compact identities for canonical evidence already seen by the Agent.

    RetrievalSession novelty suppression deliberately removes repeated evidence
    bodies from the default Agent projection.  A later, materially different
    query can still match those old rows, so the transport must preserve which
    old evidence matched without re-sending its text/preview.  This helper is
    purely mechanical: it reports overlap and makes no claim about relevance,
    importance, causality, or what the Agent should inspect next.
    """

    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("matched-existing evidence limit must be a positive integer")

    canonical_rows = result.canonical_result.get("evidence") or []
    if not isinstance(canonical_rows, (list, tuple)):
        return ()

    new_ids = {
        str(item.get("uri") or "").strip()
        for item in result.new_evidence
        if isinstance(item, Mapping) and str(item.get("uri") or "").strip()
    }
    seen: set[str] = set()
    compact: list[dict[str, Any]] = []
    for item in canonical_rows:
        if not isinstance(item, Mapping):
            continue
        uri = str(item.get("uri") or "").strip()
        if not uri or uri in new_ids or uri in seen:
            continue
        seen.add(uri)
        row = {
            key: item[key]
            for key in _REPEAT_REF_FIELDS
            if key in item and item[key] not in (None, "")
        }
        if row:
            compact.append(row)
        if len(compact) >= limit:
            break
    return tuple(compact)


def attach_matched_existing_evidence(
    result: RetrievalResult,
    *,
    limit: int = 50,
) -> dict[str, Any]:
    """Project novelty, repeated refs, and objective source-line coordinates.

    Coordinates are computed only among rows present in this response (new rows
    plus repeated rows matched by the current request).  A line gap is a source
    geometry fact, never a claim that two evidence rows are semantically related.
    """

    payload = result.to_dict()
    matched = matched_existing_evidence(result, limit=limit)
    new_rows = [
        dict(item)
        for item in payload.get("evidence") or []
        if isinstance(item, Mapping)
    ]
    combined = attach_source_line_coordinates([*new_rows, *matched])
    payload["evidence"] = combined[: len(new_rows)]

    annotated_matched = combined[len(new_rows) :]
    if annotated_matched:
        data = dict(payload.get("data") or {})
        data["matched_existing_evidence"] = [dict(item) for item in annotated_matched]
        payload["data"] = data
    return payload


__all__ = ["attach_matched_existing_evidence", "matched_existing_evidence"]
