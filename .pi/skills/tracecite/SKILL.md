---
name: tracecite
description: Use TraceCite as an evidence transport and evidence-memory layer. TraceCite retrieves and materializes evidence with provenance; the Agent owns interpretation, hypotheses, causality, sufficiency, root cause, and stopping.
compatibility: Requires the TraceCite Pi extension. tracecite_search/tracecite_expand may be exposed as compatibility aliases for retrieval/materialization.
---

# TraceCite evidence contract

```text
TraceCite = retrieve + materialize + provenance + mechanical evidence memory
Agent     = interpret + hypothesize + compare + infer + decide sufficiency + stop
```

TraceCite runtime never chooses a hypothesis, root cause, investigation direction, semantic importance, or stop decision. Those decisions belong to the Agent/skill layer.

Token saving never overrides correctness.

# Highest-priority stopping rule: cover the user's answer obligations

Before investigating, extract only the material **answer obligations** explicitly required by the user's question. Keep the list small and concrete; do not invent extra obligations for curiosity or reassurance.

Track each obligation as:

```text
open                 material answer slot still missing evidence
supported            directly observed or properly qualified inference with evidence refs
contradicted         observed evidence materially conflicts with the current claim
qualified_boundary   supplied evidence cannot establish the requested detail; state the boundary
```

A TraceCite call is justified only when it does one of these:

1. targets one `open` obligation;
2. resolves one `contradicted` obligation;
3. materializes an already-identified range needed to cite a material claim.

If no obligation is `open` or `contradicted`, **answer immediately**. Do not search for more confidence, completeness, alternative wording, extra examples, or hypothetical unknown conditions that were not raised by supplied evidence.

Do not create a new obligation merely because another search is possible. New obligations may be added only when newly observed evidence creates a material contradiction or reveals that an explicit user requirement was not actually covered.

# Terminal answer transition

The obligation ledger is internal bookkeeping, not another investigation task. Do not spend model turns repeatedly narrating, replanning, rechecking, or reconfirming already-closed obligations without new evidence.

After an evidence round, make exactly one transition:

```text
an explicit obligation is still open/contradicted
    -> the next evidence call targets that obligation

all explicit obligations are supported/qualified and no observed contradiction remains
    -> the next assistant action is the final answer
```

There is no intermediate "let me consolidate", "final verification", "one more check", or extra confidence-building phase after closure. If the Agent has stated or internally concluded that the picture/mechanism is complete, established, confirmed, sufficient, or that it has everything needed, another TraceCite call is justified only by naming one still-open or contradicted **explicit answer obligation**. If none can be named, answer now.

For a root-cause investigation, when the evidence supports a root-cause conclusion, open the final answer with one compact root-cause sentence that states the failure mechanism/class and the affected subsystem or component. Then explain the competing/causal paths, user-visible impact, strongest evidence, and any evidentiary boundary required by the user's question. This is an answer-clarity rule, not a requirement to retrieve additional evidence.

# One evidence round = one obligation

Treat one Agent tool-use batch as an evidence round. Every exploratory round must name one target obligation internally and stay bounded to that obligation.

Use a short form only:

```text
ROUND: O=<open/contradicted obligation>; Δ=<result that would change its status>; T=<bounded target>
```

Do not turn this into a planning essay.

Prefer one narrow search followed by the minimum bounded materialization needed for the same obligation. Parallel calls are acceptable only when they test distinct anchors for that same obligation and can be interpreted together.

After the round, update the obligation status before starting another round.

# Per-obligation diminishing returns

Do not spend repeated rounds trying to convert an evidence-supported inference into impossible direct observation.

For the same obligation, a round is `non_advancing` when it produces only:

```text
duplicate evidence
another equivalent instance
another synonymous no-match
already-covered body/context
no change to the obligation's material claim or qualification
```

If **2 consecutive non-advancing rounds** target the same obligation and no genuinely new observed anchor emerged, stop reformulating that search. Either:

- use the best evidence-supported qualification already available; or
- mark the detail `qualified_boundary` if the supplied artifact cannot establish it.

A new observed anchor may justify a new targeted round; a new synonym does not.

This patience is local to one unresolved answer obligation. It is not a requirement to perform extra rounds after the answer is already covered.

# Observation versus inference

Use `supported` for both direct observations and appropriately qualified inferences, but keep the distinction explicit in the answer.

A supplied snapshot may support a causal/synchronization inference from competing observed call paths even when historical internal state is not directly visible. Do not repeatedly search a snapshot for invisible acquisition history, past ownership, or events it cannot encode merely to turn an inference into a direct observation.

Likewise:

```text
not visible as a current frame != proven never acquired/performed
present in a call path          != proven currently held/active
captured line order             != happens-before or event time
```

If the user's requested conclusion necessarily depends on inference from the supplied artifact, state the inference and its evidentiary basis rather than searching indefinitely for impossible proof.

# Synchronization evidence semantics

When the incident involves blocking, contention, deadlock, or other synchronization failure, interpret stacks as a **minimal wait-for graph**, not as a census of every waiter.

A blocked synchronization-acquisition frame such as `Lock`, `RLock`, semaphore acquire, condition wait, channel receive/send, or equivalent means that execution is **waiting at that operation**. It does not by itself prove that the goroutine already holds the synchronization object it is waiting to acquire.

An enclosing caller lower in the same stack may still be inside a different critical section that it entered before invoking the blocked callee. Infer that an outer lock is held only when the supplied evidence supports the critical-section ordering: for example, a representative stack shows execution has progressed from the outer acquisition into a nested call that is now blocked, or other supplied stacks/line locations establish the acquisition boundary. If the artifact cannot establish that ordering directly, keep it as a qualified inference rather than repeatedly searching for invisible lock history.

For a candidate lock-ordering cycle, reconstruct only the distinct causal edges needed to distinguish a cycle from ordinary contention:

```text
path A: outer critical section / held resource -> waits for resource B
path B: outer critical section / held resource B -> waits for resource A
```

Do not call something a deadlock merely because many goroutines wait on one mutex, and do not downgrade a supported cycle to a convoy merely because the acquisition frame of a held *outer* lock is no longer visible on the current stack.

Once one strongest representative stack supports each distinct opposing path, the synchronization mechanism is closed unless observed evidence contradicts an edge. More equivalent waiters, counts, neighboring stacks, alternate search terms, or repeated lock-address searches are not additional answer obligations.

For structural causal claims, prefer **representative evidence over exhaustive census**: one fully materialized exemplar per distinct causal path plus the minimum evidence connecting the mechanism to the user-visible impact is sufficient unless the question explicitly asks about frequency, prevalence, scope, or ordering, or multiplicity distinguishes competing explanations.

# What does not justify another round

These are not answer obligations:

```text
look for more evidence
confirm the hypothesis
check another example
see what else is present
be extra sure
final verification
one more quick check
count more equivalent instances
survey unrelated goroutine/process classes
prove an unobservable historical state from a snapshot
```

Multiplicity, frequency, variation, scope, or ordering can be material only when the user's question requires them or when they distinguish competing explanations already raised by observed evidence.

Fresh lines are not automatically new semantic information. New evidence identity is not automatically progress.

# Evidence correctness

- In TraceCite-only mode, do not retry blocked native `read`/`grep`/`find`/`ls`/shell evidence access.
- Once a `follow_up_file`, `source_path`, or immutable source identity is known, reuse it instead of rediscovering the same source.
- Search previews may omit multi-line record bodies. If a material conclusion depends on a complete stack, traceback, exception, record, or surrounding context, materialize the bounded body first.
- Navigation/signal hints are recovery coordinates, not evidence of causal importance, and are not observed body evidence until materialized.
- `matched_existing_evidence`, covered ranges, repeated evidence, and `status=no_new_evidence` are mechanical facts. Do not refetch the same body simply to confirm it exists.
- If materialization for the same evidence identity/range returns empty text, `status=no_new_evidence`, or only already-covered/matched-existing evidence, do not repeatedly retry adjacent lines, radius changes, or synonymous searches for that same body. One alternate recovery coordinate is reasonable only when newly observed output supplies a genuinely different concrete coordinate and the body is still required by an explicit open obligation. Otherwise reuse the strongest already-materialized evidence or state the evidentiary boundary.
- `status=no_match` applies to the exact retrieval request; it is not automatically proof of global absence.
- Reuse source SHA/immutable identity when available.
- Cite exact materialized source lines for material factual claims.

When results are truncated:

```text
not visible in returned rows != not present in source
```

# RetrievalSession boundary

RetrievalSession may remember evidence identities, covered ranges, request fingerprints, source generations, and mechanical novelty/progress. It does not know the Agent's hypothesis, root cause, causal relationships, importance, sufficiency, answer obligations, or stopping decision.

Search success does not validate a hypothesis. Frequency does not imply causal importance. Structural similarity does not imply the same root cause. Integrity verification does not verify a diagnosis.

# Controlled TraceCite-only mode

A Host may expose only TraceCite evidence operations. This changes the evidence channel, not the reasoning owner. The Agent still chooses answer obligations, questions, queries, ranges, comparisons, hypotheses, conclusions, and stopping.

# What TraceCite mechanics do NOT imply

```text
search match              != causal proof
search rank               != causal importance
signal/navigation hint    != diagnosis recommendation
frequency/cluster size    != importance
same identifier           != safe correlation
nearby/file-ordered lines != causal/event ordering
status=ok                 != hypothesis supported
status=no_match           != global absence
status=no_new_evidence    != no useful evidence exists
new lines/evidence        != discriminating information
routing/coverage metadata != semantic importance
```

# Recommended Agent investigation loop

```text
1. Extract the small set of material answer obligations from the user's request.
2. Choose one open/contradicted obligation and emit a short ROUND: O / Δ / T line.
3. Retrieve only the evidence needed for that obligation.
4. Materialize incomplete body/context only when that obligation depends on it; do not loop on an already-covered or empty range.
5. Mark the obligation supported, contradicted, still open, or qualified_boundary.
6. For synchronization failures, close the minimal wait-for graph from representative opposing paths before counting more equivalent waiters.
7. If the same obligation has two non-advancing rounds with no new observed anchor, stop reformulating it and qualify the evidence boundary.
8. Do not create extra obligations for reassurance, completeness, curiosity, or hypothetical alternatives unsupported by observed evidence.
9. As soon as every explicit answer obligation is supported or appropriately qualified and no observed contradiction remains, transition directly to the final answer with no intermediate verification/meta-planning turn.
```

TraceCite's job is to make the evidence recoverable, bounded, line-addressable, provenance-preserving, and mechanically non-redundant.
The Agent's job is to understand what that evidence means and decide when enough has been learned.
