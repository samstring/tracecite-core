from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from tracecite import (
    BudgetExhausted,
    BudgetPolicy,
    InvestigationCacheStore,
    InvestigationError,
    InvestigationStore,
)
from tracecite.runtime import investigation as investigation_module
from tracecite.runtime import tools
from tracecite.runtime.tools import expand, probe, sample, search, survey, verify


def _state(tmp_path: Path, policy: BudgetPolicy | None = None) -> tuple[Path, InvestigationStore]:
    state_path = tmp_path / "investigation.json"
    store = InvestigationStore(state_path)
    store.create("question", budget_policy=policy or BudgetPolicy())
    return state_path, store


def test_budget_policy_is_strict_and_optional(tmp_path: Path) -> None:
    path, store = _state(
        tmp_path,
        BudgetPolicy(
            max_executions=2,
            max_searches=1,
            max_queries=1,
            max_recorded_evidence_pointers=3,
            max_expand_requested_chars=100,
            max_expand_returned_chars=80,
            max_elapsed_seconds=10,
        ),
    )
    status = store.budget_status()
    assert status["policy"]["max_executions"] == 2
    assert status["usage"]["executions"] == 0
    assert status["remaining"]["executions"] == 2
    assert json.loads(path.read_text(encoding="utf-8"))["budget_policy"]["schema_version"] == 1
    with pytest.raises(Exception):
        BudgetPolicy(max_executions=0)
    with pytest.raises(Exception):
        BudgetPolicy.from_mapping({"max_executions": 1, "unexpected": 2})


def test_budget_refusal_stops_without_recording_execution(tmp_path: Path) -> None:
    path, store = _state(tmp_path, BudgetPolicy(max_executions=1))
    reservation = store.reserve_budget("probe")
    reservation.finalize({"executions": 1})
    with pytest.raises(BudgetExhausted) as caught:
        store.reserve_budget("probe")
    assert caught.value.details["violations"][0]["limit"] == "max_executions"
    loaded = store.load()
    assert loaded.status == "completed"
    assert loaded.stop_reason["kind"] == "budget_exhausted"
    assert loaded.executions == []
    assert "probe 被调查预算拒绝" in loaded.stop_reason["detail"]


def test_budget_reservations_are_concurrency_safe(tmp_path: Path) -> None:
    _path, store = _state(tmp_path, BudgetPolicy(max_executions=1))
    results: list[str] = []
    reservations = []
    lock = threading.Lock()

    def reserve() -> None:
        try:
            item = store.reserve_budget("probe")
            with lock:
                reservations.append(item)
                results.append("reserved")
        except BudgetExhausted:
            with lock:
                results.append("refused")

    threads = [threading.Thread(target=reserve) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(results) == ["refused", "reserved"]
    reservations[0].finalize({"executions": 1})
    assert store.load().executions == []
    assert store.budget_status()["usage"]["executions"] == 1


def test_probe_cache_hit_records_fresh_execution_and_no_raw_body(tmp_path: Path) -> None:
    source = tmp_path / "source.log"
    source.write_text("SECRET-LINE\nsecond\n", encoding="utf-8")
    state_path, store = _state(tmp_path, BudgetPolicy(max_executions=3))
    first = probe(source, investigation_path=state_path)
    second = probe(source, investigation_path=state_path)
    assert first["data"]["cache"]["status"] == "miss"
    assert second["data"]["cache"]["status"] == "hit"
    assert len(store.load().executions) == 2
    cache_text = (tmp_path / "investigation.json.cache.json").read_text(encoding="utf-8")
    assert "SECRET-LINE" not in cache_text


def test_search_cache_stale_source_is_a_miss_and_recomputes(tmp_path: Path) -> None:
    source = tmp_path / "source.log"
    source.write_text("CACHE-TARGET\n", encoding="utf-8")
    state_path, store = _state(tmp_path, BudgetPolicy(max_executions=3, max_searches=3))
    first = search(source, "CACHE-TARGET", investigation_path=state_path)
    assert first["data"]["cache"]["status"] == "miss"
    source.write_text("CACHE-TARGET\nchanged\n", encoding="utf-8")
    second = search(source, "CACHE-TARGET", investigation_path=state_path)
    assert second["data"]["cache"]["status"] == "miss"
    assert second["data"]["cache"]["reason"] == "source_sha256_changed"
    assert len(store.load().executions) == 2


def test_search_does_not_cache_a_snapshot_from_a_different_source_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.log"
    source.write_text("old only\n", encoding="utf-8")
    state_path, _store = _state(
        tmp_path,
        BudgetPolicy(max_executions=3, max_searches=3, max_queries=3),
    )
    original_filter = tools.filter_text
    changed = False

    def mutate_before_snapshot(input_path, *args, **kwargs):
        nonlocal changed
        if not changed:
            Path(input_path).write_text("new TARGET\n", encoding="utf-8")
            changed = True
        return original_filter(input_path, *args, **kwargs)

    monkeypatch.setattr(tools, "filter_text", mutate_before_snapshot)
    first = search(source, "TARGET", investigation_path=state_path)
    assert first["status"] == "ok"
    assert first["data"]["cache"]["status"] == "bypass"
    assert first["data"]["cache"]["reason"] == "source_changed_during_snapshot"

    monkeypatch.setattr(tools, "filter_text", original_filter)
    source.write_text("old only\n", encoding="utf-8")
    second = search(source, "TARGET", investigation_path=state_path)

    assert second["status"] == "no_match"
    assert second["data"]["cache"]["status"] == "miss"


def test_search_pointer_budget_refuses_before_scan_when_cap_is_below_result_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.log"
    source.write_text("target\ntarget\ntarget\n", encoding="utf-8")
    state_path, store = _state(
        tmp_path,
        BudgetPolicy(
            max_executions=2,
            max_searches=2,
            max_queries=2,
            max_recorded_evidence_pointers=1,
        ),
    )
    called = {"scan": False}

    def should_not_scan(*_args, **_kwargs):
        called["scan"] = True
        raise AssertionError("search must reserve its bounded pointer capacity first")

    monkeypatch.setattr(tools, "filter_text", should_not_scan)
    refused = search(source, "target", investigation_path=state_path)
    assert refused["status"] == "error"
    assert refused["error"]["type"] == "BudgetExhausted"
    assert called["scan"] is False
    assert store.load().executions == []
    assert store.load().stop_reason["kind"] == "budget_exhausted"


def test_non_snapshot_raw_tools_do_not_reserve_immutable_pointer_budget(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.log"
    source.write_text("context\n", encoding="utf-8")
    state_path, store = _state(
        tmp_path,
        BudgetPolicy(max_executions=3, max_recorded_evidence_pointers=1),
    )
    result = sample(
        source,
        snapshot=False,
        count=20,
        investigation_path=state_path,
    )
    assert result["status"] == "ok"
    assert result["coverage"]["evidence_withheld"] is True
    assert store.budget_status()["usage"]["recorded_evidence_pointers"] == 0


@pytest.mark.parametrize(
    ("operation", "kwargs", "reason"),
    [
        ("search", {"snapshot": False}, "no_snapshot"),
        ("survey", {}, "raw_payload"),
        ("sample", {}, "raw_payload"),
        ("expand", {"start_line": 1}, "raw_payload"),
    ],
)
def test_unsafe_or_raw_operations_are_explicitly_bypassed(
    tmp_path: Path, operation: str, kwargs: dict, reason: str
) -> None:
    source = tmp_path / "source.log"
    source.write_text("target\n", encoding="utf-8")
    state_path, _store = _state(tmp_path, BudgetPolicy(max_executions=5))
    if operation == "search":
        result = search(source, "target", investigation_path=state_path, **kwargs)
    elif operation == "survey":
        result = survey(source, investigation_path=state_path, **kwargs)
    elif operation == "sample":
        result = sample(source, investigation_path=state_path, **kwargs)
    else:
        result = expand(source, investigation_path=state_path, **kwargs)
    assert result["data"]["cache"]["status"] == "bypass"
    assert result["data"]["cache"]["reason"] == reason


def test_cache_output_side_effect_is_bypassed(tmp_path: Path) -> None:
    source = tmp_path / "source.log"
    source.write_text("target\n", encoding="utf-8")
    output = tmp_path / "explicit.out"
    state_path, _store = _state(tmp_path, BudgetPolicy(max_executions=2))
    result = search(source, "target", output_path=output, investigation_path=state_path)
    assert result["data"]["cache"]["status"] == "bypass"
    assert result["data"]["cache"]["reason"] == "output_side_effect"


def test_verify_and_run_consume_execution_budget_before_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_path, store = _state(tmp_path, BudgetPolicy(max_executions=1))
    monkeypatch.setattr(
        tools,
        "verify_manifest",
        lambda _path: {"run_id": "r1", "verdict": "ok", "checked_files": 1},
    )
    first = verify(tmp_path / "manifest.json", investigation_path=state_path)
    assert first["status"] == "ok"
    assert store.budget_status()["usage"]["executions"] == 1
    called = {"run": False}

    def should_not_run(*_args, **_kwargs):
        called["run"] = True
        raise AssertionError("scenario must be refused before execution")

    monkeypatch.setattr(tools, "run_scenario", should_not_run)
    refused = tools.run({"version": 1}, investigation_path=state_path)
    assert refused["status"] == "error"
    assert refused["error"]["type"] == "BudgetExhausted"
    assert called["run"] is False


def test_run_reserves_worst_case_evidence_cap_before_extension(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_path, store = _state(
        tmp_path,
        BudgetPolicy(max_executions=2, max_recorded_evidence_pointers=1),
    )
    called = {"run": False}

    def should_not_run(*_args, **_kwargs):
        called["run"] = True
        raise AssertionError("scenario extension must be refused before execution")

    monkeypatch.setattr(tools, "run_scenario", should_not_run)
    refused = tools.run({"version": 1}, investigation_path=state_path)
    assert refused["status"] == "error"
    assert refused["error"]["type"] == "BudgetExhausted"
    assert called["run"] is False
    assert store.load().executions == []
    assert store.load().stop_reason["kind"] == "budget_exhausted"


def test_elapsed_limit_at_boundary_refuses_next_execution(tmp_path: Path) -> None:
    _path, store = _state(tmp_path, BudgetPolicy(max_executions=3, max_elapsed_seconds=1))
    reservation = store.reserve_budget("probe")
    reservation.finalize({"executions": 1}, elapsed_seconds=1.0)
    with pytest.raises(BudgetExhausted):
        store.reserve_budget("probe")


def test_cache_rejects_oversized_entry_and_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source.log"
    source.write_text("source\n", encoding="utf-8")
    source_ref = {"path": str(source), "sha256": tools._sha256(source)}
    cache = InvestigationCacheStore(tmp_path / "cache.json")
    key = cache.make_key(
        "probe",
        {"input": str(source)},
        source_refs=[source_ref],
        segmenter="plain",
        snapshot=None,
    )
    with pytest.raises(InvestigationError, match="缓存条目超过大小限制"):
        cache.put(
            key,
            operation="probe",
            result={"status": "ok", "data": {"oversized": "x" * investigation_module.MAX_CACHE_ENTRY_BYTES}},
            source_refs=[source_ref],
            parameters={"input": str(source)},
            segmenter="plain",
            snapshot=None,
        )
    assert not cache.path.exists()

    monkeypatch.setattr(investigation_module, "MAX_CACHE_STORE_BYTES", 256)
    raw = cache._empty()
    raw["entries"] = [{"key": "large", "payload": "x" * 512}]
    with pytest.raises(InvestigationError, match="缓存文件超过大小限制"):
        cache._save(raw)
    assert not cache.path.exists()


def test_cache_drops_entries_with_stale_evidence_or_artifact(tmp_path: Path) -> None:
    source = tmp_path / "source.log"
    evidence_source = tmp_path / "evidence.log"
    artifact = tmp_path / "artifact.json"
    source.write_text("source\n", encoding="utf-8")
    evidence_source.write_text("evidence\n", encoding="utf-8")
    artifact.write_text("artifact\n", encoding="utf-8")
    source_ref = {"path": str(source), "sha256": tools._sha256(source)}
    evidence_ref = {"path": str(evidence_source), "sha256": tools._sha256(evidence_source)}
    artifact_ref = {"path": str(artifact), "sha256": tools._sha256(artifact)}
    cache = InvestigationCacheStore(tmp_path / "cache.json")

    def add_entry(name: str, *, include_evidence: bool = True) -> str:
        params = {"input": str(source), "name": name}
        key = cache.make_key(
            "probe",
            params,
            source_refs=[source_ref],
            segmenter="plain",
            snapshot=None,
        )
        cache.put(
            key,
            operation="probe",
            result={
                "status": "ok",
                "evidence": (
                    [
                        {
                            "uri": "evidence://sha256/" + "a" * 64 + "#L1",
                            "source_path": str(evidence_source),
                            "sha256": evidence_ref["sha256"],
                        }
                    ]
                    if include_evidence
                    else []
                ),
                "artifacts": [{"path": str(artifact), "sha256": artifact_ref["sha256"]}],
                "data": {},
            },
            source_refs=[source_ref],
            parameters=params,
            segmenter="plain",
            snapshot=None,
        )
        return key

    evidence_key = add_entry("evidence")
    artifact_key = add_entry("artifact", include_evidence=False)
    evidence_source.write_text("tampered\n", encoding="utf-8")
    cached, metadata = cache.lookup(
        evidence_key,
        source_refs=[source_ref],
        operation="probe",
        parameters={"input": str(source), "name": "evidence"},
        segmenter="plain",
        snapshot=None,
    )
    assert cached is None
    assert metadata["status"] == "miss"
    assert metadata["reason"] == "evidence_source_sha256_changed"

    artifact.unlink()
    cached, metadata = cache.lookup(
        artifact_key,
        source_refs=[source_ref],
        operation="probe",
        parameters={"input": str(source), "name": "artifact"},
        segmenter="plain",
        snapshot=None,
    )
    assert cached is None
    assert metadata["status"] == "miss"
    assert metadata["reason"] == "artifact_missing"


def test_concurrent_cache_puts_preserve_entries_and_revision(tmp_path: Path) -> None:
    source = tmp_path / "source.log"
    source.write_text("source\n", encoding="utf-8")
    source_ref = {"path": str(source), "sha256": tools._sha256(source)}
    cache = InvestigationCacheStore(tmp_path / "cache.json")
    barrier = threading.Barrier(8)
    errors: list[BaseException] = []

    def put_one(index: int) -> None:
        try:
            barrier.wait()
            params = {"input": str(source), "index": index}
            key = cache.make_key(
                "probe",
                params,
                source_refs=[source_ref],
                segmenter="plain",
                snapshot=None,
            )
            cache.put(
                key,
                operation="probe",
                result={"status": "ok", "data": {"index": index}},
                source_refs=[source_ref],
                parameters=params,
                segmenter="plain",
                snapshot=None,
            )
        except BaseException as exc:  # report thread failures in the main assertion
            errors.append(exc)

    threads = [threading.Thread(target=put_one, args=(index,)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    persisted = json.loads(cache.path.read_text(encoding="utf-8"))
    assert len(persisted["entries"]) == 8
    assert persisted["revision"] == 8
