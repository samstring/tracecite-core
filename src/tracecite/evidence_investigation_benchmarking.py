"""Component benchmark for deterministic multi-source evidence exploration.

This measures structural loop compression and evidence retention only. It does
not substitute for the external model-level benchmark under
``benchmarks/agent-investigation``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

from tracecite.integrations.investigator import investigate
from tracecite.integrations.json_evidence_provider import JsonEvidenceProvider
from tracecite.runtime.traversal_frontier import TraversalLimits


FIXTURE_NAMES = (
    "crash.json",
    "analytics.json",
    "network.json",
    "trace.json",
    "client.json",
)
REQUIRED_EVIDENCE = frozenset(
    {
        "crash:C123",
        "event:tap-pay",
        "network:R19",
        "span:T22",
        "span:callback",
        "client:callback",
    }
)


def run_investigation_benchmark(case_dir: str | Path) -> dict[str, Any]:
    root = Path(case_dir).expanduser().resolve()
    providers = [JsonEvidenceProvider.from_path(root / name) for name in FIXTURE_NAMES]
    result = investigate(
        providers,
        seed_evidence_ids=("crash:C123",),
        exploration_policy=TraversalLimits(
            max_depth=3,
            max_retrievals=20,
            max_no_growth_rounds=3,
        ),
        max_tokens=2400,
    )
    investigation = result.investigation
    package_ids = {str(item["id"]) for item in result.package.evidence}
    retained = REQUIRED_EVIDENCE & package_ids
    logical_rounds = {"seed"}
    logical_rounds.update(
        step.reason
        for step in investigation.trace
        if step.reason.startswith("expand:") and step.new_evidence > 0
    )
    baseline_calls = max(1, len(logical_rounds))
    orchestrated_calls = 1
    loop_reduction = 1.0 - (orchestrated_calls / baseline_calls)
    raw_records = sum(provider.evidence_count for provider in providers)
    return {
        "schema_version": 1,
        "status": investigation.status,
        "stop_reason": investigation.stop_reason,
        "raw_provider_records": raw_records,
        "discovered_evidence": len(investigation.graph.nodes),
        "package_evidence": len(result.package.evidence),
        "package_estimated_tokens": result.package.budget["estimated_tokens"],
        "package_max_tokens": result.package.budget["max_tokens"],
        "required_evidence": len(REQUIRED_EVIDENCE),
        "required_retained": len(retained),
        "required_recall": len(retained) / len(REQUIRED_EVIDENCE),
        "structural_agent_rounds_without_orchestrator": baseline_calls,
        "structural_agent_calls_with_orchestrator": orchestrated_calls,
        "structural_loop_reduction": round(loop_reduction, 4),
        "internal_provider_retrievals": investigation.coverage["retrievals"],
        "coverage_complete": investigation.coverage["complete"],
        "citation_uris": [
            str(item.get("uri") or "") for item in result.package.evidence if item.get("uri")
        ],
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case_dir", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    result = run_investigation_benchmark(args.case_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    passed = (
        result["status"] == "ok"
        and result["coverage_complete"] is True
        and result["required_recall"] == 1.0
        and result["structural_agent_calls_with_orchestrator"]
        < result["structural_agent_rounds_without_orchestrator"]
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["REQUIRED_EVIDENCE", "run_investigation_benchmark"]
