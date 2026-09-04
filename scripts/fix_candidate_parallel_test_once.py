from __future__ import annotations

from pathlib import Path

path = Path("tests/test_session_novelty_regressions.py")
text = path.read_text(encoding="utf-8")
old = '''    store = _store(tmp_path)\n\n    def search(index: int) -> None:\n        result = retrieve_with_session(\n            EvidenceRequest(QueryTarget(source, f"marker-{index}")),\n            store,\n        )\n        assert result.new_evidence\n\n    with ThreadPoolExecutor(max_workers=8) as pool:\n'''
new = '''    store = _store(tmp_path)\n    policy = EvidenceRoutingPolicy(\n        mode="progressive",\n        progressive_max_candidates=1,\n        deep_progressive_max_candidates=1,\n    )\n\n    def search(index: int) -> None:\n        result = retrieve_with_session(\n            EvidenceRequest(QueryTarget(source, f"marker-{index}")),\n            store,\n            routing_policy=policy,\n        )\n        assert result.new_evidence\n\n    with ThreadPoolExecutor(max_workers=8) as pool:\n'''
if old not in text:
    raise RuntimeError("parallel session test block not found")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
print("parallel session test migrated to internal candidate policy")
