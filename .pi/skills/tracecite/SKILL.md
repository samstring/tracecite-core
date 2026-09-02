---
name: tracecite
description: Use TraceCite as bounded evidence transport and mechanical evidence memory. TraceCite retrieves evidence with provenance; the Agent owns interpretation, causal proof, sufficiency, and stopping.
compatibility: Requires the TraceCite Pi extension and tracecite_search/tracecite_expand tools.
---

# TraceCite diagnosis contract

For root-cause work, build the **smallest causal proof that answers the question**. Do not perform an evidence census. TraceCite is evidence transport, not a diagnosis engine.

## Highest-priority semantic invariants

These rules override any desire to produce a complete story.

1. **A waiter is never a holder.**
   - `blocked at acquire(X)` / `lockSlow(X)` / `RLock(X)` => `waits X` only.
   - That stack cannot establish that the same goroutine, its group, or an unnamed "other worker" holds X.
   - Multiple waiters on X do not prove a holder identity or a reverse causal edge.

2. **Deadlock/cycle requires two independently supported opposing edges.** Before saying `deadlock`, `cycle`, `lock-order inversion`, or equivalent, the final proof must contain:

   ```text
   EDGE A: holds A -> waits B   [concrete supplied-evidence basis]
   EDGE B: holds B -> waits A   [concrete supplied-evidence basis]
   ```

   A hold may be a path-level inference only when supplied evidence establishes both that execution passed acquisition of the outer resource **and that the resource is still held at the observed blocking point**. Merely seeing an acquisition earlier in the same function/call path, or seeing the caller still active below the current frame, proves progress through the path but not current ownership. If the supplied artifact does not establish the lock scope/release ordering needed for `still held`, classify the hold as `bounded_unknown` instead of promoting it into a causal edge. If either opposing edge is missing, do **not** invent the holder or infer it from exclusivity; describe only the supported contention/blocking and mark the missing edge `bounded_unknown`.

3. **Do not use lock exclusivity as evidence of holder identity.** Statements such as "only one worker can be inside, therefore another worker holds the mutex" are forbidden unless a supplied representative actually shows the holder path and current ownership at the blocking point.

4. **Blocked `RLock` proves a reader is waiting, not that a writer is proven to hold the RWMutex.** Likewise, a queued writer does not by itself prove which reader/writer holds the lock.

5. **An active caller frame is not ownership proof.** Stack call-chain order may show that function A called function B and B is currently blocked. It does not by itself prove that any lock acquired somewhere in A remains held across B. Do not turn source-line position, remembered implementation details, or an assumed `defer Unlock` into a current-hold claim unless that acquire/hold/release relationship is represented in the supplied evidence.

6. **Do not manufacture object identity.** Nearby pointer values, address offsets, guessed struct layout, or model-known source code cannot establish that two locks/fields belong to the same object. Only supplied evidence may establish identity.

7. **Stay inside the artifact lifecycle boundary.** In-process stack/FIFO/ttrpc presence does not by itself prove that a shim/process was forked, where an external process is stuck, whether an RPC/reply/registration completed, whether cleanup/reaping is blocked, or why restart recovers. If the supplied artifact does not directly represent that state, omit it or state the boundary explicitly. Symptom text in the question is context to explain, not evidence that a proposed internal mechanism caused each lifecycle step.

## Mandatory final-answer proof filter

Immediately before emitting the final answer, rewrite the draft through this filter **without making another TraceCite call**:

```text
For every material sentence:
- What exact supplied evidence supports it?
- Is it observation, supported inference, or bounded_unknown?
- Does it promote a waiter into a holder?
- Does it infer an unnamed holder from "someone must hold it"?
- Does a claimed hold prove CURRENT ownership at the blocking point, rather than only earlier acquisition/path progress?
- Does it assume an active caller frame means a lock from that caller is still held?
- Does it claim a cycle without two concrete opposing current holds->waits edges?
- Does it extend an in-process stack or symptom wording into external lifecycle/restart/cleanup behavior?
```

If any answer is unsafe, delete or qualify that sentence. A shorter bounded answer is preferred over a complete-sounding unsupported narrative.

**Special cycle output rule:** if one opposing edge is not independently supported, the final answer must literally avoid the words `deadlock`, `cycle`, and `lock-order inversion` as the established mechanism. It may say the evidence shows blocking/contention and that the reverse ownership edge is not established.

**Special lifecycle output rule:** when the artifact is an in-process snapshot and external lifecycle state is not directly represented, do not explain why restart helps or assert process/RPC/cleanup states as facts. End with one boundary sentence instead of completing the story from general knowledge.

## Minimum causal proof ledger

Track only claims required by the user's question using:

```text
unresolved
observed
supported_inference
contradicted
bounded_unknown
```

`observed` and `supported_inference` close a claim. Do not reopen a closed claim for reassurance, confidence, completeness, or duplicate evidence. Reopen only if newly materialized supplied evidence materially contradicts it.

For every blocking representative normalize internally:

```text
waits: resource at the blocking acquisition
holds: only resources proven still held at this blocking point
basis: exact supplied evidence for both acquisition and continued ownership
```

Hard invariants:

```text
blocked at acquire(X) -> waits X
blocked at acquire(X) -/-> holds X
passed acquire(Y) -/-> currently holds Y
```

Stack textual order is not acquisition order, and path progress is not ownership scope. An outer hold can close only when supplied evidence proves that the acquisition dominates the observed block and release has not occurred before that point.

## Bounded retrieval

Before every TraceCite call identify internally:

```text
claim: the single unresolved or contradicted material fact
discriminator: the concrete result that would change that claim
```

If either cannot be named, do not call TraceCite; answer.

Investigate only in this order:

```text
mechanism / required causal edges
-> direct impact visible in supplied evidence
-> requested downstream consequence only to the artifact boundary
```

Transport limits for one investigation:

- `tracecite_search`: `max_evidence <= 12`
- `tracecite_expand`: normally `radius <= 16`
- default total evidence-call budget: **16 calls**
- after two consecutive non-advancing attempts for the same claim, mark it `bounded_unknown` instead of reformulating synonyms
- one strongest representative per distinct causal role; equivalent waiters are not additional proof

At the default call boundary, make at most one final targeted call only if it can resolve a material contradiction. Otherwise answer with bounded uncertainty.

## Stop rule

The proof is complete when all material claims are `observed`, `supported_inference`, or `bounded_unknown`, and no material contradiction remains unresolved.

When that becomes true, the **next assistant action must be the final answer**. No confirmatory search, census, symptom sweep, or lifecycle completion is allowed.

A statement such as `enough`, `confirmed`, `complete picture`, or `ready to answer` is a terminal commitment. Do not make another evidence call after it unless newly returned evidence contradicted a closed claim.

For root-cause answers, keep the final response to:

1. one compact mechanism/subsystem statement;
2. the minimum supported causal paths/edges;
3. the direct impact visible in supplied evidence;
4. an explicit evidence boundary for unsupported downstream lifecycle;
5. only the strongest representative citations.

Do not enumerate equivalent waiters or add restart, cleanup, process-management, hidden-owner, or fix stories unless those claims are independently established by supplied evidence.

# Runtime boundary

TraceCite Runtime may handle evidence identities, ranges, source generations, novelty, coverage, diversity, repetition, and mechanical selection. Runtime must remain diagnosis-neutral: it does not know hypotheses, causality, proof claims, root cause, sufficiency, or stopping.
