from __future__ import annotations

import hashlib
from pathlib import Path

from tracecite.runtime import EvidenceRequest, InvestigationStore, QueryTarget, RangeTarget
from tracecite.runtime import agent_api as agent_api_module
from tracecite.runtime import investigation as investigation_module
from tracecite.runtime import session_retrieval as session_retrieval_module
from tracecite.runtime import tools
from tracecite.runtime.evidence_fidelity import enrich_search_leaf_context
from tracecite.runtime.investigation import InvestigationCacheStore
from tracecite.runtime.retrieval_session import RetrievalSessionStore
from tracecite.runtime.session_retrieval import retrieve_with_session


def test_stateless_no_snapshot_search_hashes_evidence_source_once(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "runtime.log"
    source.write_text("INFO boot\nERROR needle request=7\nINFO done\n", encoding="utf-8")
    original = tools._sha256
    calls = 0

    def counted(path: Path) -> str:
        nonlocal calls
        calls += 1
        return original(path)

    monkeypatch.setattr(tools, "_sha256", counted)
    result = tools.search(
        source, "needle", snapshot=False, segmenter="rawtext", cache=False
    )

    assert result["status"] == "ok"
    assert calls == 1


def test_cache_hashes_unique_evidence_source_once_per_put_and_lookup(tmp_path: Path, monkeypatch) -> None:
    original_source = tmp_path / "source.log"
    evidence_source = tmp_path / "snapshot.log"
    body = "needle\n"
    original_source.write_text(body, encoding="utf-8")
    evidence_source.write_text(body, encoding="utf-8")
    original_digest = hashlib.sha256(original_source.read_bytes()).hexdigest()
    evidence_digest = hashlib.sha256(evidence_source.read_bytes()).hexdigest()
    store = InvestigationCacheStore(tmp_path / "cache.json")
    result = {
        "operation": "search",
        "status": "ok",
        "evidence": [
            {
                "uri": f"evidence://sha256/{evidence_digest}#L1",
                "source_path": str(evidence_source),
                "sha256": evidence_digest,
                "start_line": 1,
                "end_line": 1,
            }
            for _ in range(20)
        ],
        "artifacts": [],
        "coverage": {},
        "data": {},
    }
    original_hash = investigation_module._path_sha256
    calls: list[str] = []

    def counted(path: Path) -> str:
        calls.append(str(Path(path).resolve()))
        return original_hash(path)

    monkeypatch.setattr(investigation_module, "_path_sha256", counted)
    refs = [{"path": str(original_source), "sha256": original_digest}]
    store.put(
        "k", operation="search", result=result, source_refs=refs,
        parameters={"query": "needle"}, segmenter="rawtext", snapshot=True,
    )
    assert calls == [str(evidence_source.resolve())]

    calls.clear()
    cached, meta = store.lookup(
        "k", source_refs=refs, operation="search",
        parameters={"query": "needle"}, segmenter="rawtext", snapshot=True,
    )
    assert cached is not None
    assert meta["status"] == "hit"
    assert calls.count(str(original_source.resolve())) == 1
    assert calls.count(str(evidence_source.resolve())) == 1
    assert len(calls) == 2


def test_novel_expected_range_does_not_pre_hash_in_agent_api(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "runtime.log"
    source.write_text("one\ntwo\nthree\n", encoding="utf-8")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    state_path = tmp_path / "investigation.json"
    InvestigationStore(state_path).create("test range cost")
    calls = 0
    original = agent_api_module._sha256

    def counted(path: Path) -> str:
        nonlocal calls
        calls += 1
        return original(path)

    monkeypatch.setattr(agent_api_module, "_sha256", counted)
    result = agent_api_module.retrieve(
        EvidenceRequest(
            RangeTarget(source, 2, before=0, after=0, expected_sha256=digest),
            investigation_path=state_path,
        )
    )
    assert result.status == "ok"
    assert calls == 0


def test_novel_expected_range_does_not_pre_hash_in_standalone_session(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "runtime.log"
    source.write_text("one\ntwo\nthree\n", encoding="utf-8")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    session = RetrievalSessionStore(
        tmp_path, "cost", namespace="_retrieval_sessions", legacy_evidence_context=False
    )
    calls = 0
    original = session_retrieval_module._sha256

    def counted(path: Path) -> str:
        nonlocal calls
        calls += 1
        return original(path)

    monkeypatch.setattr(session_retrieval_module, "_sha256", counted)
    result = retrieve_with_session(
        EvidenceRequest(
            RangeTarget(source, 2, before=0, after=0, expected_sha256=digest)
        ),
        session,
    )
    assert result.status == "ok"
    assert calls == 0


def test_integrity_enrichment_emits_gap_facts_without_next_query_planning(tmp_path: Path) -> None:
    source = tmp_path / "evidence.log"
    source.write_text(
        "name: resource.example/widget-1001\n"
        "resources:\n"
        "- health: Healthy\n"
        "localID: local-device\n"
        "name: resource.example/widget-1001\n"
        "- health: Unhealthy\n"
        "localID: local-device\n"
        "resource.example/widget-1002 ready\n"
        "resource.example/widget-1003 ready\n",
        encoding="utf-8",
    )
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    payload = {
        "operation": "search",
        "status": "ok",
        "outcome": "not_assessed",
        "coverage": {"evidence_returned": 1},
        "data": {"query": "Unhealthy"},
        "evidence": [{
            "uri": f"evidence://sha256/{digest}#L6",
            "source_path": str(source),
            "sha256": digest,
            "start_line": 6,
            "end_line": 6,
            "label": "- health: Unhealthy",
        }],
    }
    result = enrich_search_leaf_context(payload)
    assert "next_queries" not in result
    for gap in result.get("missing_evidence") or []:
        assert "recommended_action" not in gap
    integrity = result.get("data", {}).get("evidence_integrity", {})
    for scoped in integrity.get("scoped_identity") or []:
        for hint in scoped.get("scoped_identity_hints") or []:
            assert "recommended_search" not in hint
            assert "recommended_action" not in hint
            assert "navigation_query" not in hint


def test_single_literal_candidate_scan_does_not_call_full_matcher_per_source_line(tmp_path: Path, monkeypatch) -> None:
    from tracecite_core.candidate_search import scan_candidate_lines
    from tracecite_core.matcher import Matcher

    source = tmp_path / "large.log"
    source.write_text("noise\n" * 1000 + "needle here\n", encoding="utf-8")
    matcher = Matcher("needle")
    assert matcher.engine == "literal"

    calls = 0
    original = matcher.match

    def counted(value: str):
        nonlocal calls
        calls += 1
        return original(value)

    monkeypatch.setattr(matcher, "match", counted)
    scan = scan_candidate_lines(source, matcher, capture_lines=True)
    assert scan is not None
    assert scan.line_numbers == frozenset({1001})
    assert calls == 0
