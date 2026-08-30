from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def rw(path: str, transforms):
    p = ROOT / path
    text = p.read_text(encoding='utf-8')
    for old, new, expected in transforms:
        count = text.count(old)
        if count != expected:
            raise RuntimeError(f'{path}: expected {expected} matches for {old[:80]!r}, got {count}')
        text = text.replace(old, new)
    p.write_text(text, encoding='utf-8')


rw('src/tracecite/runtime/relationship_frontier.py', [
    ('        stop_reason=result.stop_reason,\n', '        acquisition_end_reason=result.acquisition_end_reason,\n', 1),
])

session = ROOT / 'src/tracecite/runtime/session_retrieval.py'
text = session.read_text(encoding='utf-8')
text = text.replace(
    'from .evidence_progress import EvidenceProgressTracker, StopReason',
    'from .evidence_progress import EvidenceProgressTracker',
)
old_covered = '''        stop = StopReason(\n            "no_new_evidence",\n            scope={"source_version": source_key},\n            basis=("source_generation", "requested_context_already_covered"),\n        )\n        return RetrievalResult(\n            operation="expand",\n            status="no_new_evidence",\n            canonical_result={\n                "operation": "expand",\n                "status": "ok",\n                "outcome": "not_assessed",\n                "evidence": [],\n                "coverage": {},\n                "data": {\n                    "new_text": "",\n                    "unseen_ranges": [],\n                    "source_version": source_key,\n                },\n            },\n            progress=readiness,\n            stop_reason=stop,\n        )\n'''
new_covered = '''        return RetrievalResult(\n            operation="expand",\n            status="no_new_evidence",\n            canonical_result={\n                "operation": "expand",\n                "status": "ok",\n                "outcome": "not_assessed",\n                "evidence": [],\n                "coverage": {},\n                "data": {\n                    "new_text": "",\n                    "unseen_ranges": [],\n                    "source_version": source_key,\n                    "novelty": {\n                        "state": "no_new_evidence",\n                        "basis": ["source_generation", "requested_context_already_covered"],\n                        "source_version": source_key,\n                    },\n                },\n            },\n            progress=readiness,\n        )\n'''
if text.count(old_covered) != 1:
    raise RuntimeError('session_retrieval covered-range block not found exactly once')
text = text.replace(old_covered, new_covered, 1)
old_tail = '''    status = base.status\n    stop = base.stop_reason\n    if (\n        str(canonical.get("status") or "").lower() not in {"error", "no_match"}\n        and evidence\n        and not new_rows\n        and not new_relation_ids\n        and readiness.delta.new_lines == 0\n        and not truncated\n    ):\n        status = "no_new_evidence"\n        stop = StopReason("no_new_evidence", basis=("all_returned_evidence_already_seen",))\n\n    return RetrievalResult(\n        operation=base.operation,\n        status=status,\n        canonical_result=canonical,\n        progress=readiness,\n        new_evidence=new_rows,\n        repeated_evidence=repeated,\n        stop_reason=stop,\n    )\n'''
new_tail = '''    status = base.status\n    acquisition_end_reason = base.acquisition_end_reason\n    if (\n        str(canonical.get("status") or "").lower() not in {"error", "no_match"}\n        and evidence\n        and not new_rows\n        and not new_relation_ids\n        and readiness.delta.new_lines == 0\n        and not truncated\n    ):\n        status = "no_new_evidence"\n        data = dict(canonical.get("data") or {})\n        data["novelty"] = {\n            "state": "no_new_evidence",\n            "basis": ["all_returned_evidence_already_seen"],\n        }\n        canonical["data"] = data\n\n    return RetrievalResult(\n        operation=base.operation,\n        status=status,\n        canonical_result=canonical,\n        progress=readiness,\n        new_evidence=new_rows,\n        repeated_evidence=repeated,\n        acquisition_end_reason=acquisition_end_reason,\n    )\n'''
if text.count(old_tail) != 1:
    raise RuntimeError('session_retrieval repeated-evidence tail not found exactly once')
text = text.replace(old_tail, new_tail, 1)
session.write_text(text, encoding='utf-8')

# Strengthen the architectural guardrail to cover every Runtime module, not only evidence_progress.py.
boundary = ROOT / 'tests/test_runtime_boundary.py'
body = boundary.read_text(encoding='utf-8')
old = '''    source = (ROOT / "src" / "tracecite" / "runtime" / "evidence_progress.py").read_text(\n        encoding="utf-8"\n    )\n    assert "ready_for_reasoning" not in source\n    assert "stop_recommended" not in source\n    assert '\"no_new_evidence\",' not in source.split("AcquisitionEndKind", 1)[1].split("]", 1)[0]\n'''
new = '''    runtime_dir = ROOT / "src" / "tracecite" / "runtime"\n    for path in runtime_dir.glob("*.py"):\n        source = path.read_text(encoding="utf-8")\n        assert "ready_for_reasoning" not in source, path\n        assert "stop_recommended" not in source, path\n        assert "from .evidence_progress import EvidenceProgressTracker, StopReason" not in source, path\n        assert "result.stop_reason" not in source, path\n\n    progress_source = (runtime_dir / "evidence_progress.py").read_text(encoding="utf-8")\n    assert '\"no_new_evidence\",' not in progress_source.split("AcquisitionEndKind", 1)[1].split("]", 1)[0]\n'''
if body.count(old) != 1:
    raise RuntimeError('runtime boundary guardrail block not found')
body = body.replace(old, new, 1)
boundary.write_text(body, encoding='utf-8')

# Local static guard before pytest.
for path in (ROOT / 'src' / 'tracecite' / 'runtime').glob('*.py'):
    source = path.read_text(encoding='utf-8')
    if 'from .evidence_progress import EvidenceProgressTracker, StopReason' in source:
        raise RuntimeError(f'old StopReason import remains in {path}')
    if 'result.stop_reason' in source:
        raise RuntimeError(f'old RetrievalResult.stop_reason remains in {path}')

print('A1 session path cleanup applied')
