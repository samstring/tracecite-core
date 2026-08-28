from __future__ import annotations

from pathlib import Path

from tracecite.root_cause_truth import load_truth_lock, validate_truth_lock


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_all_github_root_cause_cases_have_grounded_merged_fix_truth() -> None:
    result = validate_truth_lock(_repo_root())

    assert result["status"] == "ok"
    assert result["github_cases"] == 18
    assert result["merged_fix_truth"] == 18
    assert result["fix_alignment_grounded"] == 18
    assert len(result["projects"]) >= 8


def test_truth_lock_pins_merge_commit_not_only_mutable_pr_url() -> None:
    locked = load_truth_lock(_repo_root())["cases"]
    row = locked["kubernetes-86676"]

    assert row["fix_pr"] == 86689
    assert row["merged_at"] == "2020-01-08T10:57:41Z"
    assert row["merge_commit_sha"] == "fd0358fd211a52106fd21f036ccb0bffbc582474"
    assert "CPUManagerCheckpoint" in row["truth_text"]
