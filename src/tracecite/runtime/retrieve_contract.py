"""Public retrieve contract corrections over the canonical Agent API.

The underlying Agent API tracks both evidence identities and versioned line
coverage. A search can expose an Evidence URI without exposing the surrounding
raw context. When a later RangeTarget actually grows covered lines, that is new
retrieval progress even if the pointer identity itself was already seen.
"""

from __future__ import annotations

from typing import Mapping

from .agent_api import (
    EvidenceRequest,
    RangeTarget,
    RetrievalResult,
    retrieve as _retrieve,
)


def retrieve(request: EvidenceRequest) -> RetrievalResult:
    """Execute the public canonical retrieval contract.

    Preserve the underlying implementation for all targets, but correct the
    RangeTarget projection when newly covered context lines were acquired after
    the same Evidence URI had already appeared in a search result. Pointer
    novelty and context-coverage novelty are deliberately different signals.
    """

    result = _retrieve(request)
    if not isinstance(request.target, RangeTarget):
        return result
    if result.status != "no_new_evidence" or result.progress.delta.new_lines <= 0:
        return result

    canonical_evidence = tuple(
        dict(item)
        for item in result.canonical_result.get("evidence") or []
        if isinstance(item, Mapping)
    )
    status = str(result.canonical_result.get("status") or "ok")
    if status == "error":
        return result
    return RetrievalResult(
        operation=result.operation,
        status=status,
        canonical_result=result.canonical_result,
        progress=result.progress,
        new_evidence=canonical_evidence,
        repeated_evidence=result.repeated_evidence,
        stop_reason=None,
    )


__all__ = ["retrieve"]
