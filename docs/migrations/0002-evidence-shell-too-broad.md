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

Agent text search now binds each logical source to an immutable `SessionSourceView` for the lifetime of one RetrievalSession/context:

- the first access in a RetrievalSession establishes or reuses one fixed SourceVersion;
- later tool calls in that same session reuse the exact version even if the original mutable/live path changes;
- a Host does not need to rotate SourceVersion at every user message when one conversation maps to one RetrievalSession;
- a new RetrievalSession checks the current source fingerprint on first access;
- unchanged mutable sources reuse the previous snapshot + SHA + line metadata across sessions;
- changed mutable files create a new immutable snapshot while computing SHA and line count in the same copy pass;
- live mode freezes on the session's first access, prefers cooperative LiveCut and immutable segments, and lets a later session capture newer bytes;
- managed materialize/replay reuses the already established snapshot/segment SHA rather than hashing the full file again.

`SessionSourceView` and `SessionSourceVersionStore` are the canonical public names. The internal historical `QuestionSourceView` / `question_id` names may remain compatibility aliases/fields while persisted state is migrated.

A newer SourceVersion requires a new RetrievalSession/context, or a future explicit refresh-source operation. TraceCite must never silently refresh a bound source inside the same session.

## Agent result SourceVersion projection

The persisted SourceVersion store may contain a full immutable segment manifest. AgentResult transport does not expose that complete manifest on every call. It projects compact source-view metadata (`version_id`, mode, totals, segment count, reuse state); exact segment SHA/path provenance remains on each EvidencePointer.

For one-segment views, `data.source_sha256` is projected so adapters can reuse the established SHA without another full-file hash.

## Existing APIs

Canonical `retrieve`, `materialize`, `replay`, `aggregate`, `traverse`, and `verify` APIs remain available. Standalone legacy aggregate/filter helpers may retain their historical contracts; Agent multi-stage text investigation should use `tracecite_run` to remain SourceVersion-bound and keep intermediate results outside model context.

## Schema version

`RESULT_SCHEMA_VERSION` remains `1` because `too_broad`, compact SourceVersion metadata, and the new public SessionSourceView aliases are additive/transport-compatible changes on the refactor branch. Consumers that validate a hard-coded status enum must update that enum before adopting this branch.
