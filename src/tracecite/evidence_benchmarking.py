"""Small deterministic benchmark for the evidence-intelligence experiment.

This is a component benchmark, not an end-to-end model-quality benchmark. It
measures whether correlation/grouping/reduction can keep required incident
markers while materially shrinking the Agent-visible evidence representation.
"""

from __future__ import annotations

import json
from typing import Any

from tracecite.evidence import EntityRef
from tracecite.integrations.evidence_package import build_evidence_package, estimate_json_tokens
from tracecite.runtime.correlation import EvidenceNode, correlate
from tracecite.runtime.grouping import group_evidence
from tracecite.runtime.reducer import ReductionPolicy, reduce_evidence


def build_synthetic_incident() -> tuple[list[EvidenceNode], tuple[str, ...]]:
    session = EntityRef("session", "S-checkout", namespace="mobile")
    request = EntityRef("request", "R-pay", namespace="checkout")
    trace = EntityRef("trace", "T-pay", namespace="otel")
    required = ("crash", "tap-pay", "request-timeout", "backend-timeout")
    nodes = [
        EvidenceNode(
            "crash",
            "crash",
            "bugly",
            timestamp="2026-08-28T12:00:05Z",
            severity="fatal",
            label="checkout callback crashed",
            entities=(session,),
            evidence_uri="evidence://bugly/crash",
        ),
        EvidenceNode(
            "tap-pay",
            "user_event",
            "analytics",
            timestamp="2026-08-28T12:00:00Z",
            label="tap pay",
            entities=(session,),
            evidence_uri="evidence://analytics/tap-pay",
        ),
        EvidenceNode(
            "request-timeout",
            "network",
            "client",
            timestamp="2026-08-28T12:00:03Z",
            severity="error",
            label="request R-pay timeout",
            entities=(session, request),
            evidence_uri="evidence://client/request-timeout",
        ),
        EvidenceNode(
            "backend-timeout",
            "span",
            "otel",
            timestamp="2026-08-28T12:00:02Z",
            severity="error",
            label="payment gateway timeout",
            entities=(request, trace),
            evidence_uri="evidence://otel/backend-timeout",
        ),
    ]
    nodes.extend(
        EvidenceNode(
            f"retry-{index}",
            "log",
            "client",
            timestamp=f"2026-08-28T12:00:{index % 60:02d}Z",
            severity="info",
            label=f"retry {index} waiting for payment callback",
            entities=(session,),
            evidence_uri=f"evidence://client/retry-{index}",
        )
        for index in range(180)
    )
    nodes.extend(
        EvidenceNode(
            f"noise-{index}",
            "log",
            "background-worker",
            timestamp=f"2026-08-28T11:59:{index % 60:02d}Z",
            severity="debug",
            label=f"unrelated cache refresh {index}",
            entities=(EntityRef("job", f"J-{index}", namespace="worker"),),
            evidence_uri=f"evidence://worker/noise-{index}",
        )
        for index in range(60)
    )
    return nodes, required


def run_component_benchmark(*, max_tokens: int = 1200) -> dict[str, Any]:
    nodes, required = build_synthetic_incident()
    graph = correlate(nodes)
    grouping = group_evidence(nodes)
    reduction = reduce_evidence(
        graph,
        grouping,
        policy=ReductionPolicy(max_items=12, seed_ids=("crash",)),
    )
    package = build_evidence_package(
        graph,
        grouping,
        reduction,
        max_tokens=max_tokens,
    )
    payload = package.to_dict()
    visible = {str(item.get("id")) for item in payload["evidence"]}
    required_hits = [item for item in required if item in visible]
    raw_tokens = estimate_json_tokens([node.to_dict() for node in nodes])
    package_tokens = int(payload["budget"]["estimated_tokens"])
    return {
        "schema_version": 1,
        "case": "synthetic-payment-incident",
        "inputs": {
            "evidence_nodes": len(nodes),
            "sources": len({node.source for node in nodes}),
        },
        "quality": {
            "required_evidence": list(required),
            "required_hits": required_hits,
            "required_recall": round(len(required_hits) / len(required), 4),
        },
        "context_cost": {
            "raw_estimated_tokens": raw_tokens,
            "package_estimated_tokens": package_tokens,
            "token_reduction_ratio": round(1.0 - package_tokens / raw_tokens, 4),
            "package_evidence": len(payload["evidence"]),
            "canonical_evidence": len(nodes),
        },
        "coverage": payload["coverage"],
        "budget": payload["budget"],
        "pass": bool(
            len(required_hits) == len(required)
            and package_tokens <= max_tokens
            and package_tokens < raw_tokens
        ),
    }


def main() -> int:
    result = run_component_benchmark()
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
