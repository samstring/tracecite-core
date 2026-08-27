from __future__ import annotations

import pytest

from tracecite.evidence import EntityRef, EvidenceContractError, EvidenceRelation


def test_entity_identity_is_stable_and_namespace_sensitive() -> None:
    first = EntityRef("Session", "S-1", namespace="mobile", attributes={"label": "checkout"})
    same = EntityRef("session", "S-1", namespace="MOBILE")
    other = EntityRef("session", "S-1", namespace="backend")

    assert first.key == same.key
    assert first.key != other.key
    assert first.identity == "mobile:session:S-1"
    assert first.to_dict()["attributes"] == {"label": "checkout"}


def test_relation_serialization_keeps_basis_and_entity() -> None:
    entity = EntityRef("request", "R-9")
    relation = EvidenceRelation(
        "event-a",
        "event-b",
        kind="same_entity",
        basis="exact_entity",
        entity=entity,
    )

    restored = EvidenceRelation.from_mapping(relation.to_dict())
    assert restored == relation
    assert restored.identity == relation.identity


def test_relation_rejects_invalid_confidence() -> None:
    with pytest.raises(EvidenceContractError, match="confidence"):
        EvidenceRelation("a", "b", "related", "rule", confidence=1.1)
