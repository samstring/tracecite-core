from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def replace_once(rel: str, old: str, new: str) -> None:
    path = ROOT / rel
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"expected block not found in {rel}: {old[:120]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    # tools.search: do not hash the original source unless a linked cache key
    # actually needs that identity. Stateless/no-snapshot search still hashes the
    # evidence source once after filtering so EvidencePointer provenance is unchanged.
    replace_once(
        "src/tracecite/runtime/tools.py",
        '''        kind = detect_segmenter_kind(source) if segmenter == "auto" else segmenter\n        source_sha256 = _sha256(source)\n        source_refs = [{"path": str(source), "sha256": source_sha256}]\n''',
        '''        kind = detect_segmenter_kind(source) if segmenter == "auto" else segmenter\n        cache_identity_needed = bool(\n            investigation_path is not None and cache and cache_safe\n        )\n        source_sha256 = _sha256(source) if cache_identity_needed else ""\n        source_refs = (\n            [{"path": str(source), "sha256": source_sha256}]\n            if source_sha256\n            else []\n        )\n''',
    )
    replace_once(
        "src/tracecite/runtime/tools.py",
        '''        evidence_source = Path(result.work_input).resolve()\n        digest = _sha256(evidence_source)\n''',
        '''        evidence_source = Path(result.work_input).resolve()\n        digest = (\n            source_sha256\n            if source_sha256 and evidence_source == source\n            else _sha256(evidence_source)\n        )\n''',
    )
    replace_once(
        "src/tracecite/runtime/tools.py",
        '''        cache_source_changed = bool(cache_safe and digest != source_sha256)\n''',
        '''        cache_source_changed = bool(\n            cache_identity_needed and digest != source_sha256\n        )\n''',
    )

    # Agent API: expected_sha256 is already the requested immutable identity.
    # Hash only when an already-covered fast return would otherwise skip the
    # materialization read. Novel materialization is verified by tools.expand.
    replace_once(
        "src/tracecite/runtime/agent_api.py",
        '''        source_key: str | None = None\n        if target.expected_sha256:\n            expected = str(target.expected_sha256).lower()\n            if path.is_file() and _sha256(path) == expected:\n                source_key = file_source_version(str(path), expected).key\n                if tracker.range_is_covered(source_key, context_start, context_end):\n                    return _no_new_result(\n                        operation="expand",\n                        tracker=tracker,\n                        source_key=source_key,\n                        basis=("immutable_source_identity", "requested_context_already_covered"),\n                    )\n''',
        '''        source_key: str | None = None\n        if target.expected_sha256 and path.is_file():\n            expected = str(target.expected_sha256).lower()\n            expected_source_key = file_source_version(str(path), expected).key\n            if tracker.range_is_covered(\n                expected_source_key, context_start, context_end\n            ) and _sha256(path) == expected:\n                return _no_new_result(\n                    operation="expand",\n                    tracker=tracker,\n                    source_key=expected_source_key,\n                    basis=("immutable_source_identity", "requested_context_already_covered"),\n                )\n''',
    )

    # Standalone RetrievalSession has the same optimization: do not hash merely
    # to discover that a novel range is not yet covered. If it is covered, keep
    # the full SHA verification before suppressing the body.
    replace_once(
        "src/tracecite/runtime/session_retrieval.py",
        '''def _already_covered_range(\n    request: EvidenceRequest,\n    tracker: EvidenceProgressTracker,\n    state: RetrievalSessionState,\n) -> tuple[str, int, int, dict[str, Any] | None] | None:\n    target = request.target\n    identity = _range_source_identity(request, state)\n    if not isinstance(target, RangeTarget) or identity is None:\n        return None\n    source_key, observation = identity\n    selected_end = target.end_line or target.start_line\n    start = max(1, target.start_line - max(0, target.before))\n    end = selected_end + max(0, target.after)\n    if tracker.range_is_covered(source_key, start, end):\n        return source_key, start, end, observation\n    return None\n''',
        '''def _already_covered_range(\n    request: EvidenceRequest,\n    tracker: EvidenceProgressTracker,\n    state: RetrievalSessionState,\n) -> tuple[str, int, int, dict[str, Any] | None] | None:\n    target = request.target\n    if not isinstance(target, RangeTarget):\n        return None\n    selected_end = target.end_line or target.start_line\n    start = max(1, target.start_line - max(0, target.before))\n    end = selected_end + max(0, target.after)\n\n    if target.expected_sha256:\n        path = Path(target.source).expanduser().resolve()\n        if not path.is_file():\n            return None\n        expected = str(target.expected_sha256).strip().lower()\n        source_key = file_source_version(str(path), expected).key\n        if not tracker.range_is_covered(source_key, start, end):\n            return None\n        if _sha256(path).lower() != expected:\n            return None\n        return source_key, start, end, None\n\n    identity = _range_source_identity(request, state)\n    if identity is None:\n        return None\n    source_key, observation = identity\n    if tracker.range_is_covered(source_key, start, end):\n        return source_key, start, end, observation\n    return None\n''',
    )

    # Cache validation: keep full SHA validation but memoize it per path during
    # one lookup and store only unique Evidence source identities.
    replace_once(
        "src/tracecite/runtime/investigation.py",
        '''    @staticmethod\n    def _source_refs_valid(source_refs: Sequence[Mapping[str, Any]]) -> tuple[bool, str]:\n        for item in source_refs:\n            path = Path(str(item.get("path") or "")).expanduser()\n            expected = str(item.get("sha256") or "")\n            if not path.is_file():\n                return False, "source_missing"\n            if not re.fullmatch(r"[0-9a-fA-F]{64}", expected):\n                return False, "source_sha256_missing"\n            try:\n                actual = _path_sha256(path)\n            except OSError:\n                return False, "source_unreadable"\n            if actual != expected:\n                return False, "source_sha256_changed"\n        return True, ""\n''',
        '''    @staticmethod\n    def _source_refs_valid(\n        source_refs: Sequence[Mapping[str, Any]],\n        *,\n        digest_cache: Optional[Dict[str, str]] = None,\n    ) -> tuple[bool, str]:\n        verified = digest_cache if digest_cache is not None else {}\n        for item in source_refs:\n            path = Path(str(item.get("path") or "")).expanduser()\n            expected = str(item.get("sha256") or "")\n            if not path.is_file():\n                return False, "source_missing"\n            if not re.fullmatch(r"[0-9a-fA-F]{64}", expected):\n                return False, "source_sha256_missing"\n            key = str(path.resolve())\n            try:\n                actual = verified.get(key)\n                if actual is None:\n                    actual = _path_sha256(path)\n                    verified[key] = actual\n            except OSError:\n                return False, "source_unreadable"\n            if actual != expected:\n                return False, "source_sha256_changed"\n        return True, ""\n''',
    )
    replace_once(
        "src/tracecite/runtime/investigation.py",
        '''        valid, reason = cls._source_refs_valid(sources)\n        if not valid:\n            return False, reason\n        evidence_sources = entry.get("evidence_sources") or []\n''',
        '''        digest_cache: Dict[str, str] = {}\n        valid, reason = cls._source_refs_valid(\n            sources, digest_cache=digest_cache\n        )\n        if not valid:\n            return False, reason\n        evidence_sources = entry.get("evidence_sources") or []\n''',
    )
    replace_once(
        "src/tracecite/runtime/investigation.py",
        '''            valid, reason = cls._source_refs_valid([item])\n''',
        '''            valid, reason = cls._source_refs_valid(\n                [item], digest_cache=digest_cache\n            )\n''',
    )
    replace_once(
        "src/tracecite/runtime/investigation.py",
        '''        evidence_sources: List[Dict[str, Any]] = []\n        for item in safe_result.get("evidence") or []:\n            if not isinstance(item, Mapping):\n                continue\n            path_text = str(item.get("source_path") or "").strip()\n            digest = str(item.get("sha256") or "").strip()\n            if not path_text or not digest:\n                raise InvestigationError("缓存 Evidence 缺少可验证 source_path/sha256")\n            path = Path(path_text).expanduser()\n            if not path.is_file():\n                raise InvestigationError(f"缓存 Evidence 来源不存在: {path}")\n            try:\n                actual = _path_sha256(path)\n            except OSError as exc:\n                raise InvestigationError(f"缓存 Evidence 来源不可读: {path}") from exc\n            if actual != digest:\n                raise InvestigationError(f"缓存 Evidence 来源摘要不匹配: {path}")\n            evidence_sources.append({"path": str(path), "sha256": digest})\n''',
        '''        evidence_sources: List[Dict[str, Any]] = []\n        evidence_source_keys: set[tuple[str, str]] = set()\n        verified_evidence_paths: Dict[str, str] = {}\n        for item in safe_result.get("evidence") or []:\n            if not isinstance(item, Mapping):\n                continue\n            path_text = str(item.get("source_path") or "").strip()\n            digest = str(item.get("sha256") or "").strip()\n            if not path_text or not digest:\n                raise InvestigationError("缓存 Evidence 缺少可验证 source_path/sha256")\n            path = Path(path_text).expanduser()\n            if not path.is_file():\n                raise InvestigationError(f"缓存 Evidence 来源不存在: {path}")\n            resolved_path = str(path.resolve())\n            try:\n                actual = verified_evidence_paths.get(resolved_path)\n                if actual is None:\n                    actual = _path_sha256(path)\n                    verified_evidence_paths[resolved_path] = actual\n            except OSError as exc:\n                raise InvestigationError(f"缓存 Evidence 来源不可读: {path}") from exc\n            if actual != digest:\n                raise InvestigationError(f"缓存 Evidence 来源摘要不匹配: {path}")\n            identity = (resolved_path, digest)\n            if identity not in evidence_source_keys:\n                evidence_source_keys.add(identity)\n                evidence_sources.append({"path": resolved_path, "sha256": digest})\n''',
    )

    # Remove planner-shaped next-query production. Keep only evidence facts and
    # explicit uncertainty/correlation constraints.
    replace_once(
        "src/tracecite/runtime/evidence_fidelity.py",
        '''        "recommended_action": {\n            "operation": "search",\n            "query": identifier,\n            "purpose": "verify_identifier_uniqueness_across_scopes",\n        },\n''',
        "",
    )
    replace_once(
        "src/tracecite/runtime/evidence_fidelity.py",
        '''def _append_next_query(result: dict[str, Any], query: str) -> None:\n    value = str(query or "").strip()\n    if not value:\n        return\n    rows = [str(item) for item in result.get("next_queries") or [] if str(item).strip()]\n    if value not in rows:\n        rows.append(value)\n    result["next_queries"] = rows\n\n\n''',
        "",
    )
    fidelity = ROOT / "src/tracecite/runtime/evidence_fidelity.py"
    text = fidelity.read_text(encoding="utf-8")
    text = text.replace(
        '''                    _append_next_query(result, str(item.get("identifier_value") or ""))\n''',
        "",
    )
    text = text.replace(
        '''                _append_next_query(result, identifier)\n''',
        "",
    )
    fidelity.write_text(text, encoding="utf-8")

    replace_once(
        "src/tracecite/runtime/retrieve_contract.py",
        '''            "recommended_action": {\n                "operation": "search",\n                "query": identifier_value,\n                "purpose": "verify_identifier_uniqueness_across_scopes",\n            },\n''',
        "",
    )
    replace_once(
        "src/tracecite/runtime/retrieve_contract.py",
        '''    next_queries = [str(item) for item in canonical.get("next_queries") or [] if str(item).strip()]\n    if identifier_value not in next_queries:\n        next_queries.append(identifier_value)\n    canonical["next_queries"] = next_queries\n''',
        "",
    )
    replace_once(
        "src/tracecite/runtime/evidence_view.py",
        '''    canonical = copy.deepcopy(dict(result.canonical_result))\n    canonical.pop("next_queries", None)\n\n''',
        '''    canonical = copy.deepcopy(dict(result.canonical_result))\n\n''',
    )

    replace_once(
        "src/tracecite/runtime/evidence_ambiguity.py",
        '''                "recommended_search": value,\n                "recommended_action": {\n                    "operation": "search",\n                    "query": value,\n                    "purpose": "verify_identifier_uniqueness_across_scopes",\n                },\n''',
        "",
    )
    replace_once(
        "src/tracecite/runtime/evidence_ambiguity.py",
        '''                "navigation_query": f"{scope}/{family}-",\n''',
        "",
    )

    # Regression tests for costs and planner leakage.
    test_path = ROOT / "tests/test_search_cost_regressions.py"
    test_path.write_text(
        '''from __future__ import annotations\n\nimport hashlib\nfrom pathlib import Path\n\nfrom tracecite.runtime import EvidenceRequest, InvestigationStore, QueryTarget, RangeTarget\nfrom tracecite.runtime import agent_api as agent_api_module\nfrom tracecite.runtime import investigation as investigation_module\nfrom tracecite.runtime import session_retrieval as session_retrieval_module\nfrom tracecite.runtime import tools\nfrom tracecite.runtime.evidence_fidelity import enrich_search_leaf_context\nfrom tracecite.runtime.investigation import InvestigationCacheStore\nfrom tracecite.runtime.retrieval_session import RetrievalSessionStore\nfrom tracecite.runtime.session_retrieval import retrieve_with_session\n\n\ndef test_stateless_no_snapshot_search_hashes_evidence_source_once(tmp_path: Path, monkeypatch) -> None:\n    source = tmp_path / "runtime.log"\n    source.write_text("INFO boot\\nERROR needle request=7\\nINFO done\\n", encoding="utf-8")\n    original = tools._sha256\n    calls = 0\n\n    def counted(path: Path) -> str:\n        nonlocal calls\n        calls += 1\n        return original(path)\n\n    monkeypatch.setattr(tools, "_sha256", counted)\n    result = tools.search(\n        source, "needle", snapshot=False, segmenter="rawtext", cache=False\n    )\n\n    assert result["status"] == "ok"\n    assert calls == 1\n\n\ndef test_cache_hashes_unique_evidence_source_once_per_put_and_lookup(tmp_path: Path, monkeypatch) -> None:\n    original_source = tmp_path / "source.log"\n    evidence_source = tmp_path / "snapshot.log"\n    body = "needle\\n"\n    original_source.write_text(body, encoding="utf-8")\n    evidence_source.write_text(body, encoding="utf-8")\n    original_digest = hashlib.sha256(original_source.read_bytes()).hexdigest()\n    evidence_digest = hashlib.sha256(evidence_source.read_bytes()).hexdigest()\n    store = InvestigationCacheStore(tmp_path / "cache.json")\n    result = {\n        "operation": "search",\n        "status": "ok",\n        "evidence": [\n            {\n                "uri": f"evidence://sha256/{evidence_digest}#L1",\n                "source_path": str(evidence_source),\n                "sha256": evidence_digest,\n                "start_line": 1,\n                "end_line": 1,\n            }\n            for _ in range(20)\n        ],\n        "artifacts": [],\n        "coverage": {},\n        "data": {},\n    }\n    original_hash = investigation_module._path_sha256\n    calls: list[str] = []\n\n    def counted(path: Path) -> str:\n        calls.append(str(Path(path).resolve()))\n        return original_hash(path)\n\n    monkeypatch.setattr(investigation_module, "_path_sha256", counted)\n    refs = [{"path": str(original_source), "sha256": original_digest}]\n    store.put(\n        "k", operation="search", result=result, source_refs=refs,\n        parameters={"query": "needle"}, segmenter="rawtext", snapshot=True,\n    )\n    assert calls == [str(evidence_source.resolve())]\n\n    calls.clear()\n    cached, meta = store.lookup(\n        "k", source_refs=refs, operation="search",\n        parameters={"query": "needle"}, segmenter="rawtext", snapshot=True,\n    )\n    assert cached is not None\n    assert meta["status"] == "hit"\n    assert calls.count(str(original_source.resolve())) == 1\n    assert calls.count(str(evidence_source.resolve())) == 1\n    assert len(calls) == 2\n\n\ndef test_novel_expected_range_does_not_pre_hash_in_agent_api(tmp_path: Path, monkeypatch) -> None:\n    source = tmp_path / "runtime.log"\n    source.write_text("one\\ntwo\\nthree\\n", encoding="utf-8")\n    digest = hashlib.sha256(source.read_bytes()).hexdigest()\n    state_path = tmp_path / "investigation.json"\n    InvestigationStore(state_path).create("test range cost")\n    calls = 0\n    original = agent_api_module._sha256\n\n    def counted(path: Path) -> str:\n        nonlocal calls\n        calls += 1\n        return original(path)\n\n    monkeypatch.setattr(agent_api_module, "_sha256", counted)\n    result = agent_api_module.retrieve(\n        EvidenceRequest(\n            RangeTarget(source, 2, before=0, after=0, expected_sha256=digest),\n            investigation_path=state_path,\n        )\n    )\n    assert result.status == "ok"\n    assert calls == 0\n\n\ndef test_novel_expected_range_does_not_pre_hash_in_standalone_session(tmp_path: Path, monkeypatch) -> None:\n    source = tmp_path / "runtime.log"\n    source.write_text("one\\ntwo\\nthree\\n", encoding="utf-8")\n    digest = hashlib.sha256(source.read_bytes()).hexdigest()\n    session = RetrievalSessionStore(\n        tmp_path, "cost", namespace="_retrieval_sessions", legacy_evidence_context=False\n    )\n    calls = 0\n    original = session_retrieval_module._sha256\n\n    def counted(path: Path) -> str:\n        nonlocal calls\n        calls += 1\n        return original(path)\n\n    monkeypatch.setattr(session_retrieval_module, "_sha256", counted)\n    result = retrieve_with_session(\n        EvidenceRequest(\n            RangeTarget(source, 2, before=0, after=0, expected_sha256=digest)\n        ),\n        session,\n    )\n    assert result.status == "ok"\n    assert calls == 0\n\n\ndef test_integrity_enrichment_emits_gap_facts_without_next_query_planning(tmp_path: Path) -> None:\n    source = tmp_path / "evidence.log"\n    source.write_text(\n        "name: resource.example/widget-1001\\n"\n        "resources:\\n"\n        "- health: Healthy\\n"\n        "localID: local-device\\n"\n        "name: resource.example/widget-1001\\n"\n        "- health: Unhealthy\\n"\n        "localID: local-device\\n"\n        "resource.example/widget-1002 ready\\n"\n        "resource.example/widget-1003 ready\\n",\n        encoding="utf-8",\n    )\n    digest = hashlib.sha256(source.read_bytes()).hexdigest()\n    payload = {\n        "operation": "search",\n        "status": "ok",\n        "outcome": "not_assessed",\n        "coverage": {"evidence_returned": 1},\n        "data": {"query": "Unhealthy"},\n        "evidence": [{\n            "uri": f"evidence://sha256/{digest}#L6",\n            "source_path": str(source),\n            "sha256": digest,\n            "start_line": 6,\n            "end_line": 6,\n            "label": "- health: Unhealthy",\n        }],\n    }\n    result = enrich_search_leaf_context(payload)\n    assert "next_queries" not in result\n    for gap in result.get("missing_evidence") or []:\n        assert "recommended_action" not in gap\n    integrity = result.get("data", {}).get("evidence_integrity", {})\n    for scoped in integrity.get("scoped_identity") or []:\n        for hint in scoped.get("scoped_identity_hints") or []:\n            assert "recommended_search" not in hint\n            assert "recommended_action" not in hint\n            assert "navigation_query" not in hint\n''',
        encoding="utf-8",
    )

    # The source tree should no longer produce or strip next_queries internally.
    runtime_root = ROOT / "src/tracecite/runtime"
    offenders = []
    for path in runtime_root.rglob("*.py"):
        if "next_queries" in path.read_text(encoding="utf-8"):
            offenders.append(str(path.relative_to(ROOT)))
    if offenders:
        raise RuntimeError(f"runtime next_queries references remain: {offenders}")


if __name__ == "__main__":
    main()
