from __future__ import annotations

from tracecite.integrations.canonical_ledger import CanonicalLedger
from tracecite.integrations.evidence_context import EvidenceContextEngine


def test_canonical_ledger_accepts_non_search_artifacts(tmp_path) -> None:
    ledger = CanonicalLedger(tmp_path / "ledger")
    payload = {"schema_version": 1, "package_id": "p1", "evidence": [{"id": "e1"}]}

    artifact_id = ledger.store(payload, kind="evidence_package")
    loaded = ledger.load(artifact_id)

    assert loaded["kind"] == "evidence_package"
    assert loaded["payload"] == payload
    assert ledger.store(payload, kind="evidence_package") == artifact_id


def test_generic_context_suppresses_evidence_groups_and_relations(tmp_path) -> None:
    engine = EvidenceContextEngine(tmp_path, "incident-42")
    payload = {
        "package_id": "p1",
        "evidence": [{"id": "e1"}, {"id": "e2"}],
        "groups": [{"id": "g1"}],
        "relations": [{"source_id": "e1", "target_id": "e2", "kind": "same_entity", "basis": "exact_entity"}],
    }

    first = engine.project(payload)
    second = engine.project(payload)

    assert len(first["evidence"]) == 2
    assert len(first["groups"]) == 1
    assert len(first["relations"]) == 1
    assert second["evidence"] == []
    assert second["groups"] == []
    assert second["relations"] == []
    assert second["context"]["repeated_evidence"] == 2
    assert second["context"]["repeated_groups"] == 1
    assert second["context"]["repeated_relations"] == 1
