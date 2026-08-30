---
name: tracecite
description: Use TraceCite as an evidence-retrieval tool for large or repetitive local text/log sources. Understand how to act on search, expand, replay, novelty, correlation constraints, and scoped identity signals without treating retrieval metadata as causal conclusions.
compatibility: Requires the tracecite_search and tracecite_expand tools from the TraceCite Pi extension.
---

# TraceCite Evidence Retrieval

TraceCite retrieves and materializes evidence. You remain responsible for hypotheses, investigation order, causal reasoning, conclusions, and when to stop.

The goal is not to maximize TraceCite calls. Choose the cheapest retrieval path that preserves enough exact evidence for sound reasoning.

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

Avoid broad native output when a bounded evidence query would answer the same question with substantially less context.

For a large evidence file, broad `grep`, `awk`, `sed`, `head`, `tail`, or a large `read` used to discover evidence locations is **content retrieval**, not metadata. Prefer TraceCite for that discovery when TraceCite can express the query. Native tools remain appropriate for metadata, aggregation, structural transforms, narrow independent verification, and fallback when TraceCite itself fails.

## Search syntax

`tracecite_search` uses literal matching unless `regex=true`.

- For a plain word or exact phrase, leave `regex` false or omit it.
- If the query contains regex operators such as `|`, `.*`, `+`, `?`, `[]`, `()`, `^`, or `$`, set `regex=true`.
- Do not send a regex-looking pattern while leaving `regex` false; TraceCite will search for that pattern literally.

## Normal workflow

1. Orient with cheap metadata if needed.
2. Use `tracecite_search` for bounded evidence discovery.
3. Read the result in this order: `status` -> evidence refs -> `coverage`/`progress` -> `correlation_constraints` -> `missing_evidence`.
4. Act on identity-safety signals before correlating events across entities or scopes.
5. Use `tracecite_expand` for exact line-addressable context needed to support a claim.
6. Continue the investigation according to your own hypotheses and evidence needs.
7. If old exact evidence must be reconsidered, replay it instead of rediscovering it.

## How to interpret search results

### `new_evidence` and repeated evidence

`new_evidence=0` means this retrieval exposed no new evidence in the current session. It does not mean the investigation is complete.

If the needed evidence was already seen:

- reuse its existing ref;
- use `tracecite_expand` for exact context;
- use `replay=true` when intentionally re-reading already exposed text;
- do not run a near-synonym search merely to retrieve the same evidence again.

For the same immutable source/version, do not repeat the exact same search query with the same regex mode merely to see the same evidence again. Use the existing ref, expand it, or replay it.

Run another search only when the evidence target materially changes, for example to a different entity, identifier, time region, error class, state transition, source region, or hypothesis-specific observation.

### `no_match`

`no_match` means the query found no matching evidence. It is not proof that an event never happened.

Before changing tools, check whether the query was too narrow, used the wrong identifier, targeted the wrong source region, or accidentally used regex syntax without `regex=true`. Do not turn a retrieval miss into a causal conclusion.

### high fanout or truncated evidence

If a search has many matches, repeated sibling events, `scope_fanout_observed=true`, or truncated evidence, do not simply increase output size or dump all matches with native `grep`.

Instead, use stable identities already present in evidence to narrow the next retrieval to the relevant entity or safe identity scope.

## Correlation and identity-safety protocol

`correlation_constraints` are not decorative metadata. They tell you whether an identifier is safe to use by itself when associating evidence.

For each returned constraint, inspect these fields when present:

- `identifier_key`
- `identifier_value`
- `identifier_only_correlation_safe`
- `minimum_safe_correlation_key`
- `sibling_entity_count_observed`
- `scope_fanout_observed`
- `source_uniqueness`
- `scoped_entities`
- `observed_sibling_entities`

### If `identifier_only_correlation_safe=true`

The observed evidence supports using that identifier alone for correlation within the represented source evidence. This is still an identity fact, not a root-cause conclusion.

### If `identifier_only_correlation_safe=false`

Do **not** correlate events by that identifier alone.

Perform this sequence:

1. Read `minimum_safe_correlation_key` and identify every field required for safe correlation.
2. Inspect `scoped_entities`, `observed_sibling_entities`, `sibling_entity_count_observed`, and `scope_fanout_observed` to see which competing identities are mechanically visible.
3. Treat each different scope/entity plus identifier as a different identity until evidence proves otherwise.
4. Narrow subsequent searches using the required scope/entity plus the identifier, rather than searching the ambiguous identifier globally again.
5. Materialize representative exact evidence for the relevant competing scopes with `tracecite_expand`.
6. Compare ownership, state transitions, or event effects across those safely distinguished entities only if that comparison is relevant to your hypothesis.
7. Decide yourself whether the identity ambiguity contributes to the failure. TraceCite only establishes that identifier-only correlation is unsafe.

Generic example: if an identifier such as `device42` appears under multiple resources and `minimum_safe_correlation_key` requires `[scoped_entity, device_id]`, treat `resource-A/device42` and `resource-B/device42` as distinct identities. Do not merge their events merely because `device42` matches.

### If `scope_fanout_observed=true`

The search crossed multiple sibling scopes/entities. This is a warning against treating all matches as one timeline.

Use the safe correlation key and the returned `observed_sibling_entities` to separate evidence by entity before reasoning about sequence, ownership, health, state, or causality. If the returned sibling list is truncated, use a narrower TraceCite query for the relevant entity family before falling back to broad native content retrieval.

### If `source_uniqueness` is present

Use it only as an observed uniqueness property of the current source/version. Do not generalize it beyond the represented evidence unless exact evidence supports that broader claim.

## Evidence refs and exact context

A compact search preview is for discovery. It is not a substitute for exact context when making a material factual claim.

When a hit matters:

1. keep its evidence ref;
2. use `tracecite_expand` around the relevant line;
3. cite the exact materialized lines;
4. do not immediately fetch the same range again with native `read` or `grep`.

If overlapping context has already been exposed, TraceCite may return only unseen ranges. That is expected. Use replay only when you intentionally need the old text again.

## Avoid duplicate retrieval paths

After TraceCite has exposed evidence, do not fetch the same text again with native `grep` or `read` unless there is a concrete reason.

Good reasons include:

- independent verification of an important observation;
- a transformation, aggregation, count, or structural query TraceCite cannot express;
- resolving a retrieval gap more directly with a native tool.

Keep native verification narrow. Large duplicate outputs increase context without adding evidence.

Before using native content retrieval after TraceCite, ask: **am I obtaining new information, or only re-fetching evidence already present in the session?** If it is only a re-fetch, reuse the ref, expand, or replay instead.

## Evidence semantics

- A search hit is an observation, not proof of causality.
- Correlation constraints describe identity safety, not root cause.
- `observed_sibling_entities` are mechanically observed sibling identities and source references, not proof that they share the ambiguous identifier.
- `observed_relations` describe literal textual or structural co-observation, not root cause.
- `source_sha256`, when present, identifies the source version associated with the evidence and can be reused for exact expansion/replay.
- Replayed text is old evidence being re-read; it is not new evidence.
- Missing evidence is a retrieval fact. Do not invent a deeper cause when support is absent.

## Exact claims

Use exact line numbers from materialized evidence for material factual claims. Search previews are for discovery; use `tracecite_expand` or a narrow native read when the full supporting text has not yet been materialized.

## Efficient investigation pattern

A healthy large-source investigation usually looks like:

`cheap metadata -> bounded search -> inspect novelty + identity safety -> identity-scoped search if needed -> targeted expand -> reasoning -> materially new retrieval only when needed`

Avoid this pattern:

`broad grep/read -> TraceCite search -> duplicate native read -> near-synonym search -> repeated evidence -> another broad grep`.
