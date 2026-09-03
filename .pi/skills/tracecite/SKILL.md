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
   - a caller/deeper frame or source position after `acquire(Y)` does not prove `holds Y`;
   - current ownership is supported only when supplied evidence exposes the acquire-to-release control-flow interval strongly enough to exclude an intervening release.
5. Deadlock/cycle/lock-order inversion requires two independently supported **current** edges: `holds A -> waits B` and `holds B -> waits A`. If either holder edge is missing, report only the observed blocking/contention and mark the missing causal edge unknown.
6. Stop at the artifact boundary. External process creation, RPC completion, retries, cleanup/reaping, restart recovery, and helper-goroutine identity require independent evidence tying them to the observed attempt. User-described symptoms are hypotheses, not evidence.
7. Once the directly supported mechanism is closed—or the remaining causal discriminator is bounded unknown—answer immediately.

## Terminal safety rule

**The evidence ceiling is not permission to promote an incomplete hypothesis.** At the terminal result, classify every material causal claim as one of:

```text
observed | supported_inference | bounded_unknown | contradicted
```

If a root-cause edge is still `bounded_unknown`, the final must explicitly downgrade to the strongest supported statement (for example, a blocking location or contention pattern). Do not call the stronger hypothesis “the root cause”, “the opposing direction”, “the cycle”, or “the reason” merely because retrieval has stopped.

## Final deletion gate

Immediately before emitting the final, delete any sentence that does any of the following without independent supplied evidence:

- converts a waiter into a holder;
- infers current ownership from a past acquire, caller frame, deeper frame, or later source line;
- names an unobserved holder or opposing causal edge;
- claims deadlock/cycle/lock-order inversion without both current `holds -> waits` edges;
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
