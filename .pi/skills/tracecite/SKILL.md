---
name: tracecite
description: Use TraceCite as bounded evidence transport. TraceCite retrieves line-addressable evidence; the Agent owns interpretation, causal proof, sufficiency, and stopping.
compatibility: Requires the TraceCite Pi extension and tracecite_search/tracecite_expand tools.
---

# TraceCite diagnosis contract

Build the **smallest supported causal proof**. Correctness beats completeness. Never turn missing evidence into a plausible lifecycle story.

## Mandatory protocol

These rules override narrative quality and scorer coverage.

1. Before each TraceCite call identify internally one `claim` and one `discriminator`. If either is missing, answer now.
2. Prioritize causal closure over symptom census. After finding a representative blocker, retrieve only evidence that can prove or falsify the unresolved causal edge. Do not count equivalent waiters or chase downstream symptoms while the mechanism is unresolved.
3. Make TraceCite calls serially. Absolute transport ceiling: 16 evidence calls. A result reporting total calls >= 16 is terminal; the next action must be the final answer.
4. Treat lock acquisition frames conservatively:
   - `blocked at acquire(X)` proves only `waits X`;
   - multiple goroutines waiting on the same lock prove contention, not the identity or state of the current holder;
   - simultaneous reader and writer waiters on the same `RWMutex` do **not** prove that a writer currently holds it, that readers are starving writers, that writers are starving readers, or that a lock cycle exists;
   - a caller/deeper frame or source position after `acquire(Y)` does not prove `holds Y`;
   - **for stack-only artifacts, deeper stack frames never establish current ownership of an outer lock by themselves.** Source-code memory, remembered implementation order, and line-number ordering are not supplied evidence. Current ownership needs independent supplied evidence that exposes the acquire-to-release interval strongly enough to exclude an intervening release;
   - printed pointer-like stack arguments are not automatically lock identity. Do not equate two locks, receivers, or objects from raw stack argument values unless the artifact or transport provides reliable identity/provenance for those values.
5. Deadlock/cycle/lock-order inversion requires two independently supported **current** edges: `holds A -> waits B` and `holds B -> waits A`. If either holder edge is missing, report only the observed blocking/contention and mark the missing causal edge unknown. Never use “someone must hold the lock”, queue shape, waiter counts, pointer resemblance, source ordering, or RWMutex fairness semantics to synthesize a missing holder edge.
6. Stop at the artifact boundary. External process creation, RPC completion, retries, cleanup/reaping, restart recovery, and helper-goroutine identity require independent evidence tying them to the observed attempt. User-described symptoms are hypotheses, not evidence.
7. Once the directly supported mechanism is closed—or the remaining causal discriminator is bounded unknown—answer immediately.

## Stack-only artifact rule

When the supplied evidence is a goroutine/thread stack dump without source text, event history, or lock-owner metadata:

- report blocking locations and call paths as observed;
- do not infer that an outer lock is still held merely because the stack is currently deeper in the same function/callback;
- do not reconstruct acquire/release scopes from remembered source code or line numbers;
- do not promote apparent lock-address/object-address matches from raw stack arguments into identity proof;
- if holder identity is absent, explicitly say that the dump establishes contention/waiting but not the holder/root-cause edge, then stop.

This rule is generic and applies regardless of whether the suspected mechanism would be plausible from source knowledge.

## Terminal safety rule

**The evidence ceiling is not permission to promote an incomplete hypothesis.** At the terminal result, classify every material causal claim as one of:

```text
observed | supported_inference | bounded_unknown | contradicted
```

If a root-cause edge is still `bounded_unknown`, the final must explicitly downgrade to the strongest supported statement (for example, a blocking location or contention pattern). Do not call the stronger hypothesis “the root cause”, “the opposing direction”, “the cycle”, “the deadlock”, “the starvation”, or “the reason” merely because retrieval has stopped.

If the evidence shows only waiters and no current holder, the final must say exactly that the **holder/root cause is not established by the supplied artifact**. A large waiter population is severity evidence, not causal closure.

## Final deletion gate

Immediately before emitting the final, delete any sentence that does any of the following without independent supplied evidence:

- converts a waiter into a holder;
- infers current ownership from a past acquire, caller frame, deeper frame, later source line, or remembered source implementation;
- names an unobserved holder or opposing causal edge;
- equates lock/object identity from raw stack argument pointers without reliable identity provenance;
- infers holder identity/state from waiter counts, queue ordering, reader/writer mix, or RWMutex implementation/fairness behavior;
- claims deadlock/cycle/lock-order inversion/starvation without the required current ownership proof;
- links a helper goroutine/process to the blocked request by name or temporal proximity alone;
- explains downstream process/RPC/retry/restart/cleanup/reaping behavior;
- uses a user-reported symptom to complete causality.

A caveat later in the answer does not repair an unsupported earlier claim: remove the claim.

When lifecycle is outside the artifact, use one sentence and stop: “The supplied evidence supports the in-process blocking pattern, but does not establish the downstream process/RPC/restart lifecycle.”

## Retrieval bounds

- `tracecite_search`: `max_evidence <= 12`
- `tracecite_expand`: normally `radius <= 16`
- target total calls `<= 12`; absolute ceiling `16`
- after two non-advancing calls for the same claim, mark it `bounded_unknown`
- no confirmation pass for an already closed claim
- no equivalent-waiter census
- no symptom sweep after the causal discriminator is bounded unknown
- if a stack-only artifact lacks owner metadata or source text, do not spend calls trying to prove ownership from more equivalent stack occurrences; mark the owner edge `bounded_unknown`

## Final answer shape

Keep the answer compact and normal:

1. strongest supported mechanism/subsystem statement;
2. minimum exact evidence for the observed blocking path(s);
3. explicitly identify any missing holder/opposing edge as unknown;
4. direct impact visible in the artifact only;
5. one artifact-boundary sentence if downstream lifecycle is not established.

If the exact root cause is not closed, say so. A precise bounded conclusion is a successful outcome; an unsupported complete story is not.

## Runtime boundary

TraceCite Runtime may handle evidence identity, ranges, source generations, novelty, coverage, diversity, repetition, call limits, and other mechanical transport/selection concerns. Runtime must remain diagnosis-neutral: it does not know hypotheses, causality, proof claims, root cause, sufficiency, or stopping.
