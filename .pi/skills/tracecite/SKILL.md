---
name: tracecite
description: Use TraceCite as a bounded evidence transport and mechanical evidence-memory layer. TraceCite retrieves/materializes evidence with provenance; the Agent owns interpretation, causality, sufficiency, root cause, and stopping.
compatibility: Requires the TraceCite Pi extension. tracecite_search/tracecite_expand may be exposed as compatibility aliases for retrieval/materialization.
---

# TraceCite evidence contract

```text
TraceCite = retrieve + materialize + provenance + mechanical evidence memory
Agent     = interpret + infer + decide sufficiency + stop
```

Runtime does not choose hypotheses, causal importance, root cause, investigation direction, or stopping. Token saving never overrides correctness.

# 1. Minimal answer obligations

Extract only the material **answer obligations** required by the user's question. Track each internally as `open`, `supported`, `contradicted`, or `qualified_boundary`.

A TraceCite call is justified only to:
- resolve one `open` or `contradicted` obligation; or
- materialize an already-identified range required for a material claim.

**One evidence round = one obligation.** Prefer one narrow retrieval plus the minimum bounded materialization. Do not create new obligations for reassurance, curiosity, completeness, extra examples, or confidence after the requested answer is already supported.

For the same obligation, duplicate/equivalent evidence, synonymous no-match results, or already-covered context are non-advancing. After **2 consecutive non-advancing rounds**, stop reformulating that obligation and use the strongest supported qualification or `qualified_boundary`.

# 2. Minimal causal closure

For every material root-cause claim, identify the **minimum causal edges that must be true** for that claim to hold. An obligation is not `supported` while a required causal edge is missing or contradicted.

Use the smallest sufficient evidence packet:

```text
mechanism edge(s) + impact edge + no material contradiction
```

Do not substitute evidence volume for causal closure. More matches, more examples, more waiters, or repeated variants do not strengthen a claim unless they resolve a missing/contradicted edge.

When an edge cannot be established from the supplied artifact, mark the boundary instead of inventing hidden behavior. A qualified answer is better than a complete-sounding unsupported story.

# 3. Observation versus inference

For material causal statements distinguish:

```text
observed = directly present in materialized evidence
inferred = follows from observed paths/ordering but is not directly visible
unknown  = not established by supplied evidence
```

Do not treat:

```text
not visible now      == never happened
present in call path == currently held/active
file/line order      == happens-before/event time
search match         == causal proof
frequency/rank       == causal importance
```

Final claims may use inference, but the inference must be supported by observed evidence and must not be presented as direct observation.

# 4. Synchronization evidence semantics

For blocking/contention/deadlock questions, build the **minimal wait-for graph** needed to distinguish the mechanism.

A blocked `Lock`, `RLock`, semaphore acquire, condition wait, channel receive/send, or equivalent means execution is **waiting at that operation**. It does not prove that the goroutine already holds the object it is trying to acquire.

Infer an outer hold only when evidence establishes that execution progressed past that outer acquisition into a nested blocked call, or supplied source/context establishes the critical-section boundary.

For a candidate lock-ordering cycle require both edges:

```text
path A: held A -> waits B
path B: held B -> waits A
```

**A missing cycle edge keeps the root-cause obligation open.** One blocked lock, one nested edge, or many waiters is not enough to claim deadlock.

Once **one strongest representative stack** supports each opposing path and the impact path is supported, close the mechanism unless evidence contradicts an edge. Use **representative evidence over exhaustive census**.

# 5. Final-answer evidence discipline

The final answer must contain only claims already covered by closed answer obligations or clearly marked boundaries. **Do not introduce a new causal claim in the final answer.**

For root-cause questions, open with one compact sentence naming the **failure mechanism/class and affected subsystem/component**, then give only the minimum causal chain and impact needed to support it.

Do not add plausible but unsupported **hidden process-management behavior**, cleanup/reaping behavior, restart side effects, historical ownership, kernel behavior, or lifecycle details. **Omit unsupported lifecycle extrapolation.** A correct root-cause answer is preferable to a broader speculative answer.

# 6. Terminal answer transition

After each evidence batch make exactly one decision:

```text
open/contradicted obligation remains -> retrieve only for that obligation
all obligations closed               -> the next assistant action is the final answer
```

There is **no intermediate verification/meta-planning turn** after closure. **A terminal declaration is a commitment**: after concluding that evidence is sufficient, do not make another evidence call unless a specific open/contradicted obligation is identified.

If no obligation is open or contradicted, **answer immediately**.

# Evidence correctness and token discipline

- In TraceCite-only mode, do not retry blocked native evidence tools.
- Reuse known evidence refs, ranges, source paths, source SHAs, and immutable source identities.
- Search previews may omit multi-line bodies; materialize only the bounded body needed for a material claim.
- Navigation hints are coordinates, not causal evidence.
- `status=no_match` is request-local, not global absence.
- `status=no_new_evidence`, matched-existing evidence, duplicate requests, and covered ranges are mechanical facts; do not refetch them for confidence.
- If a materialization is empty/already covered, **do not repeatedly retry adjacent lines**, radius changes, or synonyms. Use one alternate concrete coordinate only when newly observed output supplies it and an explicit obligation still needs it.
- Prefer one representative instance per distinct causal role over enumerating equivalent instances.
- Cite exact materialized lines for material factual claims.

# RetrievalSession boundary

RetrievalSession may remember evidence identities, ranges, request fingerprints, source generations, novelty, coverage, and repeated evidence. It does not know hypotheses, causality, importance, answer obligations, root cause, sufficiency, or stopping.

# Controlled TraceCite-only mode

A Host may expose only TraceCite evidence operations. This changes the evidence channel, not the reasoning owner.

# Recommended Agent investigation loop

```text
1. Extract the smallest set of answer obligations.
2. Pick one open/contradicted obligation.
3. Retrieve the minimum evidence for its missing causal edge.
4. Materialize only the body/context needed for that edge.
5. Mark the obligation supported, contradicted, or bounded.
6. Prefer representative evidence; do not census equivalents.
7. After 2 non-advancing rounds on the same obligation, qualify/bound it.
8. When every material obligation is closed, answer immediately.
9. Do not add new causal claims while writing the final answer.
```

TraceCite's job is to make the evidence recoverable, bounded, line-addressable, provenance-preserving, and mechanically non-redundant.
The Agent's job is to understand what that evidence means and decide when enough has been learned.
