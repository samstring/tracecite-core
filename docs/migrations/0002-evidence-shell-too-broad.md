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

An aggregate may similarly return `reason=AGGREGATE_OUTPUT_BUDGET_EXCEEDED` when the aggregate projection itself is too large to cross the model boundary.

## Agent behavior

On `too_broad`, an Agent must refine the search program or scope. The Agent must not increase the Evidence budget, request a complete locator dump, or reinterpret a partial first-N sample as the complete match set.

## New Agent search surface

`tracecite_run` / `run_evidence_shell()` is the preferred Agent-facing text-query program surface. The Evidence Shell request intentionally contains no `max_evidence_tokens` or `max_evidence_bytes` fields. Those limits are supplied separately by `EvidenceShellPolicy`, which is owned by user/host configuration.

The same Host/User Evidence policy also caps Pi materialize/replay transport; the Agent cannot pass a larger character/token limit through the tool schema.

## Query compatibility change

Public text `QueryTarget` retrieval now reduces to the Evidence Shell contract. High-cardinality Agent text queries therefore no longer project a complete `EvidenceIndex` locator list.

Legacy `EvidenceIndex` and matched-record/filter artifact code may still exist for non-Agent/legacy workflows, but they are no longer required by the Agent text-search hot path.

The new hot path is:

```text
SourceVersion
  -> raw candidate search where safe
  -> Segmenter complete Record recovery
  -> shell pipeline
  -> user Evidence budget gate
  -> EvidencePointer / too_broad
```

`matched_records.jsonl`, `hits.jsonl`, `evidence.log`, filter history, and unmatched-token summaries are not required intermediates for this path.

## SourceVersion behavior

Agent text search now binds to an immutable QuestionSourceView:

- one user-question RetrievalSession/context reuses one fixed SourceVersion;
- unchanged mutable sources can reuse the previous snapshot + SHA + line metadata across questions;
- changed mutable files create a new immutable snapshot while computing SHA and line count in the same copy pass;
- live mode prefers cooperative LiveCut and immutable segments, with a verified append-only incremental fallback;
- managed materialize/replay reuses the already established snapshot/segment SHA rather than hashing the full file again.

Hosts that keep a long-lived conversation session across multiple user questions must rotate or supply a user-question retrieval context at each new question so the SourceVersion can be refreshed when appropriate.

## Agent result SourceVersion projection

The persisted SourceVersion store may contain a full immutable segment manifest. AgentResult transport does not expose that complete manifest on every call. It projects compact source-view metadata (`version_id`, mode, totals, segment count, reuse state); exact segment SHA/path provenance remains on each EvidencePointer.

For one-segment views, `data.source_sha256` is projected so adapters can reuse the established SHA without another full-file hash.

## Existing APIs

Canonical `retrieve`, `materialize`, `replay`, `aggregate`, `traverse`, and `verify` APIs remain available. Standalone legacy aggregate/filter helpers may retain their historical contracts; Agent multi-stage text investigation should use `tracecite_run` to remain SourceVersion-bound and keep intermediate results outside model context.

## Schema version

`RESULT_SCHEMA_VERSION` remains `1` because `too_broad` and the compact SourceVersion metadata are additive/transport-compatible changes on the refactor branch. Consumers that validate a hard-coded status enum must update that enum before adopting this branch.
