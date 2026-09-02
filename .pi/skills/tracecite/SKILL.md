---
name: tracecite
description: Use TraceCite as bounded evidence transport and mechanical evidence memory. TraceCite retrieves/materializes evidence with provenance; the Agent owns interpretation, causality, sufficiency, root cause, and stopping.
compatibility: Requires the TraceCite Pi extension. tracecite_search/tracecite_expand may be exposed as compatibility aliases for retrieval/materialization.
---

# Hard rule: normalize blocking evidence before diagnosis

For blocking, contention, deadlock, queueing, or synchronization questions, DO NOT name the mechanism until representative stacks have been normalized into causal facts.

For each representative path record internally:

```text
waits: resource being acquired at the blocked operation
holds: only resources proven acquired before that blocked operation
basis: exact stack/source evidence for waits and holds
```

An execution stopped at `Lock`, `RLock`, semaphore acquire, condition wait, channel send/receive, or equivalent **WAITS for that resource**. It does NOT hold that resource merely because the acquisition frame is present.

This is a hard consistency invariant:

```text
blocked at acquire(X) -> waits X
blocked at acquire(X) -/-> holds X
```

If a proposed explanation labels an acquisition waiter as the holder of that same resource, the explanation is contradicted. Correct the proof state before any further retrieval. Do not continue building a story on that interpretation.

A hold may be `supported_inference` when supplied evidence establishes progression past the acquisition into a later nested blocked call. Use phase contrast when available:

```text
path/stack A stops at acquire(X)
path/stack B is already past acquire(X) and is blocked in a nested call
=> B supports: holds X while waiting on the nested resource
```

The two observations may come from different representative stacks of the same execution path/function phase. Do not search indefinitely for a literal `held=true` frame after this ordering is established.

For a candidate cycle, reduce the mechanism to explicit normalized edges before prose:

```text
path A: holds A -> waits B   [basis]
path B: holds B -> waits A   [basis]
impact: requested operation is blocked by the cycle   [basis]
```

A deadlock/lock-order inversion is closed only when both opposing edges are `observed` or `supported_inference`. One waiter, many waiters, a hotspot, or a writer queue is not a cycle. A waiting `RLock` is not an `RLock` holder.

# Evidence boundary

TraceCite retrieves and materializes supplied evidence. The Agent interprets it.

When the investigation is limited to supplied artifacts, model memory, guessed source code, likely fixes, guessed struct layout, pointer arithmetic, web knowledge, or unstated lifecycle behavior are NOT evidence. They cannot close a claim.

Do not treat:

```text
model memory          == supplied evidence
search match          == causal proof
frequency/rank        == causal importance
file/line order       == global happens-before
nearby pointer values == same object/field identity
absence of holder     == holder exited/vanished
```

A remembered implementation detail may suggest a query only when supplied evidence exposes a concrete discriminator. Do not narrate unseen code or hidden cleanup/process/kernel behavior as fact.

# Monotonic Causal Proof Ledger

Track only the minimum claims needed to answer the user's question. Typical roles are `mechanism`, `causal_edge`, and `direct_impact`.

Statuses:

```text
unresolved
observed
supported_inference
contradicted
bounded_unknown
```

`observed` and `supported_inference` CLOSE a claim. A closed claim MUST NOT reopen for reassurance, confidence, completeness, a new hint, or a desire for stronger/direct historical observation. Reopen only when newly materialized supplied evidence materially contradicts it.

Claim identity is semantic, not query wording. `holder`, `lock owner`, `active writer`, and synonymous searches for the same missing causal fact are the same claim.

# Claim-driven TraceCite use

Every TraceCite call MUST either:
- target one `unresolved`/`contradicted` material claim; or
- materialize a known range required to settle that claim.

If no such claim exists, do not call TraceCite.

For one claim:

```text
1. Search for the strongest discriminator.
2. Materialize the minimum representative body/context.
3. Normalize waits/holds or compare competing phases when relevant.
4. Update the claim.
5. Stop querying it when observed, supported_inference, or bounded_unknown.
```

Prefer one strongest representative instance per causal role. More equivalent waiters, stacks, counts, adjacent ranges, synonyms, rare hints, or structural clusters do not strengthen a closed claim and do not create a new claim.

After two consecutive non-advancing attempts for the SAME semantic claim, stop reformulating it. Mark `bounded_unknown` or qualify the conclusion.

Reuse known evidence refs/ranges/source identities. `no_match`, `no_new_evidence`, matched-existing evidence, duplicate requests, and covered ranges are mechanical facts; do not refetch them for confidence.

# Mechanism first; downstream symptoms are subordinate

For root-cause questions, close claims in this order:

```text
mechanism / causal edges
-> direct impact visible in supplied evidence
-> optional downstream consequence only if directly linked by supplied evidence
```

A symptom stated in the user prompt is context to explain, not evidence proving its internal mechanism.

Once mechanism and direct impact are closed, do not start a secondary census of shims, FIFOs, waits, loggers, syscalls, retries, processes, cleanup, restart behavior, or other co-occurring symptoms merely to make the story complete.

A downstream causal claim requires a continuous supplied-evidence link: a direct call/causal path, explicit identity correlation, or supplied source/context establishing the transition. Co-occurrence, duration, count, or a generic long-lived waiter is insufficient. Do not reclassify normal-looking wait/watch goroutines as pathological without differentiating evidence.

If the artifact shows an operation blocked before completion but cannot represent a later external process/lifecycle state, close the direct impact at that boundary and qualify the downstream consequence without more retrieval.

# Stop and final answer

Stop when every material claim required for the answer is `observed`, `supported_inference`, or `bounded_unknown`, with no unresolved material contradiction.

When true, the NEXT assistant action MUST be the final answer. No verification turn, reassurance search, broader census, or new investigation is allowed.

Saying or concluding `enough`, `complete picture`, `confirmed`, `crystal clear`, `ready to answer`, or equivalent is a terminal commitment. Do not attach or follow it with another tool call unless newly materialized evidence has contradicted a closed material claim.

Every material causal statement in the final answer MUST be a closed proof claim:

```text
observed            -> state as fact
supported_inference -> state as inference/conclusion
bounded_unknown     -> qualify explicitly
unresolved          -> do not present as established
contradicted        -> resolve or qualify
```

Final causal claims MUST be a subset of closed proof claims. Do not add new lifecycle, cleanup, restart, kernel, hidden ownership, process-management, timing-default, or fix stories while writing the answer.

For root-cause questions, lead with one compact sentence naming the mechanism/class and affected subsystem, then give the minimum normalized causal chain and direct impact.

# Runtime boundary

TraceCite Runtime may remember evidence identities, ranges, source generations, novelty, coverage, diversity, and repetition. It does not know hypotheses, causality, proof claims, root cause, sufficiency, or stopping.
