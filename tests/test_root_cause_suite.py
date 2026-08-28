from __future__ import annotations

import json
from pathlib import Path

from tracecite.root_cause_suite import (
    SUITE_ID,
    aggregate_results,
    suite_cases,
    validate_suite,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_suite_has_30_unique_real_cases_and_fixed_cohorts() -> None:
    cases = suite_cases()
    assert len(cases) == 30
    assert len({case["id"] for case in cases}) == 30
    assert sum(case["cohort"] == "strict" for case in cases) == 26
    assert sum(case["cohort"] == "reporter_hypothesis" for case in cases) == 4
    assert sum(case["source"]["kind"] == "existing_case" for case in cases) == 12
    assert sum(case["source"]["kind"] == "github_issue" for case in cases) == 18


def test_github_cases_pin_issue_and_fix_identity() -> None:
    github_cases = [case for case in suite_cases() if case["source"]["kind"] == "github_issue"]
    assert github_cases
    for case in github_cases:
        source = case["source"]
        assert source["repo"].count("/") == 1
        assert source["number"] > 0
        assert source["fix_pr"] > 0
        assert case["source_issue"].endswith(f"/issues/{source['number']}")
        assert case["fix_reference"].endswith(f"/pull/{source['fix_pr']}")
        assert set(case["root_cause"]) == {
            "failure_localization",
            "immediate_failure_mechanism",
            "upstream_contributor",
            "fix_alignment",
        }


def test_validate_suite_checks_existing_case_sources_without_network() -> None:
    result = validate_suite(_repo_root())
    assert result["status"] == "ok"
    assert result["suite_id"] == SUITE_ID
    assert result["cases"] == 30
    assert result["cohorts"] == {"reporter_hypothesis": 4, "strict": 26}


def test_aggregate_results_separates_strict_and_reporter_hypothesis(tmp_path: Path) -> None:
    scores = tmp_path / "scores"
    failures = tmp_path / "failures"
    scores.mkdir()
    failures.mkdir()
    (scores / "doublecmd-2264-tracecite.json").write_text(
        json.dumps(
            {
                "case_id": "doublecmd-2264",
                "mode": "tracecite",
                "passed": True,
                "quality": {"dimension_recall": 1.0, "citation": {"accuracy": 1.0}},
                "context_cost": {
                    "reported_input_tokens": 100,
                    "reported_output_tokens": 10,
                    "tool_output_chars": 400,
                    "cumulative_attempted_context_chars": 1000,
                    "peak_attempted_context_chars": 600,
                },
            }
        ),
        encoding="utf-8",
    )
    (scores / "prometheus-19432-tracecite.json").write_text(
        json.dumps(
            {
                "case_id": "prometheus-19432",
                "mode": "tracecite",
                "passed": False,
                "quality": {"dimension_recall": 0.5, "citation": {"accuracy": 0.5}},
                "context_cost": {
                    "reported_input_tokens": 200,
                    "reported_output_tokens": 20,
                    "tool_output_chars": 800,
                    "cumulative_attempted_context_chars": 2000,
                    "peak_attempted_context_chars": 900,
                },
            }
        ),
        encoding="utf-8",
    )
    (failures / "pulumi-14231-tracecite.json").write_text(
        json.dumps(
            {
                "case_id": "pulumi-14231",
                "mode": "tracecite",
                "reason": "provider_rate_limited",
            }
        ),
        encoding="utf-8",
    )

    result = aggregate_results(tmp_path, mode="tracecite")
    assert result["scores"] == 2
    assert result["score_passed"] == 1
    assert result["failure_reasons"] == {"provider_rate_limited": 1}
    assert result["cohorts"]["strict"]["scored"] == 1
    assert result["cohorts"]["reporter_hypothesis"]["scored"] == 1
    assert result["reported_input_tokens"] == 300
    assert result["peak_attempted_context_chars"] == 900
