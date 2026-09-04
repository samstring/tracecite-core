# Migration 0002: Evidence Shell and `too_broad` transport status

## Scope

This migration applies to Agent/Host integrations consuming TraceCite Runtime `AgentResult` values on the `feature_for_agent_refacotr_shell` refactor branch.

## Additive result status

`AgentResult.status` now accepts:

```text
too_broad
```

`too_broad` is a mechanical transport result. It means the complete logical-record payload selected by an Evidence Shell search exceeded the user/host-configured Evidence transport budget.

It does **not** mean:

- the search failed;
- there were no matches;
- the evidence is insufficient;
- the Agent should stop;
- the Runtime selected a causal interpretation.

Consumers that previously treated the status set as closed must add `too_broad` handling.

Typical payload fields are:

```json
{
  "operation": "evidence_shell",
  "status": "too_broad",
  "outcome": "unknown",
  "evidence": [],
  "coverage": {
    "too_broad": true,
    "evidence_returned": 0,
    "observed_at_least_tokens": 12001
  },
  "data": {
    "reason": "MATCHED_EVIDENCE_BUDGET_EXCEEDED",
    "refine_query": true,
    "evidence_budget": {
      "owner": "user_policy"
    }
  }
}
```

## Agent behavior

On `too_broad`, an Agent must refine the search program or scope. The Agent must not increase the Evidence budget, request a complete locator dump, or reinterpret a partial first-N sample as the complete match set.

## New Agent search surface

`tracecite_run` / `run_evidence_shell()` is an additive Agent-facing query-program surface. Existing canonical `retrieve`, `materialize`, `replay`, `aggregate`, `traverse`, and `verify` APIs remain available.

The Evidence Shell request intentionally contains no `max_evidence_tokens` or `max_evidence_bytes` fields. Those limits are supplied separately by `EvidenceShellPolicy`, which is owned by user/host configuration.

## Compatibility

Legacy `retrieve/search` behavior remains available during the staged migration. In particular, this migration does not immediately delete legacy filter artifacts or `EvidenceIndex` code paths. New Agent text-search flows should prefer Evidence Shell, where oversized result sets are rejected before any locator dump reaches model context.

## Schema version

`RESULT_SCHEMA_VERSION` remains `1` because this is an additive status and additive API surface on the refactor branch. Consumers that validate a hard-coded status enum must update that enum before adopting this branch.
