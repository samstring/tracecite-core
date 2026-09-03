---
name: tracecite
description: Use TraceCite as bounded evidence transport. TraceCite retrieves line-addressable evidence; the Agent owns interpretation, causal proof, sufficiency, and stopping.
compatibility: Requires the TraceCite Pi extension and tracecite_search/tracecite_expand tools.
---

# TraceCite investigation contract

Build the **smallest supported causal proof**. Correctness beats completeness. TraceCite transports evidence; it never supplies hidden ownership, lifecycle, or causal facts.

## 1. Classify the artifact first

Before retrieval classify the supplied artifact:

- `stack_only`: stacks without independent owner metadata, event history, or source text proving acquire-to-release scope;
- `ownership_capable`: evidence independently exposes current ownership or a complete acquire-to-release interval;
- `event_capable`: chronology ties lifecycle events to the same observed attempt/object.

Never upgrade this classification from remembered code, line-number order, pointer values, runtime semantics, user symptoms, or plausibility. Source-code control flow remembered by the model is not supplied evidence.

## 2. Stack-only proof rules

For `stack_only` evidence:

- `blocked at acquire(X)` proves only `waits X`; it never proves `holds X`.
- A deeper/caller frame, later source line, waiter count, reader/writer mix, fairness rule, or raw pointer does not prove current ownership.
- Raw pointer-like arguments do not establish object identity, singleton/global cardinality, or that two waits target the same lock unless TraceCite exposes reliable identity provenance.
- Current holder identity remains `bounded_unknown` unless independent supplied evidence establishes it.
- Same-lock reader/writer waiters are contention, not an opposing lock path, deadlock, starvation, or root-cause proof.
- A stack location proves only execution is currently parked at that location. It does not prove what earlier code already spawned, created, retained, retried, cleaned up, or will recover.

### Reciprocal structural discriminator

A structural lock-order inversion may be reported only when two **observed stack paths** directly show reversed component nesting across two distinct synchronization domains, abstractly:

`A operation -> B-side acquisition path`

and

`B operation -> A-side acquisition path`.

This supports only the **structural inversion / cyclic-wait mechanism**. It does not identify current holders. If only one direction is observed, downgrade to observed blocking/contention.

Once a path crosses from component A into component B, the next useful search is for the reverse B-to-A nesting. Prefer distinct component/frame names and call-chain structure over addresses or waiter counts. Do not spend calls proving that many equivalent waiters exist.

If reciprocal paths are directly observed, that structural relation is the strongest mechanism to report. Do not replace it with a weaker same-lock convoy/contention story.

## 3. Bounded retrieval

Before every TraceCite call identify one unresolved claim and one discriminator. If the next call cannot change the conclusion, stop.

- Make calls serially.
- Target `<= 8` total evidence calls; absolute Runtime transport ceiling is 16.
- After one representative blocker, use at most four additional calls to find a structurally distinct reciprocal path.
- After two non-advancing calls for the same discriminator, mark it `bounded_unknown` and finalize.
- No confirmation pass for a closed claim.
- No equivalent-waiter census.
- No symptom sweep after the causal discriminator is closed or bounded unknown.
- If the Runtime reports the evidence-call ceiling, the next action is the final answer. Stopping never upgrades evidence.

## 4. Lifecycle boundary

External process creation, shim/runc state, RPC completion, retries, cleanup/reaping, termination progress, or restart recovery require independent event-capable evidence tied to the observed attempt.

For `stack_only`, **code-position reasoning is not event evidence**. Never say that reaching stack frame/line N means a child process "has already been spawned", a request "will retry", an orphan "is left behind", or restart "releases/clears/recovers" anything unless those lifecycle events are independently present in the supplied artifact.

User-described symptoms are context only. Do not convert them into evidence with phrases such as “this explains”, “therefore”, “which is why”, “matches the symptom”, “exactly causing”, or equivalent causal wording.

When lifecycle is outside the artifact, use exactly one boundary sentence:

“The supplied evidence supports the in-process blocking pattern, but does not establish the downstream process/RPC/restart lifecycle.”

Do not write a lifecycle story and then add this caveat.

## 5. Terminal claim discipline

At finalization classify each material claim internally as:

`observed | supported_inference | bounded_unknown | contradicted`.

Delete every sentence whose causal premise is `bounded_unknown`.

### Mandatory final reconstruction barrier

Do **not** turn the exploratory reasoning into the final answer by editing or caveating it. Before emitting the final, discard the narrative draft and reconstruct the answer **from the allowed claim ledger only**. Any claim not on the allowed ledger is omitted, even if it sounds likely or is known from source-code memory.

For a `stack_only` artifact, the allowed final ledger is restricted to:

1. observed blocked/waiting stack paths and affected in-process call paths;
2. a structural reciprocal lock-order statement **only if both reversed component paths were directly observed**;
3. explicit statement that current holder identity is not established;
4. direct impact visible in the artifact, such as many requests/goroutines parked in the observed in-process path;
5. the single lifecycle-boundary sentence above.

No sixth claim class is allowed unless stronger supplied evidence changes the artifact classification.

Do **not** add narrative beyond those classes. In particular, do not assert or imply:

- “the holder exists”, “is held”, “held for a long time”, “never released”, “hidden writer/reader”, “classic starvation”, or a specific holder path;
- that pointer equality proves one shared/global/singleton object or lock;
- that a waiter currently owns an outer lock;
- deadlock/starvation/current cyclic wait when only structural inversion is proven;
- process/shim/runc spawn state, orphaning, retry accumulation, cleanup/reaping, or restart recovery;
- lifecycle facts inferred only from source-line position or remembered code ordering.

A later caveat does not repair an earlier unsupported assertion. Remove the assertion and all downstream consequences that depend on it.

## 6. Final answer shape

Keep the answer compact and normal. For `stack_only`, use only:

1. strongest supported in-process mechanism;
2. minimum exact evidence for the representative path(s);
3. holder/ownership uncertainty explicitly stated;
4. direct artifact-visible impact only;
5. lifecycle-boundary sentence if needed.

If reciprocal paths are observed, say “the stacks support a structural lock-order inversion between A and B; current holders are not established by this artifact.” Do not replace that with a same-lock reader/writer convoy story.

If reciprocal paths are not observed, say only that the observed path is blocked/contended and the exact root cause remains unclosed. A bounded conclusion is a successful result; an unsupported complete story is not.

Before sending, perform a literal deletion scan for lifecycle verbs and ownership words. If `stack_only`, delete any sentence that claims spawn/start/retry/orphan/reap/restart/recover/cleanup, or held/holder/starvation/deadlock, unless that exact claim is independently supported by the supplied artifact under the rules above.

## Runtime boundary

TraceCite Runtime may handle evidence identity, ranges, source generations, novelty, coverage, diversity, repetition, call limits, and other mechanical transport/selection concerns. Runtime must remain diagnosis-neutral: it does not know hypotheses, causality, proof claims, root cause, sufficiency, or stopping.
