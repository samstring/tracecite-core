---
name: tracecite
description: Use TraceCite as bounded evidence transport. The Agent owns hypotheses, causal reasoning, sufficiency, and stopping.
compatibility: Requires the TraceCite Pi extension and tracecite_search/tracecite_expand tools.
---

# TraceCite investigation contract

Build the smallest supported causal proof. Runtime remains diagnosis-neutral; Agent investigation and stopping policy live here.

## Highest-priority stack-only stop contract

For a stack dump without independent ownership/event chronology, treat the artifact as `stack_only` and apply these rules before any other reasoning:

1. You get at most **6 total TraceCite evidence calls** (`tracecite_search` + `tracecite_expand` combined). Count locally from 1. **Every tool invocation counts, including source errors, `no_match`, `no_new_evidence`, and refused calls; source repair does not refund or reset a slot.** Never reset the count and never continue toward a higher Runtime ceiling. If a tool result exposes `tracecite_host_activity_summary.total_tool_calls`, treat that value as the authoritative cumulative evidence-call count; never narrate or continue from a smaller locally remembered count.
2. Calls 1-2 are only for source repair/orientation. If a call fails because the requested file/source is invalid and `available_sources` is returned, retry the same unresolved claim against an exact available source; do not switch to a different query. For a Go goroutine dump asking for a synchronization root cause, the first valid orientation search **must** be a single synchronization token or single-construct regex, normally `semacquire` (or the exact channel/futex primitive named by the causal path). Before the first representative synchronization-bearing domain path is materialized, process/lifecycle/symptom tokens such as `runc`, `shim`, `process`, `RPC`, `FIFO`, generic `goroutine`, or user-visible symptom nouns are forbidden orientation queries. The first successful representative synchronization-bearing domain path immediately ends orientation. A generic main-loop wait, logger/fifo wait, or other symptom path does not end orientation when the question asks for a synchronization root cause.
3. Every later call must seek one missing endpoint needed to close the exact structural discriminator. For an `RWMutex` representative path, the **first reciprocal search must target the complementary acquisition primitive** (`RLock` after an observed writer `Lock`, or `Lock` after an observed reader `RLock`) or an exact function/type symbol already present on that synchronization-bearing path; expand only the resulting synchronization-bearing candidate needed to expose caller/component nesting. **If a successful TraceCite response already includes `structural_diversity` / `navigation_hint` candidates, the next reciprocal evidence call must materialize the most relevant synchronization-bearing hint before issuing a fresh literal/regex search. Treat those hints as precomputed candidate stack blocks, not optional metadata. A no-match on one complementary primitive spelling cannot support absence while an unmaterialized synchronization-bearing structural-diversity hint remains.** **A complementary waiter is only an orientation clue, not a reciprocal causal endpoint. After materializing it, immediately search an exact caller/component symbol from that path to find the opposite cross-component nesting; do not spend remaining budget on another same-direction waiter. The discriminator closes only with reversed component nesting across distinct synchronization domains, not merely with `Lock` plus `RLock` waiters on one mutex.** Once a materialized path exposes two application components, privately name the ordered component pair `B -> A`. **The very next evidence call must search the exact receiver/type-family identity of outer component `B` from that complementary path; do not substitute a package-wide token, subsystem path, waiter census, another synchronization primitive, or a re-expand of either already materialized path. If only one evidence-call slot remains, that slot is reserved exclusively for this outer-component-family reciprocal search; otherwise finalize unclosed.** That reciprocal search must anchor on the **component identity of outer component `B` at receiver/type-family level**, not on the exact method already observed. Use the shortest distinctive package/type token or regex that can also match sibling methods of `B`; for Go, preserve the receiver/type identity but intentionally omit the method name when the reverse path may enter the same component through another method. Prefer a structurally different candidate where `A` calls back into a sibling method of `B`. Do not search the full observed `(*Type).Method` frame as the reciprocal anchor when that would exclude sibling methods. After a complementary candidate is materialized, do not re-expand the original representative path merely to extend caller/impact context; reserve the next call for this component-family reciprocal search. Do not spend a call on an unrelated synchronization branch after the component pair is named. For other synchronization primitives, use the exact acquisition primitive or exact function/type symbols from the representative path. Never use process/lifecycle/symptom nouns as reciprocal queries. Do not re-expand an already materialized range unless the prior materialization omitted an endpoint. Broad waiter census, pointer searches, lifecycle searches, symptom sweeps, and duplicate expansions are forbidden after orientation.
4. Before every TraceCite call, ask only: `Is the authoritative/local count < 6, and can this call expose one missing discriminator endpoint or repair the exact unresolved source?` If either answer is no, do not call the tool. Issue at most one evidence call per model turn after orientation; do not batch parallel speculative searches because each consumes the same bounded transport budget.
5. As soon as the reverse discriminator closes, two **well-targeted** reciprocal attempts fail to advance, the authoritative/local count reaches 6, call 6 returns, or TraceCite refuses a call: **stop all tool use immediately**. A no-match from a broad or malformed query does not count as a well-targeted reciprocal attempt; repair the query while budget remains. **After call 6 returns, the same model turn must go directly to the terminal four-paragraph answer; do not emit planning text, announce another check, or attempt any seventh evidence call.**
6. The entire user-visible answer then begins with `Observed:`. There is no preamble, scratch reasoning, evidence summary, heading, bullet list, stopping narration, or text before `Observed:`. Treat `Observed:` as the literal first bytes of the final response, not as a later section after private synthesis text.
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

A structural lock-order inversion may be reported only when two observed stack paths directly show reversed component nesting across distinct synchronization domains. Privately name all four observed endpoints as `A1 -> B1` and `B2 -> A2`. **Choose stable component identities `A` and `B` before declaring closure. Both `A` and `B` must appear in both materialized paths: one path must directly show `A ... B ... acquire(domain_B)`, and the other must directly show `B ... A ... acquire(domain_A)`, with `domain_A` and `domain_B` distinct synchronization acquisition sites/domains. Different outer callers that merely converge on the same inner lock, including `Lock` and `RLock` waiters on one `RWMutex`, do not satisfy this four-endpoint membership test. If either component appears in only one path, reciprocal closure is false and the exact root cause remains unclosed.** If either direction is absent, the exact root cause remains unclosed. Structural inversion never establishes current holders or a current deadlock cycle.

## Final serializer

For `stack_only`, emit exactly these four paragraphs and no other prose:

`Observed:` representative directly observed blocked path(s) and directly visible in-process impact. Use only waiting/attempting language at blocked acquisition sites. Do not claim object cardinality from addresses. Do not describe an unobserved lock mode or owner.

`Mechanism:` either `The stacks support a structural lock-order inversion between <A> and <B>.` only when both reversed observed paths pass the four-endpoint test, or `The artifact establishes blocking/contention, but the exact root cause remains unclosed.` Do not append a lifecycle explanation to this paragraph.

`Uncertainty:` `Current lock holder/ownership is not established by this artifact.`

`Boundary:` `The supplied evidence supports the in-process blocking pattern, but does not establish the downstream process/RPC/restart lifecycle.`

Before emitting, delete any sentence containing an unsupported holder/acquired/lock-mode claim, pointer-derived identity/cardinality claim, starvation/deadlock/current-cycle promotion, unseen-running-goroutine claim, or lifecycle/recovery story. A later caveat does not repair an earlier unsupported assertion; remove the assertion entirely.

## Runtime boundary

TraceCite Runtime may handle evidence identity, ranges, source generations, novelty, coverage, diversity, repetition, and mechanical transport limits. Runtime must remain diagnosis-neutral: it does not know hypotheses, causality, proof claims, root cause, sufficiency, or stopping.
