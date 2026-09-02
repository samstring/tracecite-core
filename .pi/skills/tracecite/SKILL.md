---
name: tracecite
description: Use TraceCite as an evidence transport and evidence-memory layer. TraceCite retrieves and materializes evidence with provenance; the Agent owns interpretation, hypotheses, causality, sufficiency, root cause, and stopping.
compatibility: Requires the TraceCite Pi extension. Canonical tools are tracecite_retrieve, tracecite_materialize, tracecite_replay, tracecite_aggregate, tracecite_traverse, and tracecite_verify. tracecite_search/tracecite_expand may be exposed as compatibility aliases.
---

# TraceCite Evidence Runtime in Pi

```text
TraceCite = evidence retrieval + bounded materialization + provenance + mechanical memory
Agent     = interpretation + comparison + hypothesis + causality + sufficiency + stopping
```

TraceCite runtime never chooses a hypothesis, investigation direction, root cause, or stop decision.

# Mandatory adaptive call gate

Treat every additional TraceCite call as a cost that must buy discriminating information. Do not use a fixed number of investigation rounds as the normal stopping rule.

**Before every TraceCite call, the Agent must be able to answer all three questions internally:**

```text
Q — What exact material fact is still unresolved?
Δ — What plausible result of this call would materially change, contradict, distinguish, or refine the conclusion?
T — What specific source/query/range can observe that result?
```

If `Q`, `Δ`, or `T` cannot be stated concretely, do not make the call. Synthesize the evidence already obtained and answer.

Generic goals do not pass the gate:

```text
look for more evidence
confirm the hypothesis
check a few more examples
be extra sure
see what else is there
```

After every call, classify what it added:

```text
discriminating -> changes or resolves a material question
confirming      -> another instance of an already-established fact/structure
duplicate       -> repeated/covered/no-new evidence
```

Only `discriminating` evidence normally creates a reason for another investigation step. `confirming` or `duplicate` evidence does not justify a semantically equivalent follow-up unless multiplicity, frequency, variation, scope, or ordering itself is the unresolved fact.

If the Agent has already thought or said that the mechanism/path/pattern is "clear", "complete", "established", or equivalent, another retrieval requires a newly stated material unresolved fact and a plausible conclusion-changing outcome. Otherwise answer now.

# Claim-closure stopping rule

Track the material claims requested by the user, not the amount of searchable text.

For each material claim, determine whether it is:

```text
observed             -> directly supported by materialized evidence
inference_supported  -> reasoned from observed evidence and explicitly qualified
unresolved           -> could materially change the answer and is observable in supplied evidence
out_of_scope         -> requires an artifact that was not supplied
```

Stop normal retrieval when:

1. the material claims needed for the answer are observed or clearly qualified as supported inference; and
2. no remaining observable `unresolved` fact has a plausible outcome that would materially change the conclusion.

The existence of more files, rows, matches, stacks, examples, or context is not itself an unresolved fact.

For diagnostic tasks, a list of blocked stacks is not enough when the question asks for a mechanism. The final synthesis should explicitly state the smallest synchronization/failure mechanism supported by the observed competing paths and explain the requested impact. Once those material claims have exact support, do not keep collecting equivalent examples merely to increase volume.

# Diminishing returns

TraceCite may expose mechanical novelty/progress such as new/repeated evidence, new lines, covered ranges, or `status=no_new_evidence`.

Low-return signals include:

- repeated evidence dominating results;
- zero or tiny new-line growth;
- repeated materialization of covered context;
- repeated equivalent `no_match` queries;
- another instance of an already-established structure;
- aggregate/replay/verify calls that do not resolve the current `Q`.

These signals do not semantically order the Agent to stop. They make a fresh `Q/Δ/T` gate mandatory before another call.

Low novelty alone never overrides correctness. If a concrete observable fact could materially change the conclusion, retrieve it. Conversely, new lines alone are not evidence that another call has value.

```text
new lines             != new semantic information
new evidence identity != discriminating evidence
more instances        != stronger causal proof by default
```

# Do not manufacture missing pieces

Do not search for an actor, owner, state, event, component, or function merely because the current hypothesis predicts it.

Before searching for a hypothesized missing piece, require both:

1. observing/refuting it would materially change the conclusion; and
2. the supplied evidence can actually establish it.

If a required fact needs source code, telemetry, metrics, traces, or another artifact not supplied, state that evidence boundary instead of repeatedly searching the same artifact.

# Hard budgets

Host call/token/time limits are safety rails against runaway investigation, not normal semantic stopping rules. If a hard limit is reached while a material fact remains unresolved, state the limitation rather than pretending the evidence is sufficient.

# Evidence-use correctness contract

- In TraceCite-only mode, do not retry blocked native `read`/`grep`/`find`/`ls`/shell evidence access.
- Once `follow_up_file`, `source_path`, or immutable source identity is known, reuse it rather than rediscovering the source.
- Search previews may be partial projections of multi-line records. Materialize the bounded body when a conclusion depends on complete stack/traceback/record/state/context structure.
- Navigation/signal hints are recovery coordinates, not causal rankings, and are not observed body evidence until materialized.
- `matched_existing_evidence`, covered ranges, repeated evidence, and `status=no_new_evidence` are mechanical session facts. Do not request the same body merely to confirm it exists.
- `status=no_match` applies only to that exact retrieval request; it is not automatically global absence proof.
- File line order is captured-source order, not automatically event time, execution order, happens-before, lock acquisition order, or causality.
- Reuse source SHA/immutable identity when available so citations remain tied to exact bytes.
- Cite exact materialized source lines for material factual claims.

A current stack does not enumerate all prior state:

```text
not visible as current frame != proven never acquired/performed
present in a call path        != proven currently held/active
```

Establish retained/prior state only from evidence that actually supports it.

When search coverage is truncated:

```text
not visible in returned rows != not present in source
```

# RetrievalSession boundary

RetrievalSession can remember evidence identities, covered ranges, request fingerprints, source generations, and mechanical novelty/progress. It does not know the Agent's hypothesis, root cause, causal relationships, importance, evidence sufficiency, or whether the Agent should stop.

# Canonical operations

```text
tracecite_retrieve      -> retrieve caller-selected evidence
tracecite_materialize   -> expose exact bounded source context
tracecite_replay        -> intentionally revisit covered immutable evidence
tracecite_aggregate     -> deterministic count/distinct/group over selected scope
tracecite_traverse      -> bounded traversal over supplied evidence relations
tracecite_verify        -> mechanical evidence/manifest integrity verification
```

Search success does not validate a hypothesis. Frequency does not imply causal importance. Traversability does not imply causality. Integrity verification does not verify a diagnosis.

Snapshot/evidence refs may be citation identities rather than usable file paths. Prefer explicit `follow_up_file` / `source_path` for later calls and reuse SHA when supported.

# Controlled TraceCite-only mode

A Host may expose only TraceCite evidence operations. This changes the evidence channel, not the reasoning owner. The Agent still chooses questions, queries, ranges, comparisons, hypotheses, conclusions, and stopping.

# What TraceCite mechanics do NOT imply

```text
search match               != causal proof
search rank                != causal importance
signal/navigation hint     != diagnosis recommendation
frequency/cluster size     != importance
structural similarity      != same root cause
same identifier            != safe correlation
nearby/file-ordered lines  != causal/event ordering
status=ok                  != hypothesis supported
status=no_match            != global absence
status=no_new_evidence     != no useful evidence exists
new lines/evidence         != discriminating information
verified integrity         != verified diagnosis
routing/coverage metadata  != semantic importance
```

# Recommended Agent investigation loop

```text
1. Define the material claims the user actually needs.
2. State one concrete unresolved factual question Q.
3. State a plausible outcome Δ that would materially change the answer.
4. Choose a specific TraceCite target T that can observe Δ.
5. Retrieve/materialize only what Q requires.
6. Record the observed fact and separate it from inference.
7. Update claim closure and synthesize before any new call.
8. Do not repeat confirming/duplicate investigation unless multiplicity/variation is itself material.
9. Run Q/Δ/T again; if it fails, answer. If the required fact is unavailable in supplied evidence, state the boundary.
```

TraceCite's job is to make the evidence recoverable, bounded, line-addressable, provenance-preserving, and mechanically non-redundant.
The Agent's job is to understand what that evidence means and decide when enough has been learned.
