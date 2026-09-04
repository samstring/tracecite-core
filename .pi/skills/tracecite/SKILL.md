---
name: tracecite
description: Use TraceCite through its canonical Evidence Runtime operations. The Pi adapter only maps tools and transparently transports TraceCite responses; TraceCite owns provenance, coverage, immutable source identity, RetrievalSession novelty, and the Evidence Index contract. TraceCite never chooses hypotheses, causal conclusions, evidence sufficiency, or stopping.
compatibility: Requires the TraceCite Pi extension. Canonical Pi tools are tracecite_retrieve, tracecite_materialize, tracecite_replay, tracecite_aggregate, tracecite_traverse, and tracecite_verify. tracecite_search/tracecite_expand remain compatibility aliases only.
---

# TraceCite Evidence Runtime in Pi

TraceCite supplies evidence mechanics. The Agent remains responsible for hypotheses, investigation order, causal reasoning, conclusions, evidence sufficiency, and when to stop.

The Pi adapter is transport only. It does not compact, sample, rename, remove, rank, or inject fields into TraceCite responses.

## Canonical Pi tools

```text
tracecite_retrieve      -> retrieve
tracecite_materialize   -> materialize
tracecite_replay        -> replay
tracecite_aggregate     -> aggregate
tracecite_traverse      -> traverse
tracecite_verify        -> verify
```

Compatibility aliases remain available for older callers:

```text
tracecite_search        -> retrieve(QueryTarget(...))
tracecite_expand        -> materialize(...) or replay(...)
```

New integrations and benchmarks should use the six canonical tool names.

## Controlled A/B evidence mode

Some Hosts, especially the native-vs-TraceCite A/B benchmark, intentionally require all evidence-content operations to go through TraceCite.

When the Host exposes only TraceCite Evidence tools plus file-location helpers such as `find`/`ls`:

- use TraceCite for searching, reading/materializing, replaying, counting/grouping, traversal, and integrity verification;
- do not bypass the controlled arm with shell pipelines, `grep`, `cat`, or native `read`;
- the requirement applies only to the evidence-operation channel;
- the Agent still chooses the hypothesis, query, entity, range, traversal seed, reasoning, sufficiency judgment, conclusion, and stopping point.

This makes the benchmark a capability comparison, not a tool-adoption test.

## Investigation discipline

A search miss is not the same as evidence insufficiency. One miss may justify a different retrieval strategy. Repeated low-novelty operations across the relevant source/component region are evidence that an investigation direction is exhausted, not proof that a hypothesized event never happened.

For large evidence sources, keep the Agent in control but prefer a bounded investigation loop:

1. Inspect source shape once instead of rediscovering filenames or schemas with synonyms.
2. Use retrieval to identify concrete signatures, services, trace IDs, request IDs, or line locators.
3. Once a concrete locator is available, materialize only the bounded context needed to answer the current question.
4. Prefer correlation-local evidence over unrelated confirmatory searches.
5. Treat `no_match` and `no_new_evidence` as facts about that exact request, not proof of a broader causal conclusion.
6. Stop when evidence is sufficient; do not continue merely to increase confidence.

These are Agent-side investigation choices, not Runtime planning or causal ranking.

## `tracecite_retrieve`

`tracecite_retrieve` performs caller-selected evidence retrieval.

- With `query`, it performs QueryTarget retrieval; literal matching is default unless `regex=true`.
- Without `query`, it performs SourceTarget inspection.
- A match is an observation, not proof of causality.
- `no_match` is a retrieval fact, not proof that an event never happened.
- `new_evidence=0` means the operation exposed no new Evidence identity in the current RetrievalSession.
- `matched_existing_evidence` identifies previously delivered Evidence matched by the current request without pretending it is new.
- Query searches with at most 5 matches return all matched Evidence directly.
- Query searches with more than 5 matches return `data.evidence_index` instead of an arbitrary first-N Evidence body.
- Each Evidence Index entry contains the matched `rule`, its `count`, and the complete `lines` array containing every matched source-line locator for that rule.
- Evidence Index locators are returned directly in one response. TraceCite does not sample or paginate them.
- The Evidence Index contains locators only; it does not add timestamp or semantic ranking metadata. If time or surrounding context matters, materialize the selected line and read it from the source Evidence.
- An Evidence Index is navigation, not cited Evidence. Materialize the selected source line/range before using its contents as evidence.

Use returned source SHA-256 when immutable identity is needed for later materialization/replay.

## `tracecite_materialize`

`tracecite_materialize` materializes exact bounded context around a caller-selected line/range.

- `radius` is bounded to `0..30`.
- It preserves immutable source identity when a SHA-256 is supplied.
- Previously covered immutable context may be suppressed rather than returned as fake new evidence.
- Materialized text is Evidence; interpretation remains the Agent's responsibility.

## `tracecite_replay`

`tracecite_replay` intentionally re-reads context already covered by the same immutable RetrievalSession.

- SHA-256 is required.
- Replay does not create new Evidence or expand the raw evidence frontier.
- Use replay when reconsidering old text rather than repeating searches and treating old output as new discovery.

## `tracecite_aggregate`

`tracecite_aggregate` performs deterministic `count`, `distinct`, or `group` operations over caller-selected local text matches.

- It returns mechanical values and source provenance.
- It does not rank groups by causal importance.
- It derives information from supplied evidence but does not expand raw source-evidence coverage by itself.
- For `group`, the Agent supplies the grouping regex.

## `tracecite_traverse`

`tracecite_traverse` runs bounded deterministic provider traversal over caller-selected evidence IDs/entities.

- The Agent selects seeds and limits.
- Traversal follows mechanical identity/entity relationships only; it does not choose what should be investigated next.

## `tracecite_verify`

`tracecite_verify` verifies a caller-selected evidence manifest mechanically.

- It verifies integrity/manifest facts.
- It does not validate the Agent's causal conclusion or expand source-evidence coverage.

## RetrievalSession semantics

RetrievalSession is mechanical evidence memory only. It can track:

- previously exposed Evidence identities;
- immutable covered ranges;
- bounded recent operations;
- request fingerprints;
- new/repeated/replay/no-match outcomes.

It does not contain or infer hypotheses, root cause, evidence sufficiency, or stop recommendations.

## Correlation and identity safety

Correlation constraints are evidence-identity facts, not causal claims.

If `identifier_only_correlation_safe=false`, do not collapse distinct scopes using that identifier alone. Use the returned minimum safe correlation key when the Agent chooses to correlate those records.

## Host tool activity

The Pi extension may record actual Host tool activity as side-channel telemetry in tool `details`. It does not alter the TraceCite response content delivered to the Agent.

## Evidence support boundary

Evaluation may distinguish:

- `supported`;
- `inference_supported`;
- `unsupported_from_log`.

If a claim is an inference, qualify it. If supplied evidence does not establish a deeper cause or fix, state that boundary rather than presenting outside knowledge as observed fact.

## What TraceCite does not decide

TraceCite does not decide:

- which hypothesis to form;
- which query, source, entity, range, or traversal seed to choose;
- which match is important;
- whether identity ambiguity is causal;
- what the root cause is;
- whether evidence is sufficient;
- what final answer to give;
- when to stop.

Those decisions remain with the Agent, including in the forced TraceCite A/B arm.
