---
name: tracecite
description: Use TraceCite as bounded evidence transport. TraceCite retrieves line-addressable evidence; the Agent owns interpretation, causal proof, sufficiency, and stopping.
compatibility: Requires the TraceCite Pi extension and tracecite_search/tracecite_expand tools.
---

# TraceCite diagnosis contract

Build the **smallest supported causal proof**. Correctness beats completeness. Never turn missing evidence into a plausible lifecycle story.

## First decision: classify the artifact before forming a mechanism

Before the first retrieval, classify the supplied evidence as one of:

- `stack_only`: goroutine/thread stack dump without independent lock-owner metadata, event history, or source text proving acquire-to-release scope;
- `ownership_capable`: supplied evidence independently exposes current ownership or a complete acquire-to-release interval;
- `event_capable`: supplied evidence contains chronology sufficient to tie lifecycle events to the same observed attempt/object.

This classification constrains the rest of the investigation. Do not silently upgrade it using remembered source code, runtime implementation knowledge, pointer values, user-described symptoms, or plausible system behavior.

### Mandatory stack-only state machine

If the artifact is `stack_only`, use this exact reasoning state machine:

1. Retrieve one representative blocked path and, only if needed, one structurally distinct competing path that identifies the affected subsystem or opposite acquisition order.
2. Treat every lock-acquisition frame as `waits X`, never `holds X`.
3. Ask separately whether **independent supplied evidence** exposes the current holder or an acquire-to-release interval, and whether the supplied stacks directly expose two structurally distinct opposite nested lock-acquisition paths. If holder evidence is absent, set `holder_edge = bounded_unknown` immediately; this does not erase directly observed structural lock-order evidence.
4. Once `holder_edge = bounded_unknown`, retrieval for holder identity, starvation, lifecycle causality, or current-owner reconstruction is finished. To test a structural lock-order mechanism, retrieve at most one representative for each opposite acquisition path; do not search equivalent waiters to manufacture certainty.
5. Finalize with the strongest supported statement. If two opposite nested acquisition paths are directly materialized, you may report the structural lock-order inversion/cyclic-wait mechanism while explicitly leaving current holder identity unknown. Otherwise report only observed blocking/contention. The supplied artifact never licenses naming an unseen holder.

For `stack_only`, a final that affirmatively names a holder, current ownership, starvation direction, hidden writer/reader state, or a specific waiter as holder is invalid unless independent supplied evidence establishes that claim. A structural lock-order inversion/cyclic-wait mechanism is different from current-holder identity: it may be reported only when two independent observed stack paths directly materialize opposite nested acquisition order.

### Reciprocal component-lock test

Do not confuse **same-lock queue shape** with **reciprocal lock-order structure**.

- Reader and writer waiters on the same lock are one contention fact, not two opposing paths.
- Two opposite structural paths require two different blocked acquisition sites associated with two distinct synchronization domains/components, with the higher-level call structure reversed across the two observed stacks. Abstractly: one observed stack is `component A operation -> component B lock acquisition`, while another is `component B operation -> component A lock acquisition`.
- The reciprocal relationship must come from the materialized stack frames themselves. Do not invent an outer lock hold, receiver identity, or source-code acquire/release scope that is not present in supplied evidence.
- When this reciprocal pattern is directly materialized, report it as a **structural lock-order inversion / cyclic-wait risk or mechanism supported by the observed stacks**, while keeping current holder identity unknown unless ownership-capable evidence exists.
- Prefer testing this reciprocal discriminator over counting additional waiters, discussing RWMutex fairness, or explaining downstream symptoms. Once both reciprocal paths are materialized, stop retrieval.
- If the second reciprocal path is not directly observed within the bounded search, do not substitute reader/writer mix on one lock; downgrade to observed contention.

## Mandatory protocol

These rules override narrative quality and scorer coverage.

1. Before each TraceCite call identify internally one `claim` and one `discriminator`. If either is missing, answer now.
2. Prioritize causal closure over symptom census. After finding a representative blocker, retrieve only evidence that can prove or falsify the unresolved causal edge or structurally distinct opposing acquisition path. Do not count equivalent waiters or chase downstream symptoms while the mechanism is unresolved.
3. Make TraceCite calls serially. Target total calls `<= 8`; absolute transport ceiling: 16 evidence calls. A result reporting total calls >= 16 is terminal; the next action must be the final answer.
4. Treat lock acquisition frames conservatively:
   - `blocked at acquire(X)` proves only `waits X`;
   - multiple goroutines waiting on the same lock prove contention, not the identity or state of the current holder;
   - simultaneous reader and writer waiters on the same `RWMutex` do **not** prove that a writer currently holds it, that readers are starving writers, that writers are starving readers, or that a lock cycle exists;
   - a caller/deeper frame or source position after `acquire(Y)` does not prove `holds Y`;
   - for stack-only artifacts, deeper stack frames never establish current ownership of an outer lock by themselves. Source-code memory, remembered implementation order, line-number ordering, and synchronization-library semantics are not supplied evidence;
   - printed pointer-like stack arguments are not reliable lock/object identity by default. Do not infer that two waits target the same object, that one object is globally shared/singleton, or that a pointer denotes a specific lock/receiver unless the evidence transport provides identity provenance.
5. Separate **current-holder proof** from **structural lock-order proof**:
   - a definitive claim that a particular current deadlock edge is `holds A -> waits B` requires independent current-ownership evidence;
   - a structural lock-order inversion/cyclic-wait mechanism may be reported from `stack_only` evidence only when two independent observed stacks directly materialize opposite nested acquisition paths `A -> acquire(B)` and `B -> acquire(A)`;
   - reader-vs-writer waits on one synchronization object do not satisfy the two-path rule; the two paths must be reciprocal across distinct synchronization domains/components;
   - structural-path evidence never identifies the current holder and never allows converting either waiter into a holder. If only one direction is observed, report blocking/contention and mark the opposing path unknown.
6. A lock being unavailable implies only that acquisition cannot proceed at that instant. Do not infer which goroutine holds it, whether the holder is a reader or writer, whether the holder is itself blocked, or whether starvation/fairness behavior explains the wait.
7. Stop at the artifact boundary. External process creation, RPC completion, retries, cleanup/reaping, restart recovery, and helper-goroutine identity require independent evidence tying them to the observed attempt. User-described symptoms are hypotheses, not evidence.
8. Once the directly supported mechanism is closed—or the remaining causal discriminator is bounded unknown—answer immediately.

## Terminal safety rule

**Stopping does not upgrade evidence.** At the terminal result, classify every material causal claim as one of:

```text
observed | supported_inference | bounded_unknown | contradicted
```

If a root-cause edge is still `bounded_unknown`, the final must downgrade every consequence that depends on that missing edge to the strongest supported statement. Do not call an unsupported stronger hypothesis “the root cause”, “the opposing direction”, “the cycle”, “the deadlock”, “the starvation”, or “the reason”. A structural lock-order statement is allowed only under the two-observed-path rule above.

If the evidence shows only waiters and no independently established current holder, the final must state that the **current holder is not established by the supplied artifact**. A large waiter population is severity evidence, not current-holder evidence.

Do not replace an unknown holder with phrases such as “a holder exists”, “is being held for a long time”, “never released”, “most plausibly”, “consistent with a hidden writer”, “classic starvation”, or “some sibling must be holding it” and then continue causally. Those are still unsupported holder stories.

## Lifecycle hard boundary

The final must not explain shim/runc/process creation, request completion, retry accumulation, cleanup/reaping, termination progress, or restart recovery unless the supplied evidence independently ties that lifecycle fact to the observed attempt.

A user-reported symptom may be repeated only as context, never converted into evidence by phrases such as “this explains”, “therefore”, “which is why”, “matches the symptom”, or “exactly causing” unless independent artifact evidence closes that causal link.

Do not write a lifecycle story and then add a caveat. Delete the story first. When lifecycle is outside the artifact, use one sentence and stop: “The supplied evidence supports the in-process blocking pattern, but does not establish the downstream process/RPC/restart lifecycle.”

## Final deletion gate

Immediately before emitting the final, delete any sentence that does any of the following without independent supplied evidence:

- converts a waiter into a holder or states that an unseen holder “must” exist in a particular state/path;
- says a lock “is being held for a long time”, “is never released”, or equivalent when the artifact shows only waiters;
- infers current ownership from a past acquire, caller frame, deeper frame, later source line, remembered source implementation, or lock-library semantics;
- names an unobserved holder or current opposing holder edge;
- promotes an unobserved sibling function/path into the mechanism merely because remembered code says it uses the same lock;
- equates lock/object identity, singleton/shared cardinality, or receiver identity from raw stack pointers without reliable provenance;
- infers holder identity/state from waiter counts, queue ordering, reader/writer mix, or RWMutex fairness behavior;
- treats reader/writer waits on one lock as the two reciprocal paths required for structural lock-order proof;
- claims a structural lock-order inversion/cyclic-wait mechanism without two independent observed opposite nested acquisition paths;
- links a helper goroutine/process to the blocked request by name or temporal proximity alone;
- explains downstream process/RPC/retry/restart/cleanup/reaping behavior;
- uses a user-reported symptom to complete causality.

A caveat later in the answer does not repair an unsupported earlier claim: remove the claim. If deleting a missing-edge claim also removes support for a downstream consequence, delete that consequence too; do not preserve it as a “likely” lifecycle narrative.

## Retrieval bounds

- `tracecite_search`: `max_evidence <= 12`
- `tracecite_expand`: normally `radius <= 16`
- target total calls `<= 8`; absolute ceiling `16`
- after one representative blocker is found, use at most four additional evidence calls to locate a structurally distinct opposing path; if those calls do not advance that discriminator, mark it `bounded_unknown` and finalize
- while testing structural lock order, search for a reciprocal component-acquisition path rather than another waiter on the first lock
- after observing `component A operation -> component B operation/acquire(B)`, the next structural search must target a **B-side operation that reaches an A-side acquisition site**; do not keep searching B's lock address, B's generic lock routine, or more callers ending at the same `acquire(B)`. Hits ending at the already-known acquisition site are non-advancing for the reciprocal-path discriminator
- after two non-advancing calls for the same claim, mark it `bounded_unknown`
- no confirmation pass for an already closed claim
- no equivalent-waiter census
- no symptom sweep after the causal discriminator is bounded unknown
- if a stack-only artifact lacks owner metadata or source text, do not spend calls trying to prove current ownership from more equivalent stack occurrences; mark the owner edge `bounded_unknown`

## Final answer shape

Keep the answer compact and normal:

1. strongest supported subsystem/blocking or structural lock-order statement;
2. minimum exact evidence for representative observed blocking path(s), including both opposite acquisition paths when the structural cycle is supported;
3. explicitly identify current holder identity or any missing opposing path as unknown;
4. direct impact visible in the artifact only;
5. one artifact-boundary sentence if downstream lifecycle is not established.

For `stack_only`, write the bounded conclusion first. If two reciprocal component-acquisition paths are observed, state that structural inversion first and then immediately state that current holders are unknown. Do not replace that reciprocal mechanism with a same-lock reader/writer convoy narrative. Do not include a speculative “most likely synchronization failure” section after acknowledging that ownership is unknown.

If the exact root cause is not closed, say so. A precise bounded conclusion is a successful outcome; an unsupported complete story is not.

## Runtime boundary

TraceCite Runtime may handle evidence identity, ranges, source generations, novelty, coverage, diversity, repetition, call limits, and other mechanical transport/selection concerns. Runtime must remain diagnosis-neutral: it does not know hypotheses, causality, proof claims, root cause, sufficiency, or stopping.
