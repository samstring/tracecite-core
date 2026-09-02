---
name: tracecite
description: Use TraceCite as bounded evidence transport and mechanical evidence memory. TraceCite retrieves/materializes evidence with provenance; the Agent owns interpretation, causal proof, sufficiency, and stopping.
compatibility: Requires the TraceCite Pi extension. tracecite_search/tracecite_expand may be exposed as compatibility aliases for retrieval/materialization.
---

# Highest-priority execution contract

For diagnosis/root-cause work, build the **smallest causal proof that answers the question**. Do not perform an evidence census.

Before EVERY TraceCite call, identify internally:

```text
claim: the one unresolved/contradicted material causal fact this call targets
discriminator: the concrete result that would change that claim
```

If either cannot be named, **do not call TraceCite; answer now**.

Investigate in this order only:

```text
mechanism / required causal edges
-> direct impact visible in supplied evidence
-> requested downstream consequence only to the artifact boundary
```

Do **not** investigate downstream symptoms while mechanism edges are unresolved. Once mechanism and direct impact are closed, do not open secondary investigations merely to make the story more complete.

Keep transport bounded:

- `tracecite_search`: request at most **12** inline evidence items. Evidence Intelligence/navigation hints exist to preserve diverse candidates under this bound.
- `tracecite_expand`: normally use radius **<= 16**. Widen once only when the current material claim needs a frame cut off by the first expansion.
- Use one strongest representative instance per distinct causal role. Counts and equivalent stacks are not additional proof unless the count itself is material to the question.

Correctness outranks token saving, but more evidence volume is not more correctness.

# Monotonic causal proof ledger

Track only material claims required by the user's question.

Statuses:

```text
unresolved
observed
supported_inference
contradicted
bounded_unknown
```

`observed` and `supported_inference` CLOSE a claim. A closed claim MUST NOT reopen for reassurance, confidence, completeness, a new hint, or a desire for a more direct historical observation. Reopen only when newly materialized supplied evidence materially contradicts it.

Claim identity is semantic, not query wording. Synonyms such as `holder`, `owner`, and `active writer` do not create new claims.

A root-cause proof is complete when the minimum mechanism/causal edges and direct impact are closed, requested downstream effects have either a supported link or an explicit evidence boundary, and no material contradiction remains unresolved.

# Normalize blocking evidence before naming the mechanism

For every representative blocking path record internally:

```text
waits: resource being acquired at the blocked operation
holds: only resources proven acquired before that blocked operation
basis: exact materialized evidence supporting waits/holds
```

Hard invariant:

```text
blocked at acquire(X) -> waits X
blocked at acquire(X) -/-> holds X
```

A blocked `Lock`, `RLock`, semaphore acquire, condition wait, channel send/receive, or equivalent does not prove the waiter holds that resource.

An outer hold may close as `supported_inference` when supplied evidence establishes progression past the outer acquisition into a later nested blocked call. Compare execution phases when available:

```text
one representative stops at acquire(X)
another representative of the same path/function is already past acquire(X) and blocked deeper
=> the deeper path supports: holds X while waiting on the nested resource
```

Do not keep searching for literal `held=true` evidence after execution ordering is sufficient and uncontradicted.

For a candidate cycle, normalize explicit edges before prose:

```text
path A: holds A -> waits B   [basis]
path B: holds B -> waits A   [basis]
impact: requested operation is blocked   [basis]
```

A deadlock/lock-order inversion requires both opposing edges, each `observed` or `supported_inference`. One waiter, many waiters, a hotspot, or a writer queue is not a cycle.

# Evidence boundary

Only supplied artifacts are evidence. Model memory, guessed source code, likely fixes, guessed struct layout, pointer arithmetic, web knowledge, and unstated lifecycle behavior cannot close a claim.

Do not treat:

```text
search match          == causal proof
frequency/rank        == causal importance
file/line order       == global happens-before
nearby pointer values == same object/field identity
absence of a match    == global absence
```

Do not use numeric address proximity to establish object/field identity. Use addresses only when the same identity is directly established by supplied evidence and the identity is material to the proof.

If the supplied artifact cannot represent a requested later/external state, stop at the last supported in-artifact transition. Mark the rest `bounded_unknown` or describe only the minimal consequence that follows from the closed path as an inference. **Do not search broadly for external process state after this boundary is known.**

In-process stack evidence alone does not prove process creation state, handshake completion, reaping, orphaning, cleanup, restart behavior, or kernel lifecycle behavior.

# Claim-driven TraceCite use

For one unresolved/contradicted claim:

```text
1. Search for its strongest discriminator.
2. Materialize the minimum representative context.
3. Normalize/compare paths if needed.
4. Update the claim.
5. Stop querying it once observed, supported_inference, or bounded_unknown.
```

Do not run independent searches for multiple alternative stories before reassessing the current claim. A search may be followed by materialization of its returned coordinate for the same claim; otherwise reassess proof state first.

A new hint, rare signal, structural cluster, subsystem, long-lived goroutine, or co-occurring symptom does NOT create a new claim by itself.

After two consecutive non-advancing attempts for the SAME semantic claim, stop reformulating synonyms. Mark it `bounded_unknown` or qualify the conclusion.

Reuse known refs/ranges/source identities. `no_match`, `no_new_evidence`, matched-existing evidence, duplicate requests, and covered ranges are mechanical facts; do not refetch them for confidence.

# Stop and answer

Stop when every material claim is `observed`, `supported_inference`, or `bounded_unknown`, with no unresolved material contradiction.

When that becomes true, the **NEXT assistant action MUST be the final answer**. No verification turn, broader census, symptom sweep, or new investigation is allowed.

A statement such as `enough`, `complete picture`, `confirmed`, `ready to answer`, or equivalent is a terminal commitment. Do not follow it with another evidence call unless newly materialized evidence contradicted a closed claim.

Every material causal statement in the final answer MUST be a closed proof claim:

```text
observed            -> state as fact
supported_inference -> state as conclusion/inference
bounded_unknown     -> qualify explicitly
unresolved          -> do not present as established
contradicted        -> resolve or qualify
```

For root-cause questions, keep the answer to the proof:

1. one compact sentence naming the mechanism/class and subsystem;
2. the minimum competing causal paths/edges;
3. the direct impact and any explicit downstream evidence boundary;
4. only the strongest representative evidence citations.

Do not enumerate equivalent waiters or add cleanup, restart, kernel, hidden-ownership, process-management, timing-default, or fix stories unless they are themselves required material claims and independently closed by supplied evidence.

# Runtime boundary

TraceCite Runtime may remember evidence identities, ranges, source generations, novelty, coverage, diversity, and repetition. It does not know hypotheses, causality, proof claims, root cause, sufficiency, or stopping.
