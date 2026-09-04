from __future__ import annotations

import ast
import re
from pathlib import Path


# The compatibility surface remains a pure forwarding module. We intentionally
# do not preserve max_evidence as another public search knob.
tools_path = Path("src/tracecite/runtime/tools.py")
tools_path.write_text(
    '''"""Backward-compatible ``runtime.tools`` surface over canonical acquisition.\n\nRuntime internals must depend on :mod:`tracecite.runtime.acquisition`; this\nmodule remains only for legacy callers and integrations while preserving the\nexisting Python surface.\n"""\n\nfrom __future__ import annotations\n\nfrom . import acquisition as _acquisition\nfrom .acquisition import *  # noqa: F401,F403\n\n\ndef __getattr__(name: str):\n    return getattr(_acquisition, name)\n\n\ndef __dir__() -> list[str]:\n    return sorted(set(globals()) | set(dir(_acquisition)))\n''',
    encoding="utf-8",
)


# Remove the temporary compatibility test that the first migration script added.
boundary_path = Path("tests/test_runtime_acquisition_boundary.py")
boundary = boundary_path.read_text(encoding="utf-8")
boundary = re.sub(
    r'\n\ndef test_legacy_tools_max_evidence_maps_to_internal_candidate_limit\(tmp_path\) -> None:.*?assert result\["coverage"\]\["evidence_returned"\] == 1\n',
    "\n",
    boundary,
    count=1,
    flags=re.S,
)
boundary_path.write_text(boundary, encoding="utf-8")


# Session novelty tests that intentionally need truncation now request the
# internal PROGRESSIVE policy cap; ordinary queries no longer carry page sizes.
session_path = Path("tests/test_session_novelty_regressions.py")
session = session_path.read_text(encoding="utf-8")
session = session.replace(
    "from tracecite.runtime import EvidenceRequest, QueryTarget, RangeTarget",
    "from tracecite.runtime import EvidenceRequest, EvidenceRoutingPolicy, QueryTarget, RangeTarget",
    1,
)
session = session.replace(
    '    request = EvidenceRequest(QueryTarget(source, "timeout", max_evidence=3))\n\n    first = retrieve_with_session(request, store).to_dict()\n    repeated = retrieve_with_session(request, store).to_dict()',
    '''    request = EvidenceRequest(QueryTarget(source, "timeout"))\n    policy = EvidenceRoutingPolicy(\n        mode="progressive",\n        progressive_max_candidates=3,\n        deep_progressive_max_candidates=3,\n    )\n\n    first = retrieve_with_session(request, store, routing_policy=policy).to_dict()\n    repeated = retrieve_with_session(request, store, routing_policy=policy).to_dict()''',
    1,
)
session = session.replace(', max_evidence=3)', ')')
session = session.replace(', max_evidence=1)', ')')
session_path.write_text(session, encoding="utf-8")


# Enforce the migration contract over all Python sources/tests so no hidden
# canonical QueryTarget call silently keeps the retired knob.
offenders: list[str] = []
for root in (Path("src"), Path("tests"), Path("benchmarks")):
    for path in root.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
            if name != "QueryTarget":
                continue
            retired = [kw.arg for kw in node.keywords if kw.arg in {"max_evidence", "max_line_chars"}]
            if retired:
                offenders.append(f"{path}:{node.lineno}: {','.join(retired)}")
if offenders:
    raise RuntimeError("retired QueryTarget limit fields remain:\n" + "\n".join(offenders))

print("candidate limit migration follow-up applied")
