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
4. Materialize incomplete body/context only when that obligation depends on it.
5. Mark the obligation supported, contradicted, still open, or qualified_boundary.
6. If the same obligation has two non-advancing rounds with no new observed anchor, stop reformulating it and qualify the evidence boundary.
7. Do not create extra obligations for reassurance, completeness, curiosity, or hypothetical alternatives unsupported by observed evidence.
8. As soon as every explicit answer obligation is supported or appropriately qualified and no observed contradiction remains, answer immediately.
```

TraceCite's job is to make the evidence recoverable, bounded, line-addressable, provenance-preserving, and mechanically non-redundant.
The Agent's job is to understand what that evidence means and decide when enough has been learned.
