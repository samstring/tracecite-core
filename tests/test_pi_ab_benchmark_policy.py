from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT / "benchmarks" / "agent-investigation" / "moderate-suite.json"
WORKFLOW = ROOT / ".github" / "workflows" / "pi-agent-moderate-suite.yml"
RETIRED_WORKFLOWS = (
    "evidence-root-cause-30-free-shell-rg.yml",
    "evidence-runnable-16-full-investigation.yml",
    "evidence-runnable-16-paired-retry.yml",
    "evidence-runnable-16-paired.yml",
)
RETIRED_RUNNERS = (
    "run_paired_bounded_retry.py",
    "run_paired_retry.py",
)


def test_official_agent_comparison_is_pi_ab_only() -> None:
    suite = json.loads(SUITE.read_text(encoding="utf-8"))
    policy = suite["policy"]

    assert policy["official_comparison_harness"] == "pi_ab"
    assert policy["native_baseline"] == "pi-native"
    assert policy["tracecite_arm"] == "pi-tracecite"
    assert policy["free_shell_allowed"] is False
    assert policy["actual_tracecite_use_required"] is True


def test_pi_ab_keeps_the_agent_harness_symmetric() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "Run Pi without TraceCite" in workflow
    assert "Run Pi with actual TraceCite use" in workflow
    assert "--tools read,bash,grep,find,ls" in workflow
    assert "--tools read,bash,grep,find,ls,tracecite_search,tracecite_expand" in workflow
    assert "--no-extensions" in workflow
    assert "pi_tracecite_extension.ts" in workflow
    assert "tracecite_actual_use_valid" in workflow


def test_retired_free_shell_ab_entrypoints_do_not_return() -> None:
    workflows = ROOT / ".github" / "workflows"
    benchmark_dir = ROOT / "benchmarks" / "agent-investigation"

    for name in RETIRED_WORKFLOWS:
        assert not (workflows / name).exists(), name
    for name in RETIRED_RUNNERS:
        assert not (benchmark_dir / name).exists(), name
