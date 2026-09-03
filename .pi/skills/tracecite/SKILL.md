---
name: tracecite
description: Use TraceCite as bounded evidence transport. TraceCite retrieves line-addressable evidence; the Agent owns interpretation, causal proof, sufficiency, and stopping.
compatibility: Requires the TraceCite Pi extension and tracecite_search/tracecite_expand tools.
---

# TraceCite investigation contract

Build the **smallest supported causal proof**. Correctness beats completeness. TraceCite transports evidence; it never supplies hidden ownership, lifecycle, or causal facts.

## Non-negotiable evidence firewall

These rules override the user's request for a complete causal story. If the supplied artifact cannot prove a requested causal/lifecycle step, say that it is not established and omit the story. Never satisfy a requested explanation by filling evidence gaps from model memory, source-code plausibility, runtime semantics, symptoms, pointer values, or likely control flow.

For a stack-only artifact, before writing the final answer ask only:

1. What blocked paths are directly visible?
2. Are two reversed cross-component acquisition paths directly visible?
3. Is current ownership independently visible?
4. Is lifecycle chronology independently visible?

If (3) is no, no waiter may be called a holder and no phrase may imply it currently owns an outer lock. If (4) is no, do not explain spawn, retry, orphaning, cleanup, reaping, restart, or recovery.

## 1. Classify the artifact first

Classify supplied evidence before retrieval:

- `stack_only`: stacks without independent owner metadata, event history, or source text proving an acquire-to-release interval;
- `ownership_capable`: evidence independently exposes current ownership or a complete acquire-to-release interval;
- `event_capable`: chronology ties lifecycle events to the same observed attempt/object.

Never upgrade classification from remembered code, line-number order, pointer values, runtime semantics, user symptoms, or plausibility.

## 2. Stack-only semantics

For `stack_only`:

- `blocked at acquire(X)` proves only `waits X`; it never proves `holds X`.
- A deeper/caller frame, later source line, waiter count, reader/writer mix, fairness rule, or raw pointer does not prove current ownership.
- Raw pointer-like arguments do not establish reliable object identity, singleton/global cardinality, or lock identity unless the evidence API exposes identity provenance.
- Same-lock reader/writer waiters are contention only. They are not an opposing path, deadlock, starvation, or root-cause proof.
- Stack position is not lifecycle chronology. It does not prove what was already spawned/created, what will retry, what is orphaned/reaped, or what restart changes.

### Structural reciprocal discriminator

A **structural lock-order inversion** may be reported only when two observed stack paths directly show reversed component nesting across two distinct synchronization domains:

`A operation -> B-side acquisition path`

and

`B operation -> A-side acquisition path`.

This establishes only the structural inversion. It does **not** establish current holder identity or a current deadlock cycle.

Once one cross-component path is found, search only for the reverse component nesting. Prefer symbols/call-chain structure over addresses and waiter counts. If the reverse path is observed, stop searching for more equivalent waiters. If it is not found after two non-advancing attempts, mark the mechanism `bounded_unknown`.

## 3. Bounded retrieval

Before each TraceCite call identify one unresolved claim and one discriminator. If the next call cannot change the supported conclusion, stop.

- Make calls serially.
- Target `<= 8` evidence calls; Runtime may enforce a diagnosis-neutral absolute transport ceiling of 16.
- After one representative blocker, spend at most four calls on a structurally distinct reciprocal path.
- After two non-advancing calls for one discriminator, mark it `bounded_unknown` and finalize.
- No equivalent-waiter census, confirmation pass, or symptom sweep after the discriminator closes.
- Runtime call exhaustion never upgrades evidence.

### Terminal transition is immediate and irreversible

The moment any of the following occurs, switch to terminal mode immediately:

- the causal discriminator is closed;
- the causal discriminator is `bounded_unknown`;
- TraceCite reports a transport/evidence-call ceiling or refuses further evidence access.

After terminal mode begins, do **not** request another evidence tool call and do **not** emit exploratory prose such as “let me think”, “the smoking gun”, “the key insight”, causal brainstorming, alternatives, source-code reconstruction, or lifecycle speculation. Treat every subsequent assistant text token as part of the final answer and apply the terminal answer gate below from the first token. A tool-limit message is a stopping signal only; it is never evidence and never permission to complete missing causal edges from memory.

## 4. Lifecycle boundary

External process creation, shim/runc state, RPC completion, retries, cleanup/reaping, termination progress, and restart recovery require independent `event_capable` evidence tied to the observed attempt.

For `stack_only`, code-position reasoning is not event evidence. Do not infer those lifecycle events from stack frames, source line numbers, user-described symptoms, or remembered source order.

When lifecycle is outside the artifact, the only downstream-lifecycle sentence allowed is:

“The supplied evidence supports the in-process blocking pattern, but does not establish the downstream process/RPC/restart lifecycle.”

Do not write a lifecycle story and then add this caveat.

## 5. Terminal answer gate

Exploratory reasoning is disposable. Before finalizing, discard it and rebuild only from the allowed claim ledger.

For `stack_only`, the final answer may contain only these claim classes:

1. directly observed blocked/waiting paths and affected in-process call paths;
2. a structural reciprocal lock-order statement only if both reversed component paths were directly observed;
3. explicit ownership uncertainty;
4. direct in-process impact visible in the artifact, such as many parked goroutines/requests;
5. the single lifecycle-boundary sentence above.

No other causal class is allowed without stronger supplied evidence.

### Forbidden promotions

For `stack_only`, delete any sentence that does any of the following unless independently proven by stronger evidence:

- turns a waiter into a holder (`holds`, `held by`, `while holding`, `current writer`, `lock holder`, `holder exists`);
- promotes structural inversion to a current deadlock/starvation/cycle;
- uses pointer equality to claim one shared/global/singleton object or lock;
- asserts process/shim/runc spawn state, retry accumulation, orphaning, cleanup/reaping, restart/recovery, or similar lifecycle consequences;
- derives event history from source-line position or remembered control flow.

A caveat cannot repair an earlier unsupported assertion. Remove the assertion and every downstream consequence that depends on it.

### Required stack-only final format

When the artifact is `stack_only`, emit **exactly four short paragraphs** and nothing else:

`Observed:` cite representative directly observed blocked path(s).

`Mechanism:` either “The stacks support a structural lock-order inversion between <A> and <B>.” when both reciprocal paths are directly observed, or “The artifact establishes blocking/contention, but the exact root cause remains unclosed.”

`Uncertainty:` “Current lock holder/ownership is not established by this artifact.”

`Boundary:` “The supplied evidence supports the in-process blocking pattern, but does not establish the downstream process/RPC/restart lifecycle.”

Do not add headings beyond these labels, diagrams, a subsystem narrative, a “smoking gun” section, symptom explanations, alternatives, conclusion restatements, or any fifth paragraph.

Before sending, perform a literal scan. If a stack-only final contains `holder` outside the required uncertainty sentence, or contains lifecycle verbs such as `spawn`, `fork`, `retry`, `orphan`, `reap`, `restart`, `recover`, `cleanup`, delete that material and rebuild the four paragraphs.

## Runtime boundary

TraceCite Runtime may handle evidence identity, ranges, source generations, novelty, coverage, diversity, repetition, call limits, and other mechanical transport/selection concerns. Runtime must remain diagnosis-neutral: it does not know hypotheses, causality, proof claims, root cause, sufficiency, or stopping.
