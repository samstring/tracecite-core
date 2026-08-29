from __future__ import annotations

import json
from pathlib import Path

from tracecite.runtime import assess_test
from tracecite.runtime.investigation import InvestigationStore
from tracecite.runtime.investigation_summary import (
    MAX_SUMMARY_OUTPUT_CHARS,
    SUMMARY_SCHEMA_VERSION,
    InvestigationSummaryError,
    summarize_investigation,
)
from tracecite import summarize_investigation as public_summarize_investigation
from tracecite.integrations import cli


VALID_REF = "evidence://sha256/" + ("a" * 64) + "#L1"


def _store(tmp_path: Path) -> InvestigationStore:
    store = InvestigationStore(tmp_path / "investigation.json")
    store.create("why did the request fail?", investigation_id="INV-1")
    return store


def test_empty_state_is_bounded_and_advisory(tmp_path: Path) -> None:
    store = _store(tmp_path)
    summary = summarize_investigation(store)

    assert summary["schema_version"] == SUMMARY_SCHEMA_VERSION
    assert summary["status"] == "ok"
    assert summary["valid"] is True
    assert summary["advisory"] is True
    assert summary["state_status"] == "active"
    assert summary["progress"]["hypotheses"]["total"] == 0
    assert summary["coverage_gaps"][0]["kind"] == "no_hypotheses"
    assert summary["suggested_actions"] == [{"category": "formulate_test", "refs": []}]
    assert summary["advisory_completeness"]["complete"] is False
    assert summary["advisory_completeness"]["advisory_only"] is True


def test_active_state_with_no_substantive_gaps_can_suggest_stop_or_reopen(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    store.add_hypothesis("claim", hypothesis_id="H1")
    store.add_test(
        "H1",
        "inspect",
        expected_observation="present",
        contradicting_observation="absent",
        test_id="T1",
    )
    store.record_execution(
        "search",
        {
            "status": "ok",
            "outcome": "supported",
            "evidence": [{"uri": VALID_REF}],
            "coverage": {"complete": True},
            "verification": {"integrity_checked": True},
        },
        hypothesis_id="H1",
        test_id="T1",
    )
    assess_test(
        store,
        "T1",
        "supported",
        evidence_refs=[VALID_REF],
        coverage={"complete": True},
    )
    store.add_finding(
        "H1",
        "supported",
        "recorded",
        supporting_evidence=[VALID_REF],
        coverage={"scope": "small", "complete": True},
    )
    summary = summarize_investigation(store)
    assert summary["state_status"] == "active"
    assert summary["advisory_completeness"]["reasons"] == ["investigation_active"]
    assert summary["suggested_actions"] == [
        {"category": "stop/reopen", "refs": ["INV-1"]}
    ]


def test_partial_state_lists_unresolved_and_next_steps_without_raw_text(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    store.add_hypothesis("secret hypothesis text", hypothesis_id="H1")
    store.add_hypothesis("another claim", hypothesis_id="H2")
    store.add_test(
        "H1",
        "inspect",
        expected_observation="present",
        contradicting_observation="absent",
        test_id="T1",
    )
    store.add_test(
        "H2",
        "inspect later",
        expected_observation="present",
        contradicting_observation="absent",
        test_id="T2",
    )
    store.record_execution(
        "search",
        {
            "status": "error",
            "outcome": "unknown",
            "error": {"type": "ValueError", "message": "secret raw error"},
        },
        hypothesis_id="H1",
        test_id="T1",
    )
    summary = summarize_investigation(store.path)
    encoded = json.dumps(summary, ensure_ascii=False)

    assert summary["progress"]["hypotheses"]["unresolved"] == 2
    assert summary["progress"]["tests"]["without_executions"] == 1
    assert summary["progress"]["executions"]["error"] == 1
    assert summary["progress"]["executions"]["unknown"] == 1
    assert summary["execution_gaps"][0]["flags"] == ["error", "unknown"]
    assert {item["category"] for item in summary["suggested_actions"]} >= {
        "execute_test",
        "gather_missing_evidence",
    }
    assert "secret hypothesis text" not in encoded
    assert "secret raw error" not in encoded


def test_clean_execution_exposes_contradiction_and_finding_hints(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.add_hypothesis("claim", hypothesis_id="H1")
    store.add_test(
        "H1",
        "inspect",
        expected_observation="present",
        contradicting_observation="absent",
        test_id="T1",
    )
    store.record_execution(
        "search",
        {
            "status": "ok",
            "outcome": "supported",
            "evidence": [{"uri": "evidence://sha256/abc#L1"}],
        },
        hypothesis_id="H1",
        test_id="T1",
    )
    summary = summarize_investigation(store)

    categories = [item["category"] for item in summary["suggested_actions"]]
    assert "seek_contradiction" in categories
    assert "record_finding" in categories
    assert summary["progress"]["executions"]["ok"] == 1
    assert summary["progress"]["executions"]["missing_evidence"] == 0


def test_completed_state_reports_stop_reason_and_is_not_a_funnel(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.add_hypothesis("claim", hypothesis_id="H1")
    store.add_test(
        "H1",
        "inspect",
        expected_observation="present",
        contradicting_observation="absent",
        test_id="T1",
    )
    store.add_finding("H1", "unknown", "not enough evidence")
    store.stop("finished because the requested scope ended", kind="completed")

    summary = summarize_investigation(store.path)
    assert summary["state_status"] == "completed"
    assert summary["stop"] == {
        "status": "completed",
        "kind": "completed",
        "reason": "finished because the requested scope ended",
        "present": True,
    }
    assert summary["finding_gaps"][0]["outcome"] == "unknown"
    assert summary["advisory_completeness"]["advisory_only"] is True
    assert summary["suggested_actions"][-1]["category"] == "stop/reopen"


def test_error_unknown_missing_omission_and_truncation_are_distinct(tmp_path: Path) -> None:
    store = _store(tmp_path)
    for index in range(5):
        store.add_hypothesis(f"claim {index}", hypothesis_id=f"H{index}")
        store.add_test(
            f"H{index}",
            "inspect",
            expected_observation="present",
            contradicting_observation="absent",
            test_id=f"T{index}",
        )
    store.record_execution(
        "error",
        {"status": "error", "outcome": "unknown"},
        hypothesis_id="H0",
        test_id="T0",
    )
    store.record_execution(
        "unknown",
        {"status": "ok", "outcome": "unknown"},
        hypothesis_id="H1",
        test_id="T1",
    )
    store.record_execution(
        "missing",
        {"status": "ok", "outcome": "supported", "missing_evidence": ["pointer"]},
        hypothesis_id="H2",
        test_id="T2",
    )
    store.record_execution(
        "omitted",
        {
            "status": "ok",
            "outcome": "supported",
            "evidence": [{"uri": "evidence://one", "metadata": {"raw": "x"}}],
        },
        hypothesis_id="H3",
        test_id="T3",
    )
    store.record_execution(
        "truncated",
        {
            "status": "ok",
            "outcome": "supported",
            "evidence": [{"uri": f"evidence://{index}"} for index in range(101)],
        },
        hypothesis_id="H4",
        test_id="T4",
    )
    summary = summarize_investigation(store)
    counts = summary["progress"]["executions"]
    assert counts["error"] == 1
    assert counts["unknown"] == 2
    assert counts["missing_evidence"] == 1
    assert counts["omission"] == 1
    assert counts["truncation"] == 1
    assert {
        "execution_error",
        "execution_unknown",
        "execution_missing_evidence",
        "execution_omission",
        "execution_truncation",
    } <= {item["kind"] for item in summary["coverage_gaps"]}


def test_corrupt_and_oversized_sources_return_safe_error_or_strict_failure(
    tmp_path: Path,
) -> None:
    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("not json", encoding="utf-8")
    summary = summarize_investigation(corrupt)
    assert summary["status"] == "error"
    assert summary["valid"] is False
    assert summary["error"] == {"code": "source_invalid"}

    oversized = tmp_path / "oversized.json"
    oversized.write_bytes(b"x" * 5_000)
    summary = summarize_investigation(oversized, max_source_bytes=4_096)
    assert summary["error"] == {"code": "source_too_large"}

    invalid_mapping = summarize_investigation({"schema_version": 1, "problem": {}})
    assert invalid_mapping["error"] == {"code": "source_invalid"}
    try:
        summarize_investigation(corrupt, strict=True)
    except InvestigationSummaryError as exc:
        assert str(exc) == "source_invalid"
    else:
        raise AssertionError("strict summary loading must raise")


def test_detail_and_serialized_output_bounds_are_deterministic(tmp_path: Path) -> None:
    store = _store(tmp_path)
    for index in range(8):
        store.add_hypothesis(f"claim {index}", hypothesis_id=f"H{index}")
        store.add_test(
            f"H{index}",
            "inspect",
            expected_observation="present",
            contradicting_observation="absent",
            test_id=f"T{index}",
        )

    first = summarize_investigation(store, max_items=2, max_output_chars=6_000)
    second = summarize_investigation(store, max_items=2, max_output_chars=6_000)
    assert first == second
    for key in (
        "unresolved_hypotheses",
        "untested_hypotheses",
        "untested_tests",
        "execution_gaps",
        "finding_gaps",
        "coverage_gaps",
        "suggested_actions",
    ):
        assert len(first[key]) <= 2
    assert first["omitted"]["coverage_gaps"] > 0
    assert first["truncated"] is True
    assert len(json.dumps(first, ensure_ascii=False, separators=(",", ":"))) <= 6_000
    assert MAX_SUMMARY_OUTPUT_CHARS >= 6_000


def test_small_output_is_still_valid_json_and_invalid_limits_are_explicit(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    tiny = summarize_investigation(store, max_output_chars=512)
    assert len(json.dumps(tiny, ensure_ascii=False, separators=(",", ":"))) <= 512
    assert tiny["truncated"] is True

    invalid = summarize_investigation(store, max_items=0)
    assert invalid["status"] == "error"
    assert invalid["error"] == {"code": "invalid_limit:max_items"}
    invalid = summarize_investigation(store, max_output_chars="small")
    assert invalid["error"] == {"code": "invalid_limit:max_output_chars"}


def test_public_export_and_cli_route_read_only_summary(tmp_path: Path, capsys) -> None:
    store = _store(tmp_path)
    revision = store.load().revision
    assert public_summarize_investigation(store.path)["advisory"] is True

    assert cli.main(
        [
            "investigation",
            "summary",
            str(store.path),
            "--max-items",
            "4",
            "--max-chars",
            "4000",
        ]
    ) == 0
    rendered = json.loads(capsys.readouterr().out)
    assert rendered["valid"] is True
    assert rendered["advisory"] is True
    assert store.load().revision == revision
