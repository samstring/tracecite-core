---
name: tracecite
description: Use TraceCite as bounded evidence transport. The Agent owns hypotheses, causal reasoning, sufficiency, and stopping.
compatibility: Requires the TraceCite Pi extension and tracecite_search/tracecite_expand tools.
---

# TraceCite investigation contract

Build the smallest supported causal proof. Runtime remains diagnosis-neutral; Agent investigation and stopping policy live here.

## Stack-only evidence firewall

Classify stack dumps without independent ownership or event chronology as `stack_only`.

For `stack_only`:

- `blocked at acquire(X)` proves only `waits X`; it never proves `holds X`.
- A waiter is not a holder. Current lock holder/ownership is not established unless independent evidence proves it.
- Pointer/address equality does not prove shared object or lock identity.
- Same-lock reader/writer waiters show contention only; they do not prove deadlock, starvation, or an opposing causal path.
- Stack position is not lifecycle chronology. Do not infer process spawn, retry, orphaning, cleanup, reaping, restart, or recovery from stack frames, line order, runtime semantics, or model memory.

A structural lock-order inversion may be reported only when two observed stack paths directly show reversed component nesting across distinct synchronization domains:

`A-owned operation -> B-owned operation/acquisition path`

and

`B-owned operation -> A-owned operation/acquisition path`.

Before closing this discriminator, privately name the four observed endpoints as `A1 -> B1` and `B2 -> A2`. If either direction is missing, the exact root cause remains unclosed. Structural inversion never establishes current holders or a current deadlock cycle.

## Stack-only evidence-call state machine

Every `tracecite_search` and every `tracecite_expand` is one evidence call.

Maintain one local `evidence_call_index`, initialized to `0`. Increment it exactly once after each TraceCite tool response. Never reset it and never derive it from Runtime metadata.

Before every TraceCite call, check `evidence_call_index`:

- calls 1–2 are the complete orientation phase and must locate one representative domain-specific blocked path;
- calls 3–6 are reciprocal-only and must target exact component/frame symbols that could expose the reverse component nesting;
- when `evidence_call_index >= 6`, another TraceCite call is forbidden and finalization is mandatory.

A Runtime transport allowance may be higher. It is only a diagnosis-neutral safety ceiling and is never extra investigation budget. Do not continue toward a higher Runtime ceiling because transport remains available.

After orientation, do not use broad discovery queries such as `goroutine`, `Lock`, `semacquire`, generic subsystem nouns, pointer/address searches, equivalent-waiter census, or lifecycle/symptom sweeps such as `runc`, `shim`, `process`, `RPC`, or `FIFO`, unless the exact frame is already on the representative path and can expose the reciprocal nesting.

A reciprocal attempt is non-advancing when it returns another equivalent waiter, only the same acquisition direction, a raw-address match, or lifecycle/symptom material. After two non-advancing reciprocal attempts, mark the mechanism `bounded_unknown` and finalize immediately. If the reverse path is still unclosed after call 6, finalize immediately.

This state machine is Agent investigation/stopping policy. It must not be moved into Runtime.

## Terminal transition

Terminal mode begins immediately when the reciprocal discriminator closes, becomes `bounded_unknown`, call 6 completes without closure, or TraceCite refuses additional evidence.

After terminal mode begins, do not call TraceCite again and do not emit stopping narration or scratch prose. The first assistant prose after the final evidence call MUST begin exactly with `Observed:`. If a tool reports a limit, the very next assistant token MUST be the `O` in `Observed:`.

For `stack_only`, emit exactly four short paragraphs and nothing else:

`Observed:` representative directly observed blocked path(s), using waiting language only for blocked acquisition sites and direct in-process impact such as many parked requests/goroutines.

`Mechanism:` either “The stacks support a structural lock-order inversion between <A> and <B>.” when both reciprocal observed paths pass the four-endpoint test, or “The artifact establishes blocking/contention, but the exact root cause remains unclosed.”

`Uncertainty:` “Current lock holder/ownership is not established by this artifact.”

`Boundary:` “The supplied evidence supports the in-process blocking pattern, but does not establish the downstream process/RPC/restart lifecycle.”

Do not add any fifth paragraph, heading, bullet list, pointer-based identity claim, waiter-as-holder claim, lifecycle/process/kernel story, or deadlock/starvation/current-cycle promotion.

## Runtime boundary

TraceCite Runtime may handle evidence identity, ranges, source generations, novelty, coverage, diversity, repetition, and mechanical transport limits. Runtime must remain diagnosis-neutral: it does not know hypotheses, causality, proof claims, root cause, sufficiency, or stopping.
