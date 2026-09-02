---
name: tracecite
description: Use TraceCite as bounded evidence transport. TraceCite retrieves line-addressable evidence; the Agent owns interpretation, causal proof, sufficiency, and stopping.
compatibility: Requires the TraceCite Pi extension and tracecite_search/tracecite_expand tools.
---

# TraceCite diagnosis contract

Build the **smallest supported causal proof**. Do not perform an evidence census and do not complete missing lifecycle stories from general system knowledge.

## Mandatory execution protocol

These rules come before completeness, narrative quality, or scorer coverage:

1. Retrieve only evidence needed to close one material claim at a time. Before every TraceCite call identify internally `claim` and `discriminator`. If either is missing, answer now.
2. Issue TraceCite calls serially. Never batch or parallelize TraceCite calls: make at most one TraceCite call per assistant turn, inspect that result's `tracecite_host_activity_summary.total_tool_calls`, then decide whether another call is admissible. At 16 or greater, the next assistant action must be the final answer. Never make call 17.
3. A stack/source position after an acquire is **not** evidence that the lock is still held. For current ownership, supplied evidence must itself expose the acquire-to-release control-flow interval strongly enough to exclude an intervening release. Model memory or guessed source scope is not supplied evidence.
4. Do not establish deadlock/cycle/lock-order inversion unless both opposing current `holds -> waits` edges are independently supported. A waiter is never a holder merely because someone must hold the resource.
5. Stop at the artifact boundary. Do not explain downstream process creation, RPC completion, retries, cleanup/reaping, or restart recovery unless supplied evidence independently establishes those lifecycle links.
6. Once the mechanism and direct visible impact are closed, answer immediately. No waiter census, synonym search, confirmation pass, or symptom completion.

## Non-negotiable final gate

Immediately before answering, delete or qualify every material sentence that is not supported by the supplied artifact. This gate overrides completeness and helpfulness. A later caveat does not cure an earlier unsupported lifecycle/process statement: delete the unsupported statement instead of narrating it and disclaiming it later.

1. **Waiter != holder.** `blocked at acquire(X)`, `lockSlow(X)`, `RLock(X)`, or queued `Lock(X)` proves only `waits X`. Multiple waiters or lock exclusivity never identify a holder. A blocked `RLock(X)` does not prove that a writer currently holds X; it may also reflect queued-writer preference. Do not convert a one-resource waiter pattern into a holder edge. If the current holder identity is not observed or proven by the control-flow ownership rule below, leave it unknown.
2. **A claimed current hold needs current-ownership proof.** A caller frame or earlier acquisition alone is insufficient. `acquire(Y) + current nested call + release only after nested return -> may support currently holds Y`, but only when the supplied artifact exposes that interval strongly enough to exclude an intervening release. A later source line, deeper callee frame, or progress-past-acquire reasoning is not enough. If the acquisition/release scope is missing, mark the hold `bounded_unknown`.
3. **Deadlock/cycle/lock-order inversion requires two independently supported current edges:** `holds A -> waits B` and `holds B -> waits A`. Use direct observation or a supplied-evidence control-flow interval, but not an unobserved holder, waiter census, pointer proximity, queued-reader/writer semantics, guessed lock scope, or progress-past-acquire reasoning. Repeated waits on one resource establish contention only, not an opposing causal path. If either edge lacks current-holder proof, report only the supported blocking/contention and the missing edge as unknown. Do not use the words deadlock, cycle, cyclic wait, lock-order inversion, or AB-BA in the final conclusion unless both edges are present in the proof ledger.
4. **Do not manufacture identity.** Pointer proximity, guessed struct layout, helper names, or model-known source code cannot establish object/request/process identity.
5. **Chronology conservation.** If supplied evidence shows a request blocked before stage S, do not say that same blocked attempt caused or repeatedly executed stages after S unless supplied evidence independently shows that later stage for that attempt.
6. **Artifact lifecycle boundary.** An in-process goroutine snapshot does not by itself prove that a shim/process was forked, where an external process is waiting, whether an RPC/reply/registration completed, what a retry created, whether cleanup/reaping is blocked, or why restart recovers. Concurrent helper goroutines do not establish identity with the blocked request.
7. **User-described symptoms are hypotheses, not evidence.** Restart recovery, accumulating processes, retries, or cleanup hangs may guide retrieval but do not prove lifecycle linkage.

When downstream lifecycle is outside the artifact, use one artifact-boundary sentence and stop: “The supplied evidence supports the in-process blocking mechanism, but does not establish the downstream process/RPC/restart lifecycle.”

## Proof ledger

For each material claim track only:

```text
unresolved | observed | supported_inference | contradicted | bounded_unknown
```

For each blocking representative normalize:

```text
waits: resource at the blocking acquisition
holds: only resources proven still held at that blocking point
basis: exact supplied evidence for waiting and any claimed current hold
```

Hard implications:

```text
blocked at acquire(X) -> waits X
blocked at acquire(X) -/-> holds X
blocked at RLock(X) -/-> writer currently holds X
repeated waits on X -/-> opposing causal edge
caller frame alone -/-> current ownership
later source line after acquire(Y) -/-> currently holds Y
progressed past acquire(Y) -/-> currently holds Y
acquire(Y) + current nested call + release only after nested return -> may support currently holds Y
unobserved holder -/-> supported holder edge
sibling waiter on X -/-> holder identity for X
blocked before S -/-> same attempt reached stage after S
user-reported symptom -/-> artifact-supported causal linkage
```

A claim is closed once `observed`, `supported_inference`, or `bounded_unknown`. Do not reopen it for reassurance.

## Bounded retrieval

Before every TraceCite call identify internally:

```text
claim: one unresolved or contradicted material fact
discriminator: the concrete result that would change that claim
```

If either cannot be named, answer instead of calling TraceCite.

Use one strongest representative per causal role. Equivalent waiters are not additional proof.

Transport limits per investigation:

- `tracecite_search`: `max_evidence <= 12`
- `tracecite_expand`: normally `radius <= 16`
- **target total evidence calls: <= 12; absolute ceiling: 16**
- after two consecutive non-advancing calls for the same claim, mark it `bounded_unknown`
- never use extra calls to confirm an already closed claim

Never batch or parallelize TraceCite calls. The activity count is only actionable after the current result is observed, so each result must be inspected before any next TraceCite request is emitted.

Every TraceCite result may include `tracecite_host_activity_summary.total_tool_calls`. Inspect this field before interpreting or acting on the returned evidence. If the returned total is 16 or greater, that tool result is the terminal retrieval result and the next assistant action must be the final answer, not another TraceCite call. Do not estimate or restart the count from memory. Evidence from any accidental later call is inadmissible.

## Stop rule

The proof is complete when every material claim is `observed`, `supported_inference`, or `bounded_unknown` and no contradiction remains unresolved. Once complete, the next assistant action must be the final answer. No confirmatory search, waiter census, symptom sweep, or lifecycle completion. Treat this as a terminal commitment.

## Final answer shape

Keep the final response compact and normal. Include only:

1. one mechanism/subsystem statement;
2. the minimum supported causal path or opposing edges;
3. direct impact visible in supplied evidence;
4. one artifact-boundary sentence for unsupported downstream lifecycle;
5. only the strongest representative line citations.

Perform a deletion pass before emitting: remove any sentence that names an unproven holder, treats past-the-acquire-line as current-hold proof without an evidenced release scope, assigns a waiter to a holder role, claims downstream process/RPC/retry/restart/cleanup state, or explains a user-reported symptom without independent artifact support.

## Runtime boundary

TraceCite Runtime may handle evidence identity, ranges, source generations, novelty, coverage, diversity, repetition, and other mechanical transport/selection concerns. Runtime must remain diagnosis-neutral: it does not know hypotheses, causality, proof claims, root cause, sufficiency, or stopping.
