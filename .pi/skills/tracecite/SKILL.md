---
name: tracecite
description: Use TraceCite as bounded evidence transport. TraceCite retrieves line-addressable evidence; the Agent owns interpretation, causal proof, sufficiency, and stopping.
compatibility: Requires the TraceCite Pi extension and tracecite_search/tracecite_expand tools.
---

# TraceCite diagnosis contract

Build the **smallest supported causal proof**. Do not perform an evidence census and do not complete missing lifecycle stories from general system knowledge.

## Non-negotiable final gate

Immediately before answering, delete or qualify every material sentence that is not supported by the supplied artifact. This gate overrides completeness and helpfulness.

1. **Waiter != holder.** `blocked at acquire(X)`, `lockSlow(X)`, `RLock(X)`, or queued `Lock(X)` proves only `waits X`. Multiple waiters or lock exclusivity never identify a holder. A blocked `RLock(X)` does not prove that a writer currently holds X; it may also reflect queued-writer preference. Do not convert a one-resource waiter pattern into a holder edge. **If the current holder identity is not observed or proven by the control-flow ownership rule below, the final answer must leave that holder identity unknown; never name a likely holder or its code path from sibling waiters, exclusivity, or “someone must hold it” reasoning.**
2. **A claimed current hold needs current-ownership proof.** A caller frame or an earlier acquisition alone is insufficient. A current hold may, however, be a `supported_inference` when supplied evidence establishes the full control-flow interval: the same execution acquired Y, entered the currently blocked nested call before any possible release of Y, and the release cannot execute until that nested call returns (for example, a directly evidenced lock scope or deferred release). **Merely being at a later source line, having progressed past the acquire call, or having a deeper callee frame is not current-ownership proof.** To infer a hold from control flow, the supplied artifact must expose the acquisition and the release scope (or equivalent control-flow fact) strongly enough to exclude an intervening release. Do not require a separate visible "holder frame" when this interval is actually established. If acquisition-before-current-call or release-after-return is missing, mark the hold `bounded_unknown`. For a control-flow-derived opposing edge, inspect the acquisition and release scope itself; do not replace a missing scope with a hidden-holder guess.
3. **Deadlock/cycle/lock-order inversion requires two independently supported current edges:** `holds A -> waits B` and `holds B -> waits A`. Either edge may use direct observation or the control-flow ownership proof above, but not an unobserved holder, waiter census, pointer proximity, queued-reader/writer semantics, guessed lock scope, or progress-past-acquire reasoning. Repeated waits on one resource establish contention only, not an opposing causal path. If either edge lacks current-holder proof, do not establish a cycle; report only the supported blocking/contention and the missing edge as unknown. **Do not use the words deadlock, cycle, cyclic wait, lock-order inversion, or AB-BA in the final conclusion unless both current edges are present in the proof ledger with supplied-evidence basis.**
4. **Do not manufacture identity.** Pointer proximity, guessed struct layout, helper names, or model-known source code cannot establish object/request/process identity.
5. **Chronology conservation.** If supplied evidence shows a request blocked before stage S, do not say that same blocked attempt caused or repeatedly executed stages after S unless supplied evidence independently shows that later stage for that attempt.
6. **Artifact lifecycle boundary.** An in-process goroutine snapshot does not by itself prove that a shim/process was forked, where an external process is waiting, whether an RPC/reply/registration completed, what a retry created, whether cleanup/reaping is blocked, or why restart recovers. Concurrent goroutines in Wait/FIFO/ttrpc/process helpers do not establish that they belong to the blocked request. Omit those claims unless identity and causal linkage are directly represented in supplied evidence.
7. **User-described symptoms are hypotheses, not evidence.** A prompt may say that restart recovers, external processes accumulate, requests retry, or cleanup hangs. Those observations may guide retrieval, but they do not prove the mechanism or lifecycle linkage. Do not use the symptom description itself to validate a causal sentence in the final answer.

When downstream lifecycle is outside the artifact, use one sentence such as: **“The supplied evidence supports the in-process blocking mechanism, but does not establish the downstream process/RPC/restart lifecycle.”** Then stop. **Do not explain how `runc init`, shim creation, retries, cleanup/reaping, kubelet RPC completion, or restart recovery follow from the in-process block unless the supplied artifact independently proves those exact lifecycle links.** Do not add a section that explains how every reported symptom “matches” unless each linkage is independently represented in supplied evidence.

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

A claim is closed once `observed`, `supported_inference`, or `bounded_unknown`. Do not reopen it for reassurance, duplicate evidence, or completeness.

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

Every TraceCite result may include a mechanical `tracecite_host_activity_summary.total_tool_calls`. Treat that number as the authoritative running evidence-call count. **Inspect this field before interpreting or acting on the returned evidence. If the returned total is 16 or greater, that tool result is the terminal retrieval result: the next assistant action must be the final answer, not another TraceCite call.** Resolve remaining claims as `bounded_unknown`, run the final gate, and answer. Do not estimate or restart the count from memory.

At 16 evidence calls, stop retrieval unconditionally, resolve remaining claims as `bounded_unknown`, run the final gate, and answer. **Evidence obtained by any accidental call after the terminal count is inadmissible: do not cite it or use it to strengthen the conclusion.**

## Stop rule

The proof is complete when every material claim is `observed`, `supported_inference`, or `bounded_unknown` and no contradiction remains unresolved. Once complete, the **next assistant action must be the final answer**. No confirmatory search, waiter census, symptom sweep, or lifecycle completion.

If you internally state “enough”, “confirmed”, “complete picture”, or “ready to answer”, that is a terminal commitment: do not make another evidence call unless newly returned supplied evidence contradicted a closed claim and the absolute ceiling has not been reached.

## Final answer shape

Keep the final response compact and normal. Include only:

1. one mechanism/subsystem statement;
2. the minimum supported causal path or opposing edges;
3. direct impact visible in supplied evidence;
4. one artifact-boundary sentence for unsupported downstream lifecycle;
5. only the strongest representative line citations.

Before emitting the final answer, perform a **deletion pass**: remove any sentence that names an unproven holder, treats "past the acquire line" as proof of a current hold without an evidenced release scope, assigns a waiter to a holder role, claims a downstream process/RPC/retry/restart/cleanup state, or explains a user-reported symptom without an independent artifact-supported identity and causal link. If deletion leaves a gap, state that point as unknown rather than filling it with a plausible story.

Do not enumerate equivalent waiters. Do not add “why every symptom matches”, restart, retry, cleanup, process-management, external-RPC, hidden-holder, or fix stories unless independently established by supplied evidence.

# Runtime boundary

TraceCite Runtime may handle evidence identity, ranges, source generations, novelty, coverage, diversity, repetition, and other mechanical transport/selection concerns. Runtime must remain diagnosis-neutral: it does not know hypotheses, causality, proof claims, root cause, sufficiency, or stopping.
