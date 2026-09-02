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

# Material answer state

Keep the reasoning state small. Track only the material claims needed to answer the user:

```text
observed             directly supported by materialized evidence
inference_supported  reasoned from observed evidence and explicitly qualified
unresolved           an observable fact could still materially change the answer
out_of_scope         would require evidence that was not supplied
```

Do not promote absence of a match into proof of absence. Do not invent missing facts merely to complete a preferred mechanism.

A candidate answer exists once the requested material claims can be stated from `observed` and properly qualified `inference_supported` evidence.

# Before a candidate answer: retrieve only for a material unresolved fact

Before every exploratory TraceCite call, keep one short internal/trajectory line:

```text
VOI: Q=<one unresolved material fact>; Δ=<a plausible observation that would materially change/refute/distinguish the answer>; T=<specific query or range that can observe it>
```

A call is justified only when all three are real:

- `Q` is still needed for a material claim;
- `Δ` names a plausible conclusion-changing observation, not merely “more confidence”;
- `T` targets supplied evidence that can actually observe `Q`.

These are not valid reasons to call TraceCite:

```text
look for more evidence
confirm the hypothesis
check another example
see what else is present
be extra sure
final verification
one more quick check
```

A call that can only produce another instance of an already-established fact has no decision value unless multiplicity, frequency, variation, scope, or ordering is itself material to the answer.

# After a candidate answer: qualified-patience stopping

Once a candidate answer exists, ordinary exploration ends. Further TraceCite calls are allowed only as **qualified challenges** to that candidate answer.

A qualified challenge must satisfy all of the following:

1. it targets a material vulnerability of the current answer: a critical causal link, a material qualification, a contradiction, or a materially different competing explanation;
2. at least one plausible result would materially change, refute, narrow, or re-qualify the current answer;
3. the supplied evidence can actually observe that result;
4. it is distinct from earlier challenges: not a synonym search, another equivalent instance, or a repeat of the same causal edge;
5. its target is bounded enough that the result can be interpreted as a real test rather than an open-ended survey.

Track only:

```text
qualified_stability = number of consecutive distinct qualified challenges
                      that leave the material answer unchanged
```

Rules:

- A qualified challenge that materially changes the answer resets `qualified_stability = 0` and returns the Agent to normal investigation.
- A qualified challenge that reveals a contradiction resets `qualified_stability = 0` and the contradiction must be resolved or explicitly qualified.
- A distinct qualified challenge that leaves the material answer unchanged increments `qualified_stability += 1`.
- Confirmation-only, duplicate, curiosity, broad-survey, citation-repair, and synonymous no-match calls do **not** increment `qualified_stability`; normally they should not be made at all.
- Do not manufacture challenges merely to reach a quota. If a proposed challenge is not observable in supplied evidence, mark that boundary `out_of_scope` rather than searching indefinitely.
- After **2 consecutive distinct qualified challenges** leave the material answer unchanged, stop and answer.

The purpose of patience is not “two more searches.” It is to give a formed answer two genuine opportunities to be changed by supplied evidence.

# What counts as a distinct challenge

Prefer challenges that attack different failure modes in the current answer, for example:

- test the weakest material causal link for contradictory evidence;
- test whether supplied evidence supports a materially different explanation that would change the answer;
- test a material scope/order/state assumption whose opposite would change the conclusion.

Do not force all of these categories. Use only challenges that are material and observable in the supplied artifact.

The following do not count as distinct challenges:

```text
same query with different wording
same stack/path at another occurrence
another count of an already-established population
another materialization of an already-covered body
another search whose only possible value is reassurance
```

Fresh lines are not automatically a fresh challenge. New evidence identity is not automatically new semantic information.

# Evidence correctness

- In TraceCite-only mode, do not retry blocked native `read`/`grep`/`find`/`ls`/shell evidence access.
- Once a `follow_up_file`, `source_path`, or immutable source identity is known, reuse it instead of rediscovering the same source.
- Search previews may omit multi-line record bodies. If a material conclusion depends on a complete stack, traceback, exception, record, or surrounding context, materialize the bounded body first.
- Navigation/signal hints are recovery coordinates, not evidence of causal importance, and are not observed body evidence until materialized.
- `matched_existing_evidence`, covered ranges, repeated evidence, and `status=no_new_evidence` are mechanical facts. Do not refetch the same body simply to confirm it exists.
- `status=no_match` applies to the exact retrieval request; it is not automatically proof of global absence.
- Captured line order is not automatically event time, execution order, happens-before, lock acquisition order, or causality.
- Reuse source SHA/immutable identity when available.
- Cite exact materialized source lines for material factual claims.

A current stack does not enumerate all prior state:

```text
not visible as a current frame != proven never acquired/performed
present in a call path          != proven currently held/active
```

When results are truncated:

```text
not visible in returned rows != not present in source
```

# RetrievalSession boundary

RetrievalSession may remember evidence identities, covered ranges, request fingerprints, source generations, and mechanical novelty/progress. It does not know the Agent's hypothesis, root cause, causal relationships, importance, sufficiency, or stopping decision.

Search success does not validate a hypothesis. Frequency does not imply causal importance. Structural similarity does not imply the same root cause. Integrity verification does not verify a diagnosis.

# Controlled TraceCite-only mode

A Host may expose only TraceCite evidence operations. This changes the evidence channel, not the reasoning owner. The Agent still chooses questions, queries, ranges, comparisons, hypotheses, conclusions, challenges, and stopping.

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
1. Define the few material claims the user's answer requires.
2. Before a candidate answer exists, choose one material unresolved Q and use the short Q / Δ / T gate.
3. Retrieve only enough evidence to resolve or materially update that Q.
4. Materialize incomplete body/context only when the material claim depends on it.
5. Update the material claims and separate observation from inference.
6. Once a candidate answer exists, stop ordinary exploration.
7. Permit only distinct qualified challenges whose plausible outcomes could materially change that answer.
8. If a qualified challenge changes the answer or reveals contradiction, reset stability and investigate the changed material claim.
9. If a qualified challenge leaves the material answer unchanged, increment qualified stability.
10. After 2 consecutive distinct qualified challenges leave the material answer unchanged, answer immediately.
11. Confirmation-only or duplicate retrieval never counts as stability and should not be used as a substitute for a real challenge.
12. If a needed fact is not observable in supplied evidence, state the boundary rather than searching indefinitely.
```

TraceCite's job is to make the evidence recoverable, bounded, line-addressable, provenance-preserving, and mechanically non-redundant.
The Agent's job is to understand what that evidence means and decide when enough has been learned.
