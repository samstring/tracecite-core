"""Stable experimental facade for evidence relationship contracts.

The implementation currently lives in ``tracecite.evidence`` so existing
experimental callers keep working. Runtime code imports this facade to respect
TraceCite's established dependency direction: Runtime may depend on the public
Extension contract layer, not on a new ad-hoc top-level layer.
"""

from tracecite.evidence import EntityRef, EvidenceContractError, EvidenceRelation

__all__ = ["EvidenceContractError", "EntityRef", "EvidenceRelation"]
