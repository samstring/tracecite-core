---
name: tracecite
description: Use TraceCite as bounded evidence transport. TraceCite retrieves line-addressable evidence; the Agent owns interpretation, causal proof, sufficiency, and stopping.
compatibility: Requires the TraceCite Pi extension and tracecite_search/tracecite_expand tools.
---

# TraceCite diagnosis contract

Build the **smallest supported causal proof**. Do not perform an evidence census and do not complete missing lifecycle stories from general system knowledge.

## Non-negotiable final gate

Immediately before answering, delete or qualify every material sentence that is not supported by the supplied artifact. This gate overrides completeness and helpfulness.

1. **Waiter != holder.** `blocked at acquire(X)`, `lockSlow(X)`, `RLock(X)`, or queued `Lock(X)` proves only `waits X`. Multiple waiters or lock exclusivity never identify a holder.
2. **A claimed current hold needs current-ownership proof.** Earlier acquisition, source-line progress, an active caller frame, a remembered `defer Unlock`, or assumed lock scope does not prove the resource is still held at the observed block. If continued ownership is not represented by supplied evidence, mark it `bounded_unknown`.
3. **Deadlock/cycle/lock-order inversion requires two independently supported current edges:** `holds A -> waits B` and `holds B -> waits A`. If either edge lacks current-holder proof, do not establish a cycle; report only the supported blocking/contention and the missing edge as unknown. **Do not use the words deadlock, cycle, cyclic wait, lock-order inversion, or AB-BA in the final conclusion unless both current edges are present in the proof ledger with supplied-evidence basis.** A logically necessary but unobserved holder is not a supported second edge.
4. **Do not manufacture identity.** Pointer proximity, guessed struct layout, helper names, or model-known source code cannot establish object/request/process identity.
5. **Chronology conservation.** If supplied evidence shows a request blocked before stage S, do not say that same blocked attempt caused or repeatedly executed stages after S unless supplied evidence independently shows that later stage for that attempt.
6. **Artifact lifecycle boundary.** An in-process goroutine snapshot does not by itself prove that a shim/process was forked, where an external process is waiting, whether an RPC/reply/registration completed, what a retry created, whether cleanup/reaping is blocked, or why restart recovers. Omit those claims unless directly represented in supplied evidence.

When downstream lifecycle is outside the artifact, use one sentence such as: **“The supplied evidence supports the in-process blocking mechanism, but does not establish the downstream process/RPC/restart lifecycle.”** Then stop.

## Proof ledger

For each material claim track only:

```text
unresolved | observed | supported_inference | contradicted | bounded_unknown
```

For each blocking representative normalize:

```text
waits: resource at the blocking acquisition
holds: only resources proven still held at that blocking point
basis: exact supplied evidence for both waiting and any claimed current hold
```

Hard implications:

```text
blocked at acquire(X) -> waits X
blocked at acquire(X) -/-> holds X
passed acquire(Y) -/-> currently holds Y
active caller frame -/-> current ownership
unobserved holder -/-> supported holder edge
blocked before S -/-> same attempt reached stage after S
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

Every TraceCite result may include a mechanical `tracecite_host_activity_summary.total_tool_calls`. Treat that number as the authoritative running evidence-call count. **Before issuing another TraceCite call, if the latest observed total is 16 or greater, do not call a tool again.** Resolve remaining claims as `bounded_unknown`, run the final gate, and answer. Do not estimate or restart the count from memory.

At 16 evidence calls, stop retrieval unconditionally, resolve remaining claims as `bounded_unknown`, run the final gate, and answer.

## Stop rule

The proof is complete when every material claim is `observed`, `supported_inference`, or `bounded_unknown` and no contradiction remains unresolved. Once complete, the **next assistant action must be the final answer**. No confirmatory search, waiter census, symptom sweep, or lifecycle completion.

If you internally state “enough”, “confirmed”, “complete picture”, or “ready to answer”, that is a terminal commitment: do not make another evidence call unless newly returned supplied evidence contradicted a closed claim and the absolute ceiling has not been reached.

## Final answer shape

Keep the final response to:

1. one compact mechanism/subsystem statement;
2. the minimum supported causal path/edges;
3. direct impact visible in supplied evidence;
4. one artifact-boundary sentence for unsupported downstream lifecycle;
5. only the strongest representative line citations.

Do not enumerate equivalent waiters. Do not add restart, retry, cleanup, process-management, external-RPC, hidden-holder, or fix stories unless independently established by supplied evidence.

# Runtime boundary

TraceCite Runtime may handle evidence identity, ranges, source generations, novelty, coverage, diversity, repetition, and other mechanical transport/selection concerns. Runtime must remain diagnosis-neutral: it does not know hypotheses, causality, proof claims, root cause, sufficiency, or stopping.
