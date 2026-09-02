---
name: tracecite
description: Use TraceCite as bounded evidence transport and mechanical evidence memory. TraceCite retrieves/materializes evidence with provenance; the Agent owns interpretation, causality, sufficiency, root cause, and stopping.
compatibility: Requires the TraceCite Pi extension. tracecite_search/tracecite_expand may be exposed as compatibility aliases for retrieval/materialization.
---

# TraceCite role

```text
TraceCite = retrieve + materialize + provenance + mechanical evidence memory
Agent     = interpret + infer + maintain proof state + decide sufficiency + stop
```

Runtime never chooses hypotheses, causal importance, root cause, investigation direction, or stopping. Token saving never overrides correctness.

Every TraceCite call MUST target one material causal claim whose status is `unresolved` or `contradicted`, or materialize an already-identified range needed to settle that claim. Claim identity is semantic, not query wording. If no such claim exists, do not call TraceCite.

# Monotonic Causal Proof Ledger

Track only the smallest set of material claims needed to answer the user's question. Typical roles are `mechanism`, `causal_edge`, and `impact`.

Each claim has one status:

```text
unresolved
observed
supported_inference
contradicted
bounded_unknown
```

`observed` and `supported_inference` both CLOSE a claim. A closed claim MUST NOT return to `unresolved` merely for reassurance, confidence, completeness, a new hint, or a desire for direct historical observation. Reopen it only when newly materialized evidence materially contradicts the claim.

A root-cause proof is sufficient when the minimum mechanism/causal edges and impact needed by the user's question are closed and no material contradiction remains unresolved.

# Supported inference and phase contrast

A claim may close as `supported_inference` when observed execution paths, ordering, source/context, or state transitions establish the claim strongly enough for the requested conclusion and no observed evidence contradicts it.

For snapshot stacks, use **phase contrast** before searching for an invisible holder or historical state. Two representative stacks can prove ordering even when neither prints `held=true`:

```text
same function / same acquisition phase:
  stack A stops at acquisition of resource X
  stack B has progressed past that acquisition into a nested call and is blocked there

=> stack B is evidence that the acquisition succeeded before the nested block.
```

When the acquisition boundary and later nested phase are established by the supplied stack/source context, the corresponding outer hold may CLOSE as `supported_inference`. Do not continue searching for a direct holder merely because the snapshot cannot display historical ownership explicitly. A paired phase contrast is causal evidence; evidence need not come from a single stack.

Do not require direct observation of historical or latent state when sufficient execution-order evidence already supports it. Conversely, do not infer ownership from a waiter alone.

Do not treat:

```text
not visible now      == never happened
present in call path == currently held/active
file/line order      == global happens-before/event time
search match         == causal proof
frequency/rank       == causal importance
nearby pointer values == same object/field identity
```

Raw-address proximity or guessed struct layout is not proof of resource identity unless supplied evidence/source context establishes that mapping.

State an inferred conclusion as inference/conclusion rather than pretending it was directly observed.

# Claim-driven evidence acquisition

For one `unresolved` or `contradicted` claim:

```text
1. Search for the strongest discriminating anchor.
2. Materialize only the minimum body/context needed.
3. Compare execution phases/competing paths when the claim is about ordering or ownership.
4. Update the claim status.
5. Stop querying that claim once it is observed, supported_inference, or bounded_unknown.
```

Use one strongest representative evidence instance per distinct causal role. More equivalent matches, waiters, stacks, counts, adjacent ranges, or synonyms do not strengthen a closed claim.

A new TraceCite hint, rare signal, structural cluster, or interesting subsystem does NOT create a new claim by itself. Evidence Intelligence improves candidate visibility; it does not expand the user's required proof.

If two consecutive attempts for the SAME unresolved claim produce no discriminating information, stop reformulating synonyms for that claim. Mark it `bounded_unknown`, or keep the final conclusion qualified if that claim is material.

# Synchronization

For blocking/contention/deadlock claims:

- waiting at `Lock`, `RLock`, semaphore acquire, condition wait, channel receive/send, or equivalent does NOT mean that resource is held;
- an outer hold may close as `supported_inference` when phase contrast or source/context establishes progression past the outer acquisition into a nested blocked call;
- a lock-order cycle requires both opposing wait-for edges, each `observed` or `supported_inference`.

For a candidate cycle, explicitly reduce the proof to:

```text
path A: holds A -> waits B
path B: holds B -> waits A
impact: requested operation blocked by the cycle
```

One blocked lock, one edge, a hotspot, or many waiters is not a deadlock proof. Once both required opposing edges and the impact are closed, do not search for more holders or equivalent stacks unless new evidence contradicts an edge.

# Artifact boundary and downstream impact

Prove only the part of the causal chain represented by the supplied artifact. If the artifact directly shows an operation blocked before completion but cannot directly represent an external process's later state, close the observed impact at that boundary and qualify the downstream consequence.

Do not open new claims merely to reconstruct hidden lifecycle, process, cleanup, kernel, or I/O behavior outside the artifact. Do not census unrelated shim/logger/fifo/syscall stacks just to make a downstream story sound complete.

# Evidence correctness and token discipline

- In TraceCite-only mode, do not retry blocked native evidence tools.
- Reuse known evidence refs, ranges, source paths, source SHAs, and immutable source identities.
- Search previews may omit multi-line bodies; materialize only the bounded body needed for a material claim.
- Navigation hints are coordinates, not causal evidence.
- `status=no_match` is request-local, not global absence.
- `status=no_new_evidence`, matched-existing evidence, duplicate requests, and covered ranges are mechanical facts; do not refetch them for confidence.
- If materialization is empty/already covered, do not repeatedly retry adjacent lines, radius changes, or synonymous searches. Use one alternate concrete coordinate only when newly observed output provides it and the same unresolved claim still needs it.
- Absence of a directly visible holder is not evidence that the holder exited, vanished, or was omitted from the dump.
- Cite exact materialized lines for material factual claims.

# Stop and final answer

Stop when every material claim required to answer the user's question is `observed`, `supported_inference`, or `bounded_unknown`, and no material contradiction remains unresolved.

When this condition becomes true, the NEXT assistant action MUST be the final answer. No verification turn, reassurance search, broader census, or new investigation is allowed before answering.

Every material causal statement in the final answer MUST correspond to a closed claim in the Causal Proof Ledger:

```text
observed            -> state as fact
supported_inference -> state as conclusion/inference
bounded_unknown     -> qualify explicitly
unresolved          -> do not present as established
contradicted        -> resolve or qualify before answering
```

Final causal claims MUST be a subset of closed proof claims. Do not introduce new causal, lifecycle, cleanup, restart, kernel, hidden ownership, or process-management stories while writing the final answer.

For root-cause questions, lead with one compact sentence naming the failure mechanism/class and affected subsystem/component, then give only the minimum causal chain and impact needed to support it.

# RetrievalSession boundary

RetrievalSession may remember evidence identities, ranges, request fingerprints, source generations, novelty, coverage, and repeated evidence. It does not know hypotheses, causality, importance, proof claims, root cause, sufficiency, or stopping.

# Controlled TraceCite-only mode

A Host may expose only TraceCite evidence operations. This changes the evidence channel, not the reasoning owner.

# Agent loop

```text
1. Define the minimum material causal claims.
2. Pick one unresolved/contradicted claim.
3. Retrieve only evidence that can change that claim.
4. Materialize the minimum representative stacks/context.
5. Use competing-path or phase contrast to close inferable ordering/ownership.
6. Close it as observed/supported_inference, contradict it, or bound it.
7. Never reopen a closed claim without material contradictory evidence.
8. When all required claims are closed, answer immediately.
9. Write only closed proof claims into the final causal story.
```

TraceCite makes evidence recoverable, bounded, line-addressable, provenance-preserving, diverse, and mechanically non-redundant. The Agent maintains the causal proof and decides when it is complete.
