from __future__ import annotations

import ast
from pathlib import Path

CANONICAL_TOP_LEVEL = {'EvidenceRoute', 'RangeTarget', 'verify', 'SourceVersion', 'SourceTarget', 'materialize', 'EvidenceTraversal', 'QueryTarget', 'traverse', 'AggregateRequest', 'AggregateOperation', 'aggregate', 'RetrievalSessionStore', 'ProviderTarget', 'EvidenceRoutingPolicy', 'retrieve', 'list_capabilities', 'EvidenceIdentity', 'replay', 'RetrievalSessionState', 'TraversalLimits', 'EvidenceRequest', 'RetrievalResult'}


def test_tests_do_not_reintroduce_removed_top_level_contracts() -> None:
    root = Path(__file__).resolve().parent
    violations = []
    for path in sorted(root.glob("test_*.py")):
        if path.name == Path(__file__).name:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "tracecite":
                for alias in node.names:
                    if alias.name not in CANONICAL_TOP_LEVEL:
                        violations.append(f"{path.name}:{node.lineno}:{alias.name}")
    assert violations == [], "removed top-level TraceCite contracts imported by tests: " + ", ".join(violations)
