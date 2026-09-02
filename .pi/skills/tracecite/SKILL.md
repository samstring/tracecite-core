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

# Execution rule: every retrieval must buy a decision

Before **every** TraceCite call, write one short internal/trajectory line in this form and keep it concrete:

```text
VOI: Q=<one unresolved material fact>; Δ=<a plausible result that would change/refute/distinguish the answer>; T=<specific query or range that can observe it>
```

Do not expand this into a long planning paragraph.

A tool call is allowed only when all three fields are real:

- `Q`: a fact still needed for a material claim in the user's answer;
- `Δ`: at least one plausible observation would materially change the conclusion, distinguish competing explanations, or change how the claim must be qualified;
- `T`: the supplied evidence can actually observe that fact and the call targets it.

If any field is missing, vague, or circular, **do not call TraceCite**. Synthesize and answer.

These do not pass the gate:

```text
look for more evidence
confirm the hypothesis
check another example
see what else is present
be extra sure
final verification
one more quick check
```

A search that can only produce another instance of an already-established fact has no decision value unless multiplicity, frequency, variation, scope, or ordering is itself material to `Q`.

# Claim ledger and closure latch

Track only the material claims the user needs. A claim is one of:

```text
observed             directly supported by materialized evidence
inference_supported  reasoned from observed evidence and explicitly qualified
unresolved           an observable fact could still materially change it
out_of_scope         would require evidence that was not supplied
```

Normal investigation is complete when:

1. the requested material claims are `observed` or properly qualified `inference_supported`; and
2. there is no pre-existing `unresolved` observable fact whose plausible result would materially change the answer.

At that point the **closure latch is set**: answer immediately. Do not perform confirmation-only, completeness, curiosity, summary-verification, or “one more” retrievals.

A confirming or duplicate call **closes its current Q but does not create a new Q**. Another call after confirming/duplicate evidence is allowed only for a different material unresolved claim that already existed before that call.

If, while composing the answer, a material claim lacks an exact materialized citation, a narrowly targeted citation-repair materialization is allowed. Citation repair must fetch only the already-identified range; it must not reopen exploratory search.

If the Agent has already stated or concluded that the mechanism/path/pattern is clear, complete, established, enough, or equivalent, treat that as closure unless it can name a still-unresolved material claim and a concrete conclusion-changing `Δ`.

# Prefer discriminating evidence over surveys

After every call classify the result mentally as:

```text
discriminating  resolves or materially changes Q
confirming      repeats an already-established structure/fact
duplicate       covered / repeated / no-new evidence
```

Only `discriminating` evidence normally advances the causal frontier. Do not turn confirming evidence into a chain of synonym searches or additional examples.

Use exact symbols, identifiers, states, and frames already observed in evidence before broad vocabulary searches. When a narrow observed anchor exists, unrelated broad scans have low information value.

When a retrieval returns many equivalent matches, investigate **structural variants**, not volume. Prefer one bounded retrieval that can reveal distinct call-site/frame variants, then materialize the variant that could change the explanation. Do not enumerate many equivalent instances merely to strengthen confidence.

# Conditional heuristic for blocked/concurrent systems

Use this only when supplied evidence actually shows blocking, lock contention, waits, or repeated stuck execution paths.

1. Establish one representative blocked path with exact materialized frames.
2. If many instances stop at the same synchronization point, treat their repetition as population evidence, not as a reason to inspect each instance.
3. Search the same observed function/path for the **structurally deepest-progressed variant**: an instance that has advanced past the shared blocking frame or is stopped at a different downstream wait.
4. Materialize that downstream path and identify what resource/state it is waiting for, without inferring unseen ownership.
5. Look for a competing observed path only when its presence/absence could distinguish a cycle, ordering conflict, starvation, external wait, or another mechanism.
6. Once the minimal competing paths and user-visible impact are supported, set the closure latch. Do not survey unrelated goroutine classes or lifecycle operations unless they are a material alternative explanation.

For a synchronization/root-cause answer, the useful unit is the smallest evidence-supported mechanism plus the paths that establish it, not the number of matching stacks.

# Diminishing returns

Mechanical TraceCite signals such as `new_evidence`, new lines, repeated evidence, covered ranges, and `status=no_new_evidence` are evidence-session facts, not semantic stop commands.

Repeated low-return outcomes force a new VOI gate before any call:

- repeated evidence dominates;
- zero/tiny new-line growth;
- the same context is materialized again;
- equivalent `no_match` queries are being reformulated;
- the call adds another equivalent instance;
- the call does not change the claim ledger.

Low novelty does not justify stopping if a concrete observable fact could still change the answer. Conversely, fresh lines do not justify continuing if they cannot change a material claim.

```text
new lines             != new semantic information
new evidence identity != discriminating evidence
more instances        != stronger causal proof by default
```

# Do not manufacture missing evidence

Do not make an actor, owner, function, event, state, component, or code path a mandatory target merely because the current hypothesis predicts it.

Search for a hypothesized missing piece only when:

1. observing or refuting it would materially change the answer; and
2. the supplied artifact can actually establish it.

If the fact requires source code, telemetry, metrics, traces, another log, or an artifact not supplied, mark it `out_of_scope` and state the boundary rather than repeatedly searching the same evidence.

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

A Host may expose only TraceCite evidence operations. This changes the evidence channel, not the reasoning owner. The Agent still chooses questions, queries, ranges, comparisons, hypotheses, conclusions, and stopping.

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
2. Choose one unresolved claim and emit a short VOI: Q / Δ / T line.
3. Retrieve only the evidence needed for that Q.
4. Materialize incomplete body/context only when the claim depends on it.
5. Update the claim ledger; separate observation from inference.
6. If the result is confirming/duplicate, close that Q; do not spawn an equivalent follow-up.
7. If all material claims are closed, latch closure and answer immediately.
8. Otherwise choose a different remaining material Q and repeat the VOI gate.
9. If the needed fact is not observable in supplied evidence, mark the boundary rather than searching indefinitely.
```

TraceCite's job is to make the evidence recoverable, bounded, line-addressable, provenance-preserving, and mechanically non-redundant.
The Agent's job is to understand what that evidence means and decide when enough has been learned.
