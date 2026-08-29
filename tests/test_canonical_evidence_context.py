from __future__ import annotations

import json

from tracecite.integrations.canonical_ledger import CanonicalLedger
from tracecite.integrations.context_engine import ContextEngine
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
    assert first["context"]["state_owner"] == "RetrievalSession"
    assert second["evidence"] == []
    assert second["groups"] == []
    assert second["relations"] == []
    assert second["context"]["repeated_evidence"] == 2
    assert second["context"]["repeated_groups"] == 1
    assert second["context"]["repeated_relations"] == 1
    assert engine.store.path == tmp_path.resolve() / "_contexts" / "incident-42.json"


def test_search_and_package_views_share_one_seen_evidence_owner(tmp_path) -> None:
    uri = "evidence://sha256/" + ("a" * 64) + "#L7"
    search = {
        "schema_version": 1,
        "operation": "search",
        "status": "ok",
        "outcome": "not_assessed",
        "evidence": [{"uri": uri, "start_line": 7, "end_line": 7, "label": "same fact"}],
        "coverage": {"evidence_returned": 1},
        "data": {},
        "warnings": [],
    }
    package = {
        "package_id": "p1",
        "evidence": [{"uri": uri, "label": "same fact in package"}],
        "groups": [],
        "relations": [],
    }

    search_engine = ContextEngine(tmp_path, "shared")
    package_engine = EvidenceContextEngine(tmp_path, "shared")

    first = search_engine.project_search(search, result_id="b" * 64)
    second = package_engine.project(package)

    assert len(first["evidence"]) == 1
    assert second["evidence"] == []
    assert second["context"]["repeated_evidence"] == 1
    state = package_engine.state()
    assert state.revision == 2
    assert state.seen_results == ("b" * 64,)
    assert state.seen_evidence == (uri,)


def test_package_projection_preserves_search_results_and_search_preserves_groups(tmp_path) -> None:
    uri = "evidence://sha256/" + ("c" * 64) + "#L3"
    search = {
        "schema_version": 1,
        "operation": "search",
        "status": "ok",
        "outcome": "not_assessed",
        "evidence": [{"uri": uri}],
        "coverage": {"evidence_returned": 1},
        "data": {},
        "warnings": [],
    }
    package = {
        "evidence": [{"id": "package-e1"}],
        "groups": [{"id": "g1"}],
        "relations": [{"id": "r1", "source_id": "a", "target_id": "b"}],
    }

    ContextEngine(tmp_path, "preserve").project_search(search, result_id="d" * 64)
    EvidenceContextEngine(tmp_path, "preserve").project(package)
    state_after_package = EvidenceContextEngine(tmp_path, "preserve").state()
    assert state_after_package.seen_results == ("d" * 64,)
    assert state_after_package.seen_groups == ("g1",)
    assert state_after_package.seen_relations == ("r1",)

    ContextEngine(tmp_path, "preserve").project_search(search, result_id="e" * 64)
    final = EvidenceContextEngine(tmp_path, "preserve").state()
    assert final.seen_results == ("d" * 64, "e" * 64)
    assert final.seen_groups == ("g1",)
    assert final.seen_relations == ("r1",)


def test_legacy_evidence_context_file_migrates_on_next_save(tmp_path) -> None:
    legacy_dir = tmp_path / "_evidence_contexts"
    legacy_dir.mkdir()
    legacy = legacy_dir / "legacy.json"
    legacy.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "context_id": "legacy",
                "revision": 4,
                "seen_evidence": ["e1"],
                "seen_groups": ["g1"],
                "seen_relations": ["r1"],
            }
        ),
        encoding="utf-8",
    )

    engine = EvidenceContextEngine(tmp_path, "legacy")
    loaded = engine.state()
    assert loaded.revision == 4
    assert loaded.seen_groups == ("g1",)

    engine.project({"evidence": [{"id": "e2"}], "groups": [], "relations": []})
    canonical = tmp_path / "_contexts" / "legacy.json"
    assert canonical.is_file()
    migrated = json.loads(canonical.read_text(encoding="utf-8"))
    assert migrated["revision"] == 5
    assert migrated["seen_evidence"] == ["e1", "e2"]
    assert migrated["seen_groups"] == ["g1"]
    assert migrated["seen_relations"] == ["r1"]
