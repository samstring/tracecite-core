from __future__ import annotations

import json
from pathlib import Path

import pytest

from tracecite import (
    BudgetPolicy,
    InvestigationStore,
    compare_investigations as public_compare_investigations,
    timeline_investigation as public_timeline_investigation,
)
from tracecite.integrations import cli
from tracecite.runtime.investigation_compare import (
    COMPARE_SCHEMA_VERSION,
    TIMELINE_SCHEMA_VERSION,
    InvestigationCompareError,
    compare_investigations,
    timeline_investigation,
)


def _state(tmp_path: Path, name: str = "investigation.json") -> tuple[Path, InvestigationStore]:
    path = tmp_path / name
    store = InvestigationStore(path)
    store.create(
        "private user claim should never appear",
        created_by="caller",
        budget_policy=BudgetPolicy(max_executions=5),
    )
    store.add_hypothesis("private hypothesis claim", hypothesis_id="H1")
    store.add_test(
        "H1",
        "private test intent",
        expected_observation="private expected",
        contradicting_observation="private contradiction",
        test_id="T1",
    )
    store.record_execution(
        "private-operation",
        {
            "status": "ok",
            "outcome": "supported",
            "data": {"SECRET-BODY": "must not leak"},
            "evidence": [
                {
                    "uri": "evidence://sha256/" + "a" * 64 + "#L1",
                    "source_path": "/private/source.log",
                    "sha256": "a" * 64,
                    "start_line": 1,
                }
            ],
            "coverage": {"records": 1},
        },
        hypothesis_id="H1",
        test_id="T1",
        parameters={"SECRET-PARAM": "must not leak"},
    )
    return path, store


def test_timeline_identical_and_no_raw_claim_or_evidence_leak(tmp_path: Path) -> None:
    path, store = _state(tmp_path)
    first = timeline_investigation(path)
    second = timeline_investigation(path)
    assert first == second
    assert first["schema_version"] == TIMELINE_SCHEMA_VERSION
    assert first["status"] == "ok"
    assert first["valid"] is True
    assert first["revision"] == store.load().revision
    assert all("revision" not in event for event in first["events"])
    encoded = json.dumps(first, ensure_ascii=False)
    for secret in (
        "private user claim",
        "private hypothesis claim",
        "private-operation",
        "SECRET-BODY",
        "SECRET-PARAM",
        "evidence://",
        "/private/source.log",
    ):
        assert secret not in encoded
    kinds = [event["kind"] for event in first["events"]]
    assert kinds[:4] == ["investigation_created", "hypothesis", "test", "execution"]


def test_timeline_time_ties_are_ordered_by_kind_then_id(tmp_path: Path) -> None:
    _path, store = _state(tmp_path)
    raw = store.load().to_dict()
    same = "2026-01-01T00:00:00+00:00"
    raw["created_at"] = same
    raw["hypotheses"][0]["created_at"] = same
    raw["tests"][0]["created_at"] = same
    raw["executions"][0]["recorded_at"] = same
    raw["hypotheses"].append(
        {
            "id": "H0",
            "claim": "hidden",
            "rationale": "hidden",
            "status": "open",
            "test_ids": [],
            "supporting_evidence": [],
            "contradicting_evidence": [],
            "created_at": same,
        }
    )
    # H0/H1 tie on timestamp and kind, so ID order is stable.
    result = timeline_investigation(raw)
    assert [row["id"] for row in result["events"] if row["kind"] == "hypothesis"] == [
        "H0",
        "H1",
    ]


def test_timeline_caps_events_and_reports_omissions(tmp_path: Path) -> None:
    _path, store = _state(tmp_path)
    raw = store.load().to_dict()
    for index in range(20):
        raw["hypotheses"].append(
            {
                "id": f"H{index + 2}",
                "claim": "hidden",
                "rationale": "",
                "status": "open",
                "test_ids": [],
                "supporting_evidence": [],
                "contradicting_evidence": [],
                "created_at": f"2026-01-01T00:00:{index:02d}+00:00",
            }
        )
    result = timeline_investigation(raw, max_events=4)
    assert len(result["events"]) == 4
    assert result["counts"]["total"] > 4
    assert result["counts"]["omitted"] == result["omitted"]["events"]
    assert result["truncated"] is True


def test_compare_identical_and_changed_revision_structurally(tmp_path: Path) -> None:
    path, store = _state(tmp_path)
    same = compare_investigations(store, path)
    assert same["schema_version"] == COMPARE_SCHEMA_VERSION
    assert same["status"] == "ok"
    assert same["valid"] is True
    assert same["revision_delta"] == 0
    assert same["status_changed"] is False
    assert same["outcome_transitions"] == []
    assert all(item["delta"] == 0 for item in same["counts"].values())

    left = store.load().to_dict()
    right = store.load().to_dict()
    right["revision"] = left["revision"] + 3
    right["status"] = "completed"
    right["stop_reason"] = {
        "kind": "resolved",
        "detail": "private stop detail",
        "stopped_at": "2026-01-01T00:00:00+00:00",
    }
    right["hypotheses"][0]["status"] = "supported"
    right["findings"] = [
        {
            "id": "F1",
            "hypothesis_id": "H1",
            "outcome": "supported",
            "summary": "private finding claim",
            "supporting_evidence": ["evidence://sha256/" + "b" * 64 + "#L1"],
            "contradicting_evidence": [],
            "coverage": {"records": 2},
            "limitations": [],
            "created_at": "2026-01-01T00:00:00+00:00",
        }
    ]
    changed = compare_investigations(left, right)
    assert changed["revision_delta"] == 3
    assert changed["status_changed"] is True
    assert changed["outcome_transitions"] == [
        {"kind": "hypothesis", "id": "H1", "from": "open", "to": "supported"}
    ]
    assert changed["ids"]["findings"]["added"] == ["F1"]
    assert changed["stop"]["changed"] is True
    encoded = json.dumps(changed, ensure_ascii=False)
    for secret in ("private finding claim", "private stop detail", "evidence://"):
        assert secret not in encoded


def test_compare_reports_coverage_omission_truncation_and_budget_deltas(tmp_path: Path) -> None:
    _path, store = _state(tmp_path)
    left = store.load().to_dict()
    right = store.load().to_dict()
    right["budget_usage"]["executions"] = 2
    right["executions"][0]["coverage"] = {"records": 2, "lines": 4}
    right["executions"][0]["recording"]["evidence_truncated"] = True
    right["executions"][0]["recording"]["custom_omitted"] = True
    right["findings"] = [
        {
            "id": "F1",
            "hypothesis_id": "H1",
            "outcome": "unknown",
            "summary": "hidden",
            "supporting_evidence": [],
            "contradicting_evidence": [],
            "coverage": {},
            "limitations": ["hidden limitation"],
            "created_at": "2026-01-01T00:00:00+00:00",
        }
    ]
    result = compare_investigations(left, right)
    assert result["budget"]["usage"]["executions"]["delta"] == 2
    assert result["coverage"]["delta"]["declared_fields"]["delta"] == 1
    assert result["coverage"]["delta"]["omitted"]["delta"] == 1
    assert result["coverage"]["delta"]["truncated"]["delta"] == 1
    assert result["limitations"]["delta"]["items"]["delta"] == 1
    assert result["omissions"]["omitted"]["delta"] == 1
    assert result["truncations"]["truncated"]["delta"] == 1


@pytest.mark.parametrize("operation", [timeline_investigation, compare_investigations])
def test_invalid_corrupt_and_oversized_inputs_are_bounded_errors(
    tmp_path: Path, operation
) -> None:
    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("not-json", encoding="utf-8")
    if operation is timeline_investigation:
        result = operation(corrupt)
    else:
        result = operation(corrupt, corrupt)
    assert result["status"] == "error"
    assert result["valid"] is False
    assert result["error"]["code"] in {"source_invalid", "source_unreadable"}

    oversized = tmp_path / "oversized.json"
    oversized.write_text("x" * 5_000, encoding="utf-8")
    if operation is timeline_investigation:
        result = operation(oversized, max_source_bytes=4_096)
    else:
        result = operation(oversized, oversized, max_source_bytes=4_096)
    assert result["status"] == "error"
    assert result["error"]["code"] == "source_too_large"


def test_output_char_cap_and_strict_error(tmp_path: Path) -> None:
    _path, store = _state(tmp_path)
    result = timeline_investigation(store, max_output_chars=512)
    assert len(json.dumps(result, ensure_ascii=False, separators=(",", ":"))) <= 512
    compared = compare_investigations(store, store, max_output_chars=512)
    assert len(json.dumps(compared, ensure_ascii=False, separators=(",", ":"))) <= 512
    with pytest.raises(InvestigationCompareError, match="source_missing"):
        timeline_investigation(tmp_path / "missing.json", strict=True)


def test_public_exports_and_cli_routes_are_read_only(tmp_path: Path, capsys) -> None:
    path, store = _state(tmp_path)
    revision = store.load().revision

    assert public_timeline_investigation(path)["kind"] == "timeline"
    assert public_compare_investigations(path, path)["revision_delta"] == 0

    assert cli.main(
        [
            "investigation",
            "timeline",
            str(path),
            "--max-events",
            "4",
            "--max-chars",
            "4000",
        ]
    ) == 0
    rendered = json.loads(capsys.readouterr().out)
    assert rendered["kind"] == "timeline"
    assert rendered["valid"] is True

    assert cli.main(
        [
            "investigation",
            "compare",
            str(path),
            str(path),
            "--max-items",
            "4",
            "--max-chars",
            "12000",
        ]
    ) == 0
    rendered = json.loads(capsys.readouterr().out)
    assert rendered["kind"] == "compare"
    assert rendered["revision_delta"] == 0
    assert store.load().revision == revision
