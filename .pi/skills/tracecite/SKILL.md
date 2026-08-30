---
name: tracecite
description: Use TraceCite through its canonical Evidence API semantics. The Pi adapter exposes retrieval/materialization/replay tools while preserving provenance, coverage, immutable source identity, session novelty, correlation safety, and Host-owned full-tool telemetry. TraceCite does not choose hypotheses, causal conclusions, sufficiency, or stopping.
compatibility: Requires the TraceCite Pi extension. Current adapter tools map tracecite_search to canonical retrieve and tracecite_expand to canonical materialize/replay.
---

# TraceCite Evidence Runtime in Pi

TraceCite supplies evidence mechanics. You remain responsible for hypotheses, investigation order, causal reasoning, conclusions, what to inspect next, evidence sufficiency, and when to stop.

This skill documents canonical semantics and the current Pi adapter mapping. It does not prescribe a preferred investigation workflow.

## Canonical Evidence API

The stable TraceCite public primitives are:

- `retrieve`
- `materialize`
- `replay`
- `aggregate`
- `traverse`
- `verify`

The current minimal Pi adapter exposes a subset through host-friendly tool names:

```text
tracecite_search                -> retrieve(QueryTarget(...))
tracecite_expand replay=false   -> materialize(RangeTarget(...))
tracecite_expand replay=true    -> replay(RangeTarget(...))
```

These adapter names do not define separate novelty, routing, or state semantics.

## `tracecite_search` = canonical `retrieve`

`tracecite_search` performs caller-selected text retrieval.

- Literal matching is the default unless `regex=true`.
- A match is an observation, not proof of causality.
- `no_match` is a retrieval fact, not proof that an event never happened.
- A bounded preview is not the complete source or complete causal context.
- `new_evidence=0` means the call exposed no new Evidence identity in the current RetrievalSession.
- `matched_existing_evidence` means the current query matched evidence already seen in the session; the body can remain suppressed while exact refs preserve current-query relevance.

If a query contains regex operators, set `regex=true`; otherwise the adapter searches that text literally.

## `tracecite_expand` = canonical `materialize` or `replay`

With `replay=false`, `tracecite_expand` materializes exact bounded context around a caller-selected line/range.

With `replay=true`, it intentionally re-reads context already covered by the same immutable RetrievalSession.

Replay semantics:

- source SHA-256 should be supplied when available;
- replayed text is old evidence being shown again;
- replay does not create new evidence;
- novelty remains zero.

If the purpose is simply to see already exposed text again, replay is the canonical reread mechanism rather than pretending a repeated search produced new evidence.

## Canonical operations not exposed by the minimal Pi adapter

The canonical Runtime also defines `aggregate`, `traverse`, and `verify`.

If the current Pi extension does not expose a dedicated tool for one of these operations, do not invent TraceCite results for it. Use the capabilities actually available to the Host, or call the public Python API when the Host integration supports that path.

Their semantics remain:

- `aggregate`: deterministic `count` / `distinct` / `group`, not causal ranking;
- `traverse`: caller-selected deterministic traversal, not next-target selection;
- `verify`: mechanical integrity/manifest verification, not validation of an Agent conclusion.

## RetrievalSession semantics

RetrievalSession is mechanical evidence memory only. It can track:

- previously exposed Evidence identities;
- immutable covered ranges;
- bounded recent operations;
- request fingerprints;
- new/repeated/replay/no-match outcomes.

It does not contain or infer hypotheses, root cause, evidence sufficiency, or stop recommendations.

## Correlation and identity safety

`correlation_constraints` and related fields describe safe evidence identity/correlation.

Possible fields include:

- `identifier_key`;
- `identifier_value`;
- `identifier_only_correlation_safe`;
- `minimum_safe_correlation_key`;
- `scope_fanout_observed`;
- `source_uniqueness`;
- `scoped_entities`;
- `observed_sibling_entities`.

If `identifier_only_correlation_safe=false`, do not collapse evidence from distinct scopes into one identity using that identifier alone. Use the minimum safe correlation key for any caller-selected correlation.

These fields do not say which entity is important, which sibling should be investigated, or whether identity ambiguity caused the failure.

## Routing and bounded projections

TraceCite may choose bounded transport forms using mechanical facts such as source size, output limits, seen coverage, or repeated-output ratio.

High fanout, truncation, or bounded selection are transport facts. They do not establish causal relevance.

A lossy projection must remain explicit about truncation/omission, and exact materialization/replay must remain available for reviewable source text.

## Full Pi Host Tool Activity

The TraceCite Pi extension observes actual Pi `tool_call` / `tool_result` events, including TraceCite tools and native tools such as:

- `grep` / `find` -> native search activity;
- `read` -> native read activity;
- `bash` -> native/opaque shell activity;
- TraceCite tools -> TraceCite evidence activity.

`bash` is explicitly marked `opaque`; Host telemetry must not pretend arbitrary shell activity is canonical TraceCite Evidence.

This activity ledger is Host-owned trajectory telemetry. It is not evidence sufficiency, root-cause confidence, or a stop recommendation.

## Native tools remain valid Host tools

Native tools are not forbidden. They may be used for tasks the current TraceCite adapter does not express, including structural inspection, transformations, aggregation, independent verification, or fallback when a TraceCite capability is unavailable.

Avoid treating native output as TraceCite provenance unless it actually came through a canonical Evidence operation.

## Evidence support boundary

Evaluation may distinguish:

- `supported`;
- `inference_supported`;
- `unsupported_from_log`.

If a claim is an inference, qualify it as inference. If the supplied evidence does not establish a deeper cause or fix, state that boundary instead of presenting known upstream truth as directly observed in the log.

This is an evidence-claim discipline, not a prescribed investigation path.

## Citation and provenance

For material claims based on TraceCite evidence:

- preserve exact refs and materialized line ranges;
- preserve source SHA-256 when immutable identity matters;
- distinguish replayed evidence from new evidence;
- do not treat a compact preview as more exact than the text actually returned;
- do not treat an Agent-generated conclusion as its own verification.

## What TraceCite does not decide

TraceCite and this skill do not decide:

- which hypothesis to form;
- which source/entity/query to inspect next;
- which sibling should be compared;
- whether identity ambiguity is causal;
- what the root cause is;
- whether the evidence is sufficient;
- what the final answer should be;
- when to stop.

Those decisions remain with the Agent.
