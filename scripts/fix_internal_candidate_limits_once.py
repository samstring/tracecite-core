from __future__ import annotations

import ast
import re
from pathlib import Path


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"missing expected block: {label}")
    return text.replace(old, new, 1)


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


# The normal CLI no longer exposes candidate/body page limits. Agent input size
# is governed by the investigation max_input_per_round budget and progressive
# disclosure. Compact transport still has its own complete-document bound.
cli_path = Path("src/tracecite/integrations/cli.py")
cli = cli_path.read_text(encoding="utf-8")
cli = replace_once(
    cli,
    '''    search_parser.add_argument(\n        "--max-evidence",\n        type=int,\n        default=None,\n        metavar="N",\n        help=(\n            f"maximum evidence rows in the agent view "\n            f"(default {DEFAULT_AGENT_MAX_EVIDENCE} for agent profiles)"\n        ),\n    )\n    search_parser.add_argument(\n        "--max-line-chars",\n        type=int,\n        default=None,\n        metavar="N",\n        help=(\n            f"truncate matched evidence lines to N characters "\n            f"(default {DEFAULT_FILTER_MAX_LINE_CHARS} for agent profiles)"\n        ),\n    )\n''',
    '',
    label="CLI candidate/body options",
)
cli = replace_once(
    cli,
    '''        max_evidence = (\n            args.max_evidence\n            if args.max_evidence is not None\n            else (DEFAULT_AGENT_MAX_EVIDENCE if agent_transport else None)\n        )\n        max_line_chars = (\n            args.max_line_chars\n            if args.max_line_chars is not None\n            else (DEFAULT_FILTER_MAX_LINE_CHARS if agent_transport else None)\n        )\n        if max_evidence is not None and max_evidence < 1:\n            raise ValueError("max-evidence must be at least 1")\n        if max_line_chars is not None and max_line_chars < 1:\n            raise ValueError("max-line-chars must be at least 1")\n''',
    '',
    label="CLI candidate/body derivation",
)
cli = replace_once(
    cli,
    '''            fold=args.fold,\n            max_evidence=max_evidence,\n            max_line_chars=max_line_chars,\n            cache=args.cache,''',
    '''            fold=args.fold,\n            cache=args.cache,''',
    label="CLI search candidate/body kwargs",
)
cli_path.write_text(cli, encoding="utf-8")


# Stateful CLI keeps the artifact-writing compatibility branch, but neither the
# canonical request nor the raw compatibility search exposes result-page knobs.
stateful_path = Path("src/tracecite/integrations/stateful_cli.py")
stateful = stateful_path.read_text(encoding="utf-8")
stateful = stateful.replace('        max_evidence=None,\n        max_line_chars=None,\n', '', 1)
stateful = stateful.replace(
    '                max_evidence=max_evidence,\n                max_line_chars=max_line_chars,\n',
    '',
    1,
)
stateful = stateful.replace(
    '                fold=fold,\n                max_evidence=max_evidence,\n                max_line_chars=max_line_chars,\n            ),',
    '                fold=fold,\n            ),',
    1,
)
stateful_path.write_text(stateful, encoding="utf-8")


# GMI hosts exercise the canonical contract; None-valued legacy knobs were only
# vestigial and must not survive on QueryTarget.
for host_name in (
    "benchmarks/agent-investigation/gmi_canonical_host.py",
    "benchmarks/agent-investigation/gmi_evidence_contract_host.py",
):
    host_path = Path(host_name)
    host = host_path.read_text(encoding="utf-8")
    host = host.replace(
        '                    snapshot=False,\n                    max_evidence=None,\n                    max_line_chars=None,\n',
        '                    snapshot=False,\n',
    )
    host_path.write_text(host, encoding="utf-8")


# Enforce the migration contract over all Python sources/tests so no hidden
# canonical QueryTarget or search call silently keeps the retired knobs.
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
            retired = [kw.arg for kw in node.keywords if kw.arg in {"max_evidence", "max_line_chars"}]
            if not retired:
                continue
            if name in {"QueryTarget", "search"}:
                offenders.append(f"{path}:{node.lineno}: {name}({','.join(retired)})")
if offenders:
    raise RuntimeError("retired public candidate/body limit fields remain:\n" + "\n".join(offenders))

print("candidate limit migration follow-up applied")
