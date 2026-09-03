---
name: tracecite
description: Use TraceCite as bounded evidence transport. The Agent owns hypotheses, causal reasoning, sufficiency, and stopping.
compatibility: Requires the TraceCite Pi extension and tracecite_search/tracecite_expand tools.
---

# TraceCite investigation contract

Build the smallest supported causal proof. Runtime remains diagnosis-neutral; Agent investigation and stopping policy live here.

## Highest-priority stack-only stop contract

For a stack dump without independent ownership/event chronology, treat the artifact as `stack_only` and apply these rules before any other reasoning:

1. You get at most **6 total TraceCite evidence calls** (`tracecite_search` + `tracecite_expand` combined). Count locally from 1. Never reset the count and never continue toward a higher Runtime ceiling.
2. Calls 1-2 are only for source repair/orientation. If a call fails because the requested file/source is invalid and `available_sources` is returned, retry the same unresolved claim against an exact available source; do not switch to a different query. For goroutine/stack dumps, orientation must prefer synchronization-bearing frames (`sync.Mutex`, `sync.RWMutex`, semacquire, futex, or a channel wait on the user-requested causal path) over generic blocked-state or symptom censuses. The first successful representative synchronization-bearing domain path immediately ends orientation. A generic main-loop wait, logger/fifo wait, or other symptom path does not end orientation when the question asks for a synchronization root cause.
3. Every later call must seek one missing endpoint needed to close the exact structural discriminator. Do not re-expand an already materialized range unless the prior materialization omitted an endpoint. Broad waiter census, pointer searches, lifecycle searches, symptom sweeps, and duplicate expansions are forbidden after orientation.
4. Before every TraceCite call, ask only: `Is the local count < 6, and can this call expose one missing discriminator endpoint or repair the exact unresolved source?` If either answer is no, do not call the tool. Issue at most one evidence call per model turn after orientation; do not batch parallel speculative searches because each consumes the same bounded transport budget.
5. As soon as the reverse discriminator closes, two **well-targeted** reciprocal attempts fail to advance, call 6 returns, or TraceCite refuses a call: **stop all tool use immediately**. A no-match from a broad or malformed query does not count as a well-targeted reciprocal attempt; repair the query while budget remains.
6. The entire user-visible answer then begins with `Observed:`. There is no preamble, scratch reasoning, evidence summary, heading, bullet list, stopping narration, or text before `Observed:`.
7. The entire answer is exactly four short paragraphs: `Observed:`, `Mechanism:`, `Uncertainty:`, `Boundary:`. Nothing else may appear before or after them.

If you notice that you already exceeded six evidence calls, do not compensate with more reasoning or more calls. Finalize immediately using only supported claims.

## Stack-only claim firewall

For `stack_only`:

- `blocked at acquire(X)` proves only `waits X`; it never proves `holds X` or that the caller has already acquired X.
- A waiter is not a holder. Current lock holder/ownership is unknown unless independent evidence directly proves it.
- Pointer/address equality does not prove shared, singleton, global, or same-object identity.
- Same-lock reader/writer waiters show contention only; they do not prove deadlock, starvation, a holder, an opposing causal path, or that the lock is currently owned in writer mode. In particular, simultaneous blocked `RWMutex.Lock` and `RWMutex.RLock` frames do not identify the active owner or lock state; pending-writer semantics can also block later readers.
- Do not infer an unseen running goroutine or active holder merely because all observed goroutines are waiters.
- Stack position and source order are not lifecycle chronology. Do not infer spawn, retry, orphaning, cleanup, reaping, restart, recovery, timeout causes, or process/RPC state from stack frames, source semantics, user symptoms, or model memory.
- User-reported symptoms are context, not evidence for an unobserved causal/lifecycle edge.

A structural lock-order inversion may be reported only when two observed stack paths directly show reversed component nesting across distinct synchronization domains. Privately name all four observed endpoints as `A1 -> B1` and `B2 -> A2`. If either direction is absent, the exact root cause remains unclosed. Structural inversion never establishes current holders or a current deadlock cycle.

## Final serializer

For `stack_only`, emit exactly these four paragraphs and no other prose:

`Observed:` representative directly observed blocked path(s) and directly visible in-process impact. Use only waiting/attempting language at blocked acquisition sites. Do not claim object cardinality from addresses. Do not describe an unobserved lock mode or owner.

`Mechanism:` either `The stacks support a structural lock-order inversion between <A> and <B>.` only when both reversed observed paths pass the four-endpoint test, or `The artifact establishes blocking/contention, but the exact root cause remains unclosed.` Do not append a lifecycle explanation to this paragraph.

`Uncertainty:` `Current lock holder/ownership is not established by this artifact.`

`Boundary:` `The supplied evidence supports the in-process blocking pattern, but does not establish the downstream process/RPC/restart lifecycle.`

Before emitting, delete any sentence containing an unsupported holder/acquired/lock-mode claim, pointer-derived identity/cardinality claim, starvation/deadlock/current-cycle promotion, unseen-running-goroutine claim, or lifecycle/recovery story. A later caveat does not repair an earlier unsupported assertion; remove the assertion entirely.

## Runtime boundary

TraceCite Runtime may handle evidence identity, ranges, source generations, novelty, coverage, diversity, repetition, and mechanical transport limits. Runtime must remain diagnosis-neutral: it does not know hypotheses, causality, proof claims, root cause, sufficiency, or stopping.
