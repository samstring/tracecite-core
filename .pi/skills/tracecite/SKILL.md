---
name: tracecite
description: Use TraceCite through its canonical Evidence Runtime operations. The Pi adapter exposes retrieve, materialize, replay, aggregate, traverse, and verify while preserving provenance, coverage, immutable source identity, RetrievalSession novelty, correlation safety, and Host-owned full-tool telemetry. TraceCite never chooses hypotheses, causal conclusions, evidence sufficiency, or stopping.
compatibility: Requires the TraceCite Pi extension. Canonical Pi tools are tracecite_retrieve, tracecite_materialize, tracecite_replay, tracecite_aggregate, tracecite_traverse, and tracecite_verify. tracecite_search/tracecite_expand remain compatibility aliases only.
---

# TraceCite Evidence Runtime in Pi

TraceCite supplies evidence mechanics. The Agent remains responsible for hypotheses, investigation order, causal reasoning, conclusions, evidence sufficiency, and when to stop.

The Pi adapter exposes the complete canonical Evidence Runtime surface. Adapter names are a Host mapping, not a second Core API.

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
- do not attempt to bypass the controlled arm with shell pipelines, `grep`, `cat`, or native `read`;
- the requirement applies only to the evidence-operation channel;
- the Agent still chooses the hypothesis, query, entity, range, traversal seed, reasoning, sufficiency judgment, conclusion, and stopping point.

This makes the benchmark a capability comparison, not a tool-adoption test.

## Convergence discipline

TraceCite exposes mechanical novelty, raw-evidence frontier progress, and bounded Host checkpoints so the Agent can avoid wasting investigation steps. These signals do not choose a root cause or decide stopping for the Agent.

Before making a follow-up evidence call, keep one explicit unresolved question in mind and know what materially different evidence the next call is expected to add. Do not continue merely because another synonym, nearby keyword, aggregate, or replay can be tried.

Treat these as low-novelty or non-frontier signals:

- `status=no_match`;
- `status=no_new_evidence`;
- `coverage.new_evidence=0` with repeated evidence;
- a materialization that exposes no unseen range or new text;
- repeated `aggregate`, `replay`, or `verify` calls that derive or revisit information without expanding raw source-evidence coverage;
- Host `agent_feedback.convergence_checkpoint.triggered=true`.

The Host may trigger a checkpoint after repeated low-novelty operations, a burst of non-frontier analysis, or a long TraceCite investigation. When that happens, the next TraceCite evidence operation requires an `investigation_goal`.

A valid `investigation_goal` should state both:

1. the exact unresolved question that still matters to the task; and
2. the materially different evidence expected from the next call.

Do not use generic goals such as "look for more evidence", "confirm the hypothesis", or a paraphrase of the previous search. A new goal should target a genuinely different source, component, entity, time region, error signature, relation, or unseen range.

When the Host convergence checkpoint is triggered, reassess before another evidence operation:

1. State the strongest conclusion currently supported by observed evidence.
2. Identify the exact unresolved question that still matters to the task.
3. Decide whether the supplied inputs actually contain the evidence class needed to resolve it.
4. Continue only if the next operation targets a materially different evidence frontier or a necessary derived check.
5. Do not continue by merely paraphrasing the same query, repeatedly materializing already-covered context, or chaining aggregates that do not change the evidence boundary.
6. If the required deeper evidence is not present in the supplied inputs, stop that line of investigation and state the evidence boundary explicitly.

A search miss is not the same as evidence insufficiency. One miss may justify a different retrieval strategy. Repeated low-novelty operations across the relevant source/component/time region are evidence that the current investigation direction is exhausted, not proof that the hypothesized event never happened.

The Agent still owns the decision to continue, switch hypotheses, answer, or declare insufficient evidence. The Host checkpoint only exposes recent evidence progress and requires deliberate reassessment.

## `tracecite_retrieve`

`tracecite_retrieve` performs caller-selected evidence retrieval.

- With `query`, it performs QueryTarget retrieval; literal matching is default unless `regex=true`.
- Without `query`, it performs SourceTarget inspection.
- A match is an observation, not proof of causality.
- `no_match` is a retrieval fact, not proof that an event never happened.
- `new_evidence=0` means the operation exposed no new Evidence identity in the current RetrievalSession.
- `matched_existing_evidence` identifies previously delivered Evidence matched by the current request without pretending it is new.

Use exact refs and returned source SHA-256 for later materialization/replay.

## Source line ordering

Returned refs and ranges such as `L123-L140` describe positions in the captured source output.

- Within the same source file, a lower line number only means that line appears earlier in that file's output than a higher line number.
- Line order is output order, not event-time order, execution order, happens-before, causal order, lock order, or proof that one action occurred before another.
- Use line numbers to navigate, revisit, and compare nearby output context.
- Do not infer a relationship merely because two ranges are close together or appear in a particular file order.
- If the evidence itself provides timestamps, sequence numbers, trace/span IDs, thread/goroutine context, or another explicit ordering signal, the Agent may reason from those observed fields separately.

## `tracecite_materialize`

`tracecite_materialize` materializes exact bounded context around a caller-selected line/range.

- `radius` is bounded to `0..30`; use multiple deliberate ranges rather than requesting a larger invalid radius.
- It preserves immutable source identity when a SHA-256 is supplied.
- Previously covered immutable context may be suppressed rather than returned as fake new evidence.
- Materialized text is evidence; any interpretation of that text remains the Agent's responsibility.

## `tracecite_replay`

`tracecite_replay` intentionally re-reads context already covered by the same immutable RetrievalSession.

- SHA-256 is required.
- Replay does not create new evidence or expand the raw evidence frontier.
- Use replay when reconsidering old text rather than repeating searches and treating old output as new discovery.

## `tracecite_aggregate`

`tracecite_aggregate` performs bounded deterministic `count`, `distinct`, or `group` operations over caller-selected local text matches.

- It returns mechanical values and source provenance.
- It does not rank groups by causal importance.
- It derives information from supplied evidence but does not expand raw source-evidence coverage by itself.
- Do not chain aggregates merely to keep investigating after the relevant raw evidence is already covered.
- For `group`, the Agent supplies the grouping regex.

## `tracecite_traverse`

`tracecite_traverse` runs bounded deterministic provider traversal over caller-selected evidence IDs/entities.

- The Pi bridge accepts a provider-shaped JSON fixture (`name`, `evidence[]`, optional `relations[]`) so the canonical provider traversal is genuinely executable from Pi.
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

The Pi extension observes actual Host tool calls and records categories such as:

- canonical TraceCite tools -> `tracecite_evidence`;
- `grep` / `find` -> `native_search`;
- `read` -> `native_read`;
- `bash` -> `opaque_shell`;
- `ls` -> `native_other`.

Host activity is trajectory telemetry only. It is not evidence sufficiency or a stop recommendation.

## Evidence support boundary

Evaluation may distinguish:

- `supported`;
- `inference_supported`;
- `unsupported_from_log`.

If a claim is an inference, qualify it. If supplied evidence does not establish a deeper cause or fix, state that boundary rather than presenting outside knowledge as observed fact.

When a deeper upstream cause or corrective fix would require source code, internal component logs, telemetry, or another artifact that is not present, say so directly instead of repeatedly searching the same supplied evidence for confirmation that cannot exist there.

## What TraceCite does not decide

TraceCite does not decide:

- which hypothesis to form;
- which query, source, entity, range, or traversal seed to choose;
- which sibling is important;
- whether identity ambiguity is causal;
- what the root cause is;
- whether evidence is sufficient;
- what final answer to give;
- when to stop.

Those decisions remain with the Agent, including in the forced TraceCite A/B arm.
