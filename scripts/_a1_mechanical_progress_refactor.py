from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, got {count}")
    return text.replace(old, new, 1)


# 1) Public retrieve wrapper: propagate only mechanical acquisition-end facts.
path = "src/tracecite/runtime/retrieve_contract.py"
text = read(path)
text = text.replace(
    "stop_reason=result.stop_reason",
    "acquisition_end_reason=result.acquisition_end_reason",
)
old_gap = '''def _with_actionable_gap_progress(result: RetrievalResult) -> RetrievalResult:\n    gaps = [\n        item\n        for item in result.canonical_result.get("missing_evidence") or []\n        if isinstance(item, Mapping) and item.get("actionable") is True\n    ]\n    if not gaps or result.progress.actionable_gaps >= len(gaps):\n        return result\n\n    progress = replace(\n        result.progress,\n        actionable_gaps=len(gaps),\n        ready_for_reasoning=(\n            False if result.progress.ready_for_reasoning is True else result.progress.ready_for_reasoning\n        ),\n        stop_recommended=False,\n        stop_reason="actionable_evidence_gap",\n        stop=None,\n    )\n    return RetrievalResult(\n        operation=result.operation,\n        status=result.status,\n        canonical_result=result.canonical_result,\n        progress=progress,\n        new_evidence=result.new_evidence,\n        repeated_evidence=result.repeated_evidence,\n        stop_reason=None,\n    )\n'''
new_gap = '''def _with_actionable_gap_progress(result: RetrievalResult) -> RetrievalResult:\n    """Expose the number of actionable evidence gaps without judging sufficiency."""\n\n    gaps = [\n        item\n        for item in result.canonical_result.get("missing_evidence") or []\n        if isinstance(item, Mapping) and item.get("actionable") is True\n    ]\n    if not gaps or result.progress.actionable_gaps >= len(gaps):\n        return result\n\n    progress = replace(result.progress, actionable_gaps=len(gaps))\n    return RetrievalResult(\n        operation=result.operation,\n        status=result.status,\n        canonical_result=result.canonical_result,\n        progress=progress,\n        new_evidence=result.new_evidence,\n        repeated_evidence=result.repeated_evidence,\n        acquisition_end_reason=result.acquisition_end_reason,\n    )\n'''
text = replace_once(text, old_gap, new_gap, "retrieve_contract actionable gaps")
text = text.replace(
    "        stop_reason=None,\n",
    "        acquisition_end_reason=result.acquisition_end_reason,\n",
)
write(path, text)

# 2) Old large-evidence benchmark host must render novelty as a fact, not a stop.
path = "benchmarks/agent-investigation/gmi_scale_host.py"
text = read(path)
text = replace_once(
    text,
    "from tracecite.runtime.evidence_progress import EvidenceProgressTracker, EvidenceReadiness",
    "from tracecite.runtime.evidence_progress import EvidenceProgress, EvidenceProgressTracker",
    "gmi progress import",
)
text = text.replace("def _progress_line(progress: EvidenceReadiness) -> str:", "def _progress_line(progress: EvidenceProgress) -> str:")
old_line = '''        f"source_complete={progress.source_complete} "\n        f"no_growth={progress.consecutive_no_growth} stop={progress.stop_reason}"\n'''
new_line = '''        f"source_complete={progress.source_complete} "\n        f"no_growth={progress.consecutive_no_growth}"\n'''
text = replace_once(text, old_line, new_line, "gmi progress rendering")
text = text.replace("@STOP reason=NO_NEW_EVIDENCE", "@NOVELTY state=no_new_evidence")
text = text.replace("@STOP inspection_output_truncated=", "@ACQ_END inspection_output_truncated=")
write(path, text)

# 3) Runtime tests: no-new remains a retrieval fact; explicit traversal exhaustion is acquisition-only.
path = "tests/test_runtime_agent_api.py"
text = read(path)
text = text.replace("    StopReason,\n", "")
text = replace_once(
    text,
    "    assert snapshot.consecutive_no_growth == 0\n    assert snapshot.stop_recommended is False\n",
    '''    assert snapshot.consecutive_no_growth == 0\n    payload = snapshot.to_dict()\n    assert "ready_for_reasoning" not in payload\n    assert "stop_recommended" not in payload\n    assert "stop" not in payload\n    assert snapshot.acquisition_end_reason is None\n''',
    "progress restore assertions",
)
pattern = re.compile(
    r"def test_progress_exposes_formal_no_new_evidence_stop\(\) -> None:\n.*?\n\n\ndef test_retrieve_query_suppresses_repeated_evidence",
    re.DOTALL,
)
replacement = '''def test_progress_no_growth_remains_mechanical() -> None:\n    tracker = EvidenceProgressTracker()\n    tracker.observe(evidence_ids=("E1",))\n    progress = tracker.observe(evidence_ids=("E1",))\n\n    assert progress.delta.new_evidence == 0\n    assert progress.consecutive_no_growth == 1\n    assert progress.acquisition_end_reason is None\n    payload = progress.to_dict()\n    assert "ready_for_reasoning" not in payload\n    assert "stop_recommended" not in payload\n    assert "stop" not in payload\n\n\ndef test_retrieve_query_suppresses_repeated_evidence'''
text, count = pattern.subn(replacement, text, count=1)
if count != 1:
    raise RuntimeError(f"progress no-growth test: expected 1 replacement, got {count}")
text = replace_once(
    text,
    '''    assert second.stop_reason is not None\n    assert second.stop_reason.kind == "no_new_evidence"\n    assert second.to_dict()["evidence"] == []\n''',
    '''    assert second.acquisition_end_reason is None\n    novelty = second.to_dict()["data"]["novelty"]\n    assert novelty["state"] == "no_new_evidence"\n    assert "all_returned_evidence_already_seen" in novelty["basis"]\n    assert second.to_dict()["evidence"] == []\n''',
    "query repeated assertions",
)
text = replace_once(
    text,
    '''    assert second.stop_reason is not None\n    assert "immutable_source_identity" in second.stop_reason.basis\n''',
    '''    assert second.acquisition_end_reason is None\n    novelty = second.to_dict()["data"]["novelty"]\n    assert novelty["state"] == "no_new_evidence"\n    assert "immutable_source_identity" in novelty["basis"]\n''',
    "range repeated immutable assertions",
)
text = replace_once(
    text,
    '    assert "requested_context_already_covered" in second.stop_reason.basis\n',
    '    assert "requested_context_already_covered" in second.to_dict()["data"]["novelty"]["basis"]\n',
    "range ownership novelty assertion",
)
text = text.replace("    assert expanded.stop_reason is None\n", "    assert expanded.acquisition_end_reason is None\n")
text = replace_once(
    text,
    '''    assert result.stop_reason is not None\n    assert result.stop_reason.kind == "frontier_exhausted"\n    assert result.progress.frontier_exhausted is True\n''',
    '''    assert result.acquisition_end_reason is not None\n    assert result.acquisition_end_reason.kind == "frontier_exhausted"\n    assert result.progress.frontier_exhausted is True\n    assert "stop" not in result.to_dict()\n''',
    "mechanical frontier end assertions",
)
write(path, text)

# 4) Architecture guardrail: these epistemic/stop symbols must not creep back into Runtime.
path = "tests/test_runtime_boundary.py"
text = read(path)
append = '''\n\ndef test_runtime_progress_contract_has_no_epistemic_stop_semantics() -> None:\n    forbidden_exports = {\n        "EvidenceReadiness",\n        "ReadinessStatus",\n        "StopKind",\n        "StopReason",\n    }\n    assert forbidden_exports.isdisjoint(runtime.__all__)\n    for name in forbidden_exports:\n        assert not hasattr(runtime, name)\n\n    source = (ROOT / "src" / "tracecite" / "runtime" / "evidence_progress.py").read_text(\n        encoding="utf-8"\n    )\n    assert "ready_for_reasoning" not in source\n    assert "stop_recommended" not in source\n    assert '"no_new_evidence",' not in source.split("AcquisitionEndKind", 1)[1].split("]", 1)[0]\n'''
if "test_runtime_progress_contract_has_no_epistemic_stop_semantics" not in text:
    text += append
write(path, text)

# 5) No old public progress symbols may remain in Runtime implementation.
for py in (ROOT / "src" / "tracecite" / "runtime").glob("*.py"):
    body = py.read_text(encoding="utf-8")
    for forbidden in ("EvidenceReadiness", "ReadinessStatus", "stop_recommended", "ready_for_reasoning"):
        if forbidden in body:
            raise RuntimeError(f"forbidden A1 symbol {forbidden!r} remains in {py.relative_to(ROOT)}")

print("A1 mechanical progress refactor applied")
