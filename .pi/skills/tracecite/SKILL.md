---
name: tracecite
description: Use TraceCite as bounded evidence transport and mechanical evidence memory. TraceCite retrieves/materializes evidence with provenance; the Agent owns interpretation, causal proof, sufficiency, and stopping.
compatibility: Requires the TraceCite Pi extension. tracecite_search/tracecite_expand may be exposed as compatibility aliases for retrieval/materialization.
---

# Highest-priority execution contract

For diagnosis/root-cause work, build the **smallest causal proof that answers the question**. Do not perform an evidence census.

**Non-negotiable proof compression:** a representative blocked at `acquire(X)` may only support `waits X`; it must never be relabeled as a holder/owner of X in the final answer. Once one representative closes each required causal role, exclude equivalent waiters from both further investigation and final prose. In-process stack/FIFO/ttrpc presence cannot support external process lifecycle, restart, cleanup, reaping, or orphan claims; omit those claims rather than complete the story speculatively.

**Role-admission hard gate:** a final causal role must be justified by the representative's own blocking state. If a representative, or every member of a cited group, is stopped in `acquire(X)` / `lockSlow(X)`, that evidence may only be described as `waits X` / queued on X. It cannot establish that "another worker" in that same group holds X. If holder identity is not independently materialized, keep the identity `bounded_unknown`; never fill it by exclusivity reasoning such as "only one can be inside" or "there must be a holder".

**Mechanism-first transport budget:** the first evidence call must target a mechanism discriminator, not a downstream symptom, unless the symptom itself is the mechanism. Hard transport limits are `tracecite_search max_evidence <= 12` and `tracecite_expand radius <= 16`. Use no more than **16 evidence calls** for one investigation by default. At that boundary, do not broaden: make at most one final targeted call for an unresolved material contradiction; otherwise answer with `bounded_unknown` where needed. Once two opposing mechanism edges and the direct impact are closed, downstream symptom/lifecycle searches are prohibited unless the supplied artifact already contains a direct causal bridge requiring materialization.

**Two-resource mechanism closure:** when supplied evidence shows blocking on two nested synchronization resources, do not collapse the diagnosis to a one-lock contention/starvation theory until both possible directions have been normalized. For each resource, distinguish (a) a representative stopped at its acquisition from (b) a representative of the same execution path already past that acquisition and blocked deeper. Only (b), backed by supplied evidence that the earlier acquisition precedes the deeper block, may support `holds X -> waits Y`. A blocked `RLock` does not prove a writer currently holds the RWMutex; it proves only that the reader waits there. Before naming deadlock/cycle, require two supported opposing hold/wait edges. Before naming mere contention/starvation instead, explicitly verify that no supplied representative closes the missing opposing edge. Do not use model-known lock semantics or source ordering that was not supplied as evidence to manufacture either conclusion.

**Artifact-boundary final answer:** every sentence about a process/shim/child, an RPC being sent or not sent, retry behavior, restart recovery, cleanup, reaping, or an external lifecycle stage must have its own supplied-artifact basis. If it does not, delete that sentence. A correct answer may stop at the in-process blocked task/start path even when the field symptom mentions an external process.

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

**Stack-frame orientation is not acquisition order.** In stack dumps, the currently blocked acquisition is commonly printed above its callers. The blocked acquire frame identifies the resource being **waited on**; caller frames below it do not mean those callers acquire later. Derive lock order only from execution-phase evidence that proves a resource was acquired before entry into the later blocked operation.

Therefore, when a path has progressed past acquisition of A and is now blocked in a nested `acquire(B)`, normalize it as `holds A -> waits B` even if the textual stack prints `acquire(B)` above the A-owning caller. Never downgrade two proven opposing hold/wait edges to mere contention, starvation, or head-of-line blocking because the stack text visually lists functions or locks in a similar order.

A goroutine blocked acquiring X must not be named as the current holder/owner of X. If the literal holder identity is not observable, keep that identity `bounded_unknown`; path-level execution-phase evidence may still establish a hold/wait edge without identifying the exact owner goroutine.

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

A deadlock/lock-order inversion requires both opposing edges, each `observed` or `supported_inference`. One waiter, many waiters, a hotspot, a writer queue, or two groups waiting on the same mutex is not a cycle.

**Mandatory cycle audit before naming deadlock / lock-order inversion:**

```text
EDGE 1: holder of A (or execution-phase proof of holding A) -> blocked acquiring B
EDGE 2: holder of B (or execution-phase proof of holding B) -> blocked acquiring A
```

Both rows must have a concrete supplied-evidence basis. A waiter on A cannot serve as proof that A is held by that waiter. Multiple goroutines blocked on B do not establish `holds B -> waits A`. If one opposing edge is missing, do **not** call the mechanism a deadlock or lock-order inversion; describe only the supported contention/bottleneck and mark the missing edge `bounded_unknown`.

**Self-contradiction check:** for an ordinary non-reentrant lock, one representative path cannot simultaneously be normalized as `waits X` and `holds X` merely because the blocked `acquire(X)` appears inside a function that also uses X. If the current blocking operation is `acquire(X)`, that representative is a waiter on X. A different, deeper representative may support a path-level prior hold only if execution-phase evidence establishes that it progressed beyond the outer acquisition before blocking on another resource. Cite the deeper representative for that inference; never cite the outer waiter as the holder.

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

In-process stack evidence alone does not prove process creation state, handshake completion, reply/registration completion, process reaping, orphaning, cleanup, restart behavior, kernel lifecycle behavior, or that an external process is at a specific lifecycle stage merely because related containerd goroutines/FIFO/ttrpc frames are present.

**Final-answer lifecycle audit:** do not state any of the following as fact unless the supplied artifact directly represents that state or a closed causal claim establishes it:

```text
process/shim was already forked or started
process is stuck at runc init / a specific external stage
containerd did or did not receive a reply/registration
restart clears the lock/state and therefore recovers
cleanup/reaping/termination is blocked or will occur
```

If such a downstream story would be useful but is not represented, say the snapshot only proves the in-process blocking boundary and stop there.

# Pre-final semantic gate

Before emitting the final answer, audit the proposed prose itself, not just the search history. This gate is mandatory and requires **no additional TraceCite call**.

1. **Mechanism gate.** If the draft says `deadlock`, `cycle`, `lock inversion`, or an equivalent cyclic mechanism, verify that the proof ledger contains two opposing `holds -> waits` edges with separate concrete bases. If either edge is absent, downgrade the mechanism wording before answering.
2. **Holder-language gate.** Scan every material use of `holds`, `holder`, `owns`, or equivalent. If its cited basis is a stack blocked acquiring that same resource, delete or rewrite that holder claim. A waiter is not a holder.
3. **Phase-inference gate.** When a hold is inferred from execution phases rather than directly observed, state it as a path-level inference and cite the representative that is already past the outer acquisition and blocked deeper. Do not identify an exact holder goroutine unless that identity is independently supported.
4. **Object-identity gate.** Delete any ownership/field conclusion derived only from numeric pointer adjacency, address offsets, or guessed struct layout.
5. **Lifecycle gate.** Scan the draft for process creation/start, external-stage location, reply/registration, orphaning, restart recovery, cleanup, reaping, and termination claims. If the supplied artifact does not directly represent that state and the claim is not independently closed, **remove the claim from the final answer** rather than turning it into a confident narrative.
6. **Impact gate.** State only the direct blocked operation/path visible in the supplied artifact. Do not extend it into unobserved external lifecycle consequences merely because they are plausible.
7. **Role-admission gate.** If the cited representative or cited group is blocked at `acquire(X)` / `lockSlow(X)`, the draft may say only that it waits/queues on X. Delete any sentence that promotes that waiter/group into a holder/owner of X or invents an uncited "other worker" as the holder.

If this audit removes part of the story, that is acceptable. A shorter bounded answer is more correct than a complete-sounding unsupported one.

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
