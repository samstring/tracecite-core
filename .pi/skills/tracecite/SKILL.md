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

1. Retrieve one representative blocked path and, only if needed, one distinct competing/waiting path that identifies the affected subsystem.
2. Treat every lock-acquisition frame as `waits X`, never `holds X`.
3. Ask whether **independent supplied evidence** exposes the current holder or an acquire-to-release interval. If not, set `holder_edge = bounded_unknown` immediately.
4. Once `holder_edge = bounded_unknown`, retrieval for lock ownership, starvation, cycle, or lifecycle causality is finished. Do not search equivalent waiters to manufacture certainty.
5. Finalize with the strongest observed blocking/contention statement. The exact root cause is **not established by the supplied artifact**.

For `stack_only`, a final that affirmatively names a holder, current ownership, deadlock, cycle, lock-order inversion, starvation direction, hidden writer/reader state, or exact synchronization root cause is invalid unless independent supplied evidence establishes that claim.

## Mandatory protocol

These rules override narrative quality and scorer coverage.

1. Before each TraceCite call identify internally one `claim` and one `discriminator`. If either is missing, answer now.
2. Prioritize causal closure over symptom census. After finding a representative blocker, retrieve only evidence that can prove or falsify the unresolved causal edge. Do not count equivalent waiters or chase downstream symptoms while the mechanism is unresolved.
3. Make TraceCite calls serially. Target total calls `<= 8`; absolute transport ceiling: 16 evidence calls. A result reporting total calls >= 16 is terminal; the next action must be the final answer.
4. Treat lock acquisition frames conservatively:
   - `blocked at acquire(X)` proves only `waits X`;
   - multiple goroutines waiting on the same lock prove contention, not the identity or state of the current holder;
   - simultaneous reader and writer waiters on the same `RWMutex` do **not** prove that a writer currently holds it, that readers are starving writers, that writers are starving readers, or that a lock cycle exists;
   - a caller/deeper frame or source position after `acquire(Y)` does not prove `holds Y`;
   - for stack-only artifacts, deeper stack frames never establish current ownership of an outer lock by themselves. Source-code memory, remembered implementation order, line-number ordering, and synchronization-library semantics are not supplied evidence;
   - printed pointer-like stack arguments are not reliable lock/object identity by default. Do not infer that two waits target the same object, that one object is globally shared/singleton, or that a pointer denotes a specific lock/receiver unless the evidence transport provides identity provenance.
5. Deadlock/cycle/lock-order inversion requires two independently supported **current** edges: `holds A -> waits B` and `holds B -> waits A`. If either holder edge is missing, report only observed blocking/contention and mark the missing causal edge unknown.
6. A lock being unavailable implies only that acquisition cannot proceed at that instant. Do not infer which goroutine holds it, whether the holder is a reader or writer, whether the holder is itself blocked, or whether starvation/fairness behavior explains the wait.
7. Stop at the artifact boundary. External process creation, RPC completion, retries, cleanup/reaping, restart recovery, and helper-goroutine identity require independent evidence tying them to the observed attempt. User-described symptoms are hypotheses, not evidence.
8. Once the directly supported mechanism is closed—or the remaining causal discriminator is bounded unknown—answer immediately.

## Terminal safety rule

**Stopping does not upgrade evidence.** At the terminal result, classify every material causal claim as one of:

```text
observed | supported_inference | bounded_unknown | contradicted
```

If a root-cause edge is still `bounded_unknown`, the final must downgrade to the strongest supported statement. Do not call the stronger hypothesis “the root cause”, “the opposing direction”, “the cycle”, “the deadlock”, “the starvation”, or “the reason”.

If the evidence shows only waiters and no independently established current holder, the final must state that the **holder and exact root cause are not established by the supplied artifact**. A large waiter population is severity evidence, not causal closure.

Do not replace an unknown holder with phrases such as “a holder exists”, “most plausibly”, “consistent with a hidden writer”, “classic starvation”, or “some sibling must be holding it” and then continue causally. Those are still unsupported holder stories.

## Lifecycle hard boundary

The final must not explain shim/runc/process creation, request completion, retry accumulation, cleanup/reaping, termination progress, or restart recovery unless the supplied evidence independently ties that lifecycle fact to the observed attempt.

A user-reported symptom may be repeated only as context, never converted into evidence by phrases such as “this explains”, “therefore”, “which is why”, “matches the symptom”, or “exactly causing” unless independent artifact evidence closes that causal link.

Do not write a lifecycle story and then add a caveat. Delete the story first. When lifecycle is outside the artifact, use one sentence and stop: “The supplied evidence supports the in-process blocking pattern, but does not establish the downstream process/RPC/restart lifecycle.”

## Final deletion gate

Immediately before emitting the final, delete any sentence that does any of the following without independent supplied evidence:

- converts a waiter into a holder or states that an unseen holder “must” exist in a particular state/path;
- infers current ownership from a past acquire, caller frame, deeper frame, later source line, remembered source implementation, or lock-library semantics;
- names an unobserved holder or opposing causal edge;
- equates lock/object identity, singleton/shared cardinality, or receiver identity from raw stack pointers without reliable provenance;
- infers holder identity/state from waiter counts, queue ordering, reader/writer mix, or RWMutex fairness behavior;
- claims deadlock/cycle/lock-order inversion/starvation without required current ownership proof;
- links a helper goroutine/process to the blocked request by name or temporal proximity alone;
- explains downstream process/RPC/retry/restart/cleanup/reaping behavior;
- uses a user-reported symptom to complete causality.

A caveat later in the answer does not repair an unsupported earlier claim: remove the claim.

## Retrieval bounds

- `tracecite_search`: `max_evidence <= 12`
- `tracecite_expand`: normally `radius <= 16`
- target total calls `<= 8`; absolute ceiling `16`
- after two non-advancing calls for the same claim, mark it `bounded_unknown`
- no confirmation pass for an already closed claim
- no equivalent-waiter census
- no symptom sweep after the causal discriminator is bounded unknown
- if a stack-only artifact lacks owner metadata or source text, do not spend calls trying to prove ownership from more equivalent stack occurrences; mark the owner edge `bounded_unknown`

## Final answer shape

Keep the answer compact and normal:

1. strongest supported subsystem/blocking statement;
2. minimum exact evidence for representative observed blocking path(s);
3. explicitly identify missing holder/opposing edge as unknown;
4. direct impact visible in the artifact only;
5. one artifact-boundary sentence if downstream lifecycle is not established.

For `stack_only`, write the bounded conclusion first. Do not include a speculative “most likely synchronization failure” section after acknowledging that ownership is unknown.

If the exact root cause is not closed, say so. A precise bounded conclusion is a successful outcome; an unsupported complete story is not.

## Runtime boundary

TraceCite Runtime may handle evidence identity, ranges, source generations, novelty, coverage, diversity, repetition, call limits, and other mechanical transport/selection concerns. Runtime must remain diagnosis-neutral: it does not know hypotheses, causality, proof claims, root cause, sufficiency, or stopping.
