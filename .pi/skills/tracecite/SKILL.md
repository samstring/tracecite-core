---
name: tracecite
description: Use TraceCite as an evidence-retrieval tool for large or repetitive local text/log sources. Interpret search, expand, replay, novelty, correlation constraints, and scoped identity signals without treating retrieval metadata as causal conclusions.
compatibility: Requires the tracecite_search and tracecite_expand tools from the TraceCite Pi extension.
---

# TraceCite Evidence Retrieval

TraceCite retrieves and materializes evidence. You remain responsible for hypotheses, investigation order, causal reasoning, conclusions, what to investigate next, and when to stop.

This skill documents TraceCite semantics and correct tool usage. It does not prescribe an investigation strategy or choose which evidence, entity, hypothesis, or comparison should matter.

## Tool selection

| Need | Prefer |
| --- | --- |
| List files, inspect size/line count, or inspect directory structure | native `ls`, `find`, `wc` |
| Read a very small file directly | native `read` |
| Locate relevant evidence in a large or repetitive text/log source | `tracecite_search` |
| Materialize exact context around a known hit | `tracecite_expand` |
| Re-read context already exposed in this retrieval session | `tracecite_expand(..., replay=true)` |
| Compute, aggregate, transform, sort, count, or perform a structural query TraceCite does not express | native shell/tools |
| Independently verify a critical observation | narrow native `read`/`grep` when useful |

Avoid broad native output when a bounded evidence query would answer the same retrieval need with substantially less context.

For a large evidence file, broad `grep`, `awk`, `sed`, `head`, `tail`, or a large `read` used to discover evidence locations is **content retrieval**, not metadata. Prefer TraceCite for that retrieval when TraceCite can express the query. Native tools remain appropriate for metadata, aggregation, structural transforms, narrow independent verification, and fallback when TraceCite itself fails.

## Search syntax

`tracecite_search` uses literal matching unless `regex=true`.

- For a plain word or exact phrase, leave `regex` false or omit it.
- If the query contains regex operators such as `|`, `.*`, `+`, `?`, `[]`, `()`, `^`, or `$`, set `regex=true`.
- Do not send a regex-looking pattern while leaving `regex` false; TraceCite will search for that pattern literally.

## Search-result fields

When reading a `tracecite_search` result, these fields describe retrieval state rather than investigation conclusions:

- `status`: retrieval outcome for this call.
- evidence refs/previews: evidence exposed by the call.
- `coverage` / `progress`: mechanical coverage or novelty information.
- `correlation_constraints`: identity-safety information observed in the represented evidence.
- `missing_evidence`: retrieval gaps or unavailable evidence reported by the tool.

None of these fields decides which hypothesis to pursue, what to investigate next, whether a relationship is causal, or whether the investigation is complete.

## `new_evidence` and repeated evidence

`new_evidence=0` means this retrieval exposed no new evidence in the current session. It does not mean the investigation is complete.

If evidence was already exposed, TraceCite supports these mechanical reuse paths:

- reuse its existing ref;
- use `tracecite_expand` for exact context;
- use `replay=true` when intentionally re-reading already exposed text.

For the same immutable source/version, repeating the exact same search query with the same regex mode normally re-fetches the same retrieval target. If the intent is to see already exposed evidence again, use the existing ref, expand, or replay instead.

A new search should represent a materially different retrieval target. TraceCite does not decide whether that different target is useful to the investigation.

## `no_match`

`no_match` means the query found no matching evidence. It is not proof that an event never happened and is not a causal conclusion.

A `no_match` can also result from query construction, including using regex syntax without `regex=true`, using the wrong identifier, or targeting the wrong source region.

## High fanout and truncated results

Many matches, truncation, or `scope_fanout_observed=true` are retrieval-shape signals. They do not identify which matching entity matters.

If the Agent chooses to retrieve a specific entity from an ambiguous or high-fanout result, use the stable identity fields required by the returned correlation contract rather than relying on an ambiguous identifier alone. Do not interpret high fanout itself as evidence of causality.

## Correlation and identity-safety semantics

`correlation_constraints` describe whether identifiers are safe to use when associating evidence. They do not tell the Agent which entities to investigate or compare.

A constraint may include:

- `identifier_key`
- `identifier_value`
- `identifier_only_correlation_safe`
- `minimum_safe_correlation_key`
- `sibling_entity_count_observed`
- `scope_fanout_observed`
- `source_uniqueness`
- `scoped_entities`
- `observed_sibling_entities`

### `identifier_only_correlation_safe=true`

Within the represented source evidence, the observed identity information supports using that identifier by itself for correlation. This is an identity fact, not a root-cause conclusion.

### `identifier_only_correlation_safe=false`

The same identifier value must **not** be assumed to refer to the same entity across the represented evidence.

`minimum_safe_correlation_key` states which fields are required to identify an entity safely for TraceCite correlation. For example, if it is `[scoped_entity, resourceID]`, then `resourceID` alone is insufficient.

If the Agent independently decides to retrieve evidence for a particular entity, the TraceCite query must carry enough information to satisfy that safe identity key. This is a tool-usage requirement; it does not imply that the Agent should investigate that entity.

`scoped_entities` and `observed_sibling_entities` expose mechanically observed identities and evidence refs. Their presence does not mean those entities should be compared, that they participate in the same failure, or that identity ambiguity is causal.

Generic example: if `device42` appears under multiple resources and `minimum_safe_correlation_key` is `[scoped_entity, device_id]`, `resource-A/device42` and `resource-B/device42` are distinct identities for retrieval/correlation purposes unless evidence establishes otherwise. This example says nothing about whether either resource is relevant to the investigation.

### `scope_fanout_observed=true`

The returned matches span multiple sibling scopes/entities. It warns only that all matches must not be collapsed into one entity timeline solely because they share an ambiguous identifier.

If the Agent chooses to retrieve one of those entities, use the safe correlation key. TraceCite does not prescribe which sibling to select or whether any cross-sibling comparison should be performed.

### `source_uniqueness`

When present, `source_uniqueness` is an observed uniqueness property of the current source/version only. Do not generalize it beyond the represented evidence without additional evidence.

## Evidence refs and exact context

A compact search preview is a bounded discovery representation. When exact source text is needed, use the evidence ref with `tracecite_expand`.

`tracecite_expand.radius` must be between `0` and `30`, inclusive. If the Agent independently needs a wider area, materialize additional adjacent bounded ranges instead of sending a radius above the tool limit.

Mechanical ref usage:

1. keep the evidence ref returned by search;
2. expand the required exact range when needed;
3. use exact materialized lines for citations;
4. use replay when intentionally re-reading text already exposed in the session.

If overlapping context has already been exposed, TraceCite may return only unseen ranges. That is expected retrieval-session behavior.

## Duplicate retrieval paths

After TraceCite has exposed evidence, fetching the same text again with native `grep` or `read` adds duplicate context unless there is a separate tool need.

Legitimate native-tool uses include:

- independent verification of an observation;
- transformation, aggregation, counting, or structural queries TraceCite does not express;
- resolving a retrieval capability gap.

Keep native verification narrow. If the purpose is simply to see already exposed evidence again, use the existing ref, expand, or replay.

## Evidence semantics

- A search hit is an observation, not proof of causality.
- Correlation constraints describe identity safety, not root cause.
- `observed_sibling_entities` are mechanically observed sibling identities and source references; they do not prescribe investigation or comparison.
- `observed_relations` describe literal textual or structural co-observation, not root cause.
- `source_sha256`, when present, identifies the source version associated with the evidence and can be reused for exact expansion/replay.
- Replayed text is old evidence being re-read; it is not new evidence.
- Missing evidence is a retrieval fact, not a deeper causal explanation.

## Boundary: what TraceCite does not decide

TraceCite and this skill do **not** decide:

- which sibling/entity the Agent should investigate next;
- whether two entities should be compared;
- which hypothesis is more important;
- whether an observed identity collision contributes to the failure;
- what the root cause is;
- whether enough evidence has been collected;
- when the Agent should stop.

Those decisions remain with the Agent.
