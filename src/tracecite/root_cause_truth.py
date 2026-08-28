"""Auditable maintainer-fix truth for the real root-cause benchmark suite.

The model never receives this data.  It exists only to prove that each GitHub
case's evaluator rubric is anchored to a real merged fix instead of a hand-made
answer key with no external provenance.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping


TRUTH_LOCK_SCHEMA_VERSION = 1
TRUTH_LOCK_PATH = Path("benchmarks/agent-investigation/root-cause-truth-lock.json")
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def load_truth_lock(repo_root: Path) -> dict[str, Any]:
    path = repo_root.resolve() / TRUTH_LOCK_PATH
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("root-cause truth lock must be a JSON object")
    return payload


def _fix_patterns(case: Mapping[str, Any]) -> tuple[str, ...]:
    root_cause = case.get("root_cause") or {}
    if not isinstance(root_cause, Mapping):
        raise ValueError(f"{case.get('id')}: root_cause must be an object")
    fix = root_cause.get("fix_alignment") or {}
    if not isinstance(fix, Mapping):
        raise ValueError(f"{case.get('id')}: fix_alignment must be an object")
    patterns = fix.get("patterns")
    if not isinstance(patterns, list) or not patterns:
        raise ValueError(f"{case.get('id')}: fix_alignment.patterns must be non-empty")
    result: list[str] = []
    for value in patterns:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{case.get('id')}: fix_alignment pattern must be non-empty")
        re.compile(value)
        result.append(value)
    return tuple(result)


def validate_truth_lock(
    repo_root: Path,
    cases: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Validate identity, merge proof, and rubric grounding for GitHub cases."""

    if cases is None:
        # Import lazily so root_cause_suite can also call this helper later
        # without creating a module-import cycle.
        from .root_cause_suite import SUITE_ID, suite_cases

        expected_suite_id = SUITE_ID
        rows = list(suite_cases())
    else:
        from .root_cause_suite import SUITE_ID

        expected_suite_id = SUITE_ID
        rows = [dict(item) for item in cases]

    payload = load_truth_lock(repo_root)
    if payload.get("schema_version") != TRUTH_LOCK_SCHEMA_VERSION:
        raise ValueError(
            f"truth lock schema_version must be {TRUTH_LOCK_SCHEMA_VERSION}"
        )
    if payload.get("suite_id") != expected_suite_id:
        raise ValueError("truth lock suite_id does not match root-cause suite")
    locked = payload.get("cases")
    if not isinstance(locked, Mapping):
        raise ValueError("truth lock cases must be an object")

    github_cases = {
        str(item["id"]): item
        for item in rows
        if isinstance(item.get("source"), Mapping)
        and item["source"].get("kind") == "github_issue"
    }
    if set(locked) != set(github_cases):
        missing = sorted(set(github_cases) - set(locked))
        extra = sorted(set(locked) - set(github_cases))
        raise ValueError(f"truth lock case mismatch: missing={missing} extra={extra}")

    projects: Counter[str] = Counter()
    grounded = 0
    for case_id, case in sorted(github_cases.items()):
        truth = locked[case_id]
        if not isinstance(truth, Mapping):
            raise ValueError(f"{case_id}: truth row must be an object")
        source = case["source"]
        repo = str(source["repo"])
        issue = int(source["number"])
        fix_pr = int(source["fix_pr"])
        if truth.get("repo") != repo:
            raise ValueError(f"{case_id}: truth repo does not match suite case")
        if truth.get("source_issue") != issue:
            raise ValueError(f"{case_id}: truth source_issue does not match suite case")
        if truth.get("fix_pr") != fix_pr:
            raise ValueError(f"{case_id}: truth fix_pr does not match suite case")
        merged_at = str(truth.get("merged_at") or "")
        if not merged_at.endswith("Z"):
            raise ValueError(f"{case_id}: merged_at must prove a merged UTC PR")
        merge_sha = str(truth.get("merge_commit_sha") or "")
        if _SHA_RE.fullmatch(merge_sha) is None:
            raise ValueError(f"{case_id}: merge_commit_sha must be a 40-char git SHA")
        title = str(truth.get("fix_title") or "").strip()
        truth_text = str(truth.get("truth_text") or "").strip()
        if not title or not truth_text:
            raise ValueError(f"{case_id}: fix_title/truth_text must be non-empty")
        combined = f"{title}\n{truth_text}"
        patterns = _fix_patterns(case)
        if not any(
            re.search(pattern, combined, flags=re.IGNORECASE | re.DOTALL)
            for pattern in patterns
        ):
            raise ValueError(
                f"{case_id}: fix_alignment rubric is not grounded in locked merged-fix truth"
            )
        expected_issue = f"https://github.com/{repo}/issues/{issue}"
        expected_fix = f"https://github.com/{repo}/pull/{fix_pr}"
        if case.get("source_issue") != expected_issue:
            raise ValueError(f"{case_id}: source_issue URL does not match locked identity")
        if case.get("fix_reference") != expected_fix:
            raise ValueError(f"{case_id}: fix_reference URL does not match locked identity")
        grounded += 1
        projects[repo] += 1

    return {
        "status": "ok",
        "schema_version": TRUTH_LOCK_SCHEMA_VERSION,
        "suite_id": expected_suite_id,
        "github_cases": len(github_cases),
        "merged_fix_truth": len(github_cases),
        "fix_alignment_grounded": grounded,
        "projects": dict(sorted(projects.items())),
    }


__all__ = [
    "TRUTH_LOCK_PATH",
    "TRUTH_LOCK_SCHEMA_VERSION",
    "load_truth_lock",
    "validate_truth_lock",
]
