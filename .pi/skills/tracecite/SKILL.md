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

TraceCite runtime never chooses a hypothesis, root cause, investigation direction, semantic importance, or stop decision. Token saving never overrides correctness.

# Highest-priority stopping rule: answer obligations

Extract only the material **answer obligations** required by the user's question. Keep them small and concrete. Track each internally as `open`, `supported`, `contradicted`, or `qualified_boundary`.

A TraceCite call is justified only to:
1. resolve an `open` obligation;
2. resolve a `contradicted` obligation; or
3. materialize an already-identified range needed for a material claim.

If no obligation is open or contradicted, **answer immediately**. Do not create new obligations for confidence, curiosity, completeness, extra examples, or hypothetical unknowns unsupported by observed evidence.

# Terminal answer transition

After each evidence batch make one transition:

```text
open/contradicted obligation remains
    -> retrieve only for that obligation

all explicit obligations are supported/qualified and no observed contradiction remains
    -> the next assistant action is the final answer
```

There is **no intermediate verification/meta-planning turn** after closure. A terminal declaration is a commitment: if you say or conclude "I have enough", "complete picture", "confirmed", "finalize", or equivalent, do not attach another tool call in that turn and do not start another evidence round unless you first identify a still-open or contradicted explicit answer obligation.

For root-cause questions, open the final answer with one compact sentence containing the **failure mechanism/class and the affected subsystem or component**.

# One evidence round = one obligation

**One evidence round = one obligation.** Keep the target internal; do not narrate a planning essay. Prefer one narrow search plus the minimum bounded materialization needed to resolve that obligation. Parallel calls are acceptable only for distinct anchors of the same obligation.

After the batch, update the obligation before making another call.

For the same obligation, a round is non-advancing when it yields only duplicate evidence, equivalent instances, synonymous no-match results, already-covered context, or no material change. After **2 consecutive non-advancing rounds**, stop reformulating that search and either use the best supported qualification or mark `qualified_boundary`. A new synonym is not a new anchor.

# Observation versus inference

Keep these distinctions explicit:

```text
not visible as a current frame != proven never acquired/performed
present in a call path          != proven currently held/active
captured line order             != happens-before or event time
```

A snapshot can support a causal or synchronization inference without directly exposing historical ownership. State the inference and its evidence rather than repeatedly searching for invisible history.

# Synchronization evidence semantics

When investigating blocking, contention, deadlock, or synchronization failure, build the **minimal wait-for graph** needed to distinguish the mechanism.

A blocked `Lock`, `RLock`, semaphore acquire, condition wait, channel receive/send, or equivalent means execution is **waiting at that operation**. It does not prove that the goroutine already holds the object it is trying to acquire.

A goroutine may still hold an outer resource acquired earlier. Infer an outer hold only when evidence establishes that execution progressed past that outer acquisition into a nested call that is now blocked, or when supplied source/line context establishes the critical-section boundary. If that ordering cannot be established, keep it qualified.

For a candidate lock-ordering cycle, require both causal edges:

```text
path A: held resource A -> waits for resource B
path B: held resource B -> waits for resource A
```

**A missing cycle edge keeps the root-cause obligation open.** A hotspot, many waiters, one blocked lock, or one nested-lock edge is not enough to close a deadlock/root-cause claim. If one edge is missing, the next retrieval must target exactly that missing edge or establish an evidence boundary. Do not fill the missing edge with a speculative long-held lock, stalled I/O, lifecycle event, or unknown holder when the supplied evidence exposes another synchronization object/path that can discriminate the explanation.

Do not call ordinary contention a deadlock merely because many goroutines share a waiter. Conversely, once **one strongest representative stack** supports each distinct opposing path and the impact path is supported, close the synchronization mechanism unless observed evidence contradicts an edge. Use **representative evidence over exhaustive census**; more equivalent waiters, counts, adjacent stacks, repeated lock-address searches, or alternate search terms are not additional answer obligations.

# Final-answer evidence discipline

For material causal statements distinguish:

```text
observed   directly present in materialized evidence
inferred   follows from observed paths but is not directly visible
unknown    not established by supplied evidence
```

Do not add plausible but unsupported **hidden process-management behavior**, cleanup/reaping behavior, restart side effects, historical ownership, kernel behavior, or lifecycle details merely to make the story complete. If the requested conclusion does not need them, omit them. If a necessary link exceeds the artifact, qualify it.

**A correct root-cause answer is preferable** to a broader answer with speculative claims. In the final answer, **omit unsupported lifecycle extrapolation**.

# Evidence correctness

- In TraceCite-only mode, do not retry blocked native `read`/`grep`/`find`/`ls`/shell evidence access.
- Reuse known `follow_up_file`, source path, source SHA, or immutable source identity instead of rediscovering it.
- Search previews may omit multi-line bodies. Materialize the bounded body before relying on a complete stack/record.
- Navigation hints are coordinates, not causal evidence.
- `status=no_match` applies only to that request; it is not global absence.
- `status=no_new_evidence`, matched-existing evidence, and covered ranges are mechanical facts; do not refetch them for confidence.
- If materialization for the same evidence/range is empty or already covered, **do not repeatedly retry adjacent lines**, radius changes, or synonymous searches. One alternate concrete coordinate is reasonable only if newly observed output supplies it and an explicit obligation still needs the body.
- Cite exact materialized lines for material factual claims.

# RetrievalSession boundary

RetrievalSession may remember evidence identities, ranges, request fingerprints, source generations, novelty, and coverage. It does not know hypotheses, causal relationships, importance, answer obligations, root cause, sufficiency, or stopping.

```text
search match              != causal proof
search rank               != causal importance
frequency/cluster size    != importance
same identifier           != safe correlation
nearby/file-ordered lines != causal/event ordering
status=ok                 != hypothesis supported
status=no_match           != global absence
new evidence              != discriminating information
```

# Controlled TraceCite-only mode

A Host may expose only TraceCite evidence operations. This changes the evidence channel, not the reasoning owner. The Agent still chooses questions, queries, comparisons, hypotheses, conclusions, and stopping.

# Recommended Agent investigation loop

```text
1. Extract the small set of material answer obligations.
2. Pick one open/contradicted obligation.
3. Retrieve the minimum evidence needed for it.
4. Materialize only required incomplete body/context.
5. Update the obligation state.
6. For synchronization failures, do not close root cause until every required wait-for edge is supported or explicitly bounded.
7. Stop reformulating after 2 consecutive non-advancing rounds for the same obligation.
8. Do not create reassurance/completeness obligations.
9. When all obligations are closed and no contradiction remains, answer immediately; no extra tool call after a terminal declaration.
10. Keep the final answer within observed evidence plus clearly qualified inference.
```

TraceCite's job is to make the evidence recoverable, bounded, line-addressable, provenance-preserving, and mechanically non-redundant.
The Agent's job is to understand what that evidence means and decide when enough has been learned.
