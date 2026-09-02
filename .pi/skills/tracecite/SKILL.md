---
name: tracecite
description: Use TraceCite as an evidence transport and evidence-memory layer. TraceCite finds, bounds, materializes, remembers, and verifies evidence with provenance; the Agent decides hypotheses, causality, sufficiency, root cause, and when to stop.
compatibility: Requires the TraceCite Pi extension. Canonical tools are tracecite_retrieve, tracecite_materialize, tracecite_replay, tracecite_aggregate, tracecite_traverse, and tracecite_verify. tracecite_search/tracecite_expand may be exposed as compatibility aliases.
---

# TraceCite Evidence Runtime in Pi

TraceCite is evidence infrastructure, not a diagnostic authority.

```text
TraceCite = retrieve + bound + materialize + provenance + evidence memory
Agent     = interpret + compare + hypothesize + infer + decide sufficiency + stop
```

TraceCite must not be treated as having chosen a hypothesis, causal mechanism, next investigation direction, or stop decision.

# Evidence-use contract

Use TraceCite efficiently without weakening correctness:

- In TraceCite-only mode, do not retry blocked native `read`/`grep`/`find`/`ls`/shell evidence access. Resolve the source through TraceCite and reuse the returned source/follow-up identity.
- Once `follow_up_file`, `source_path`, or immutable source identity is known, reuse it instead of rediscovering the same source.
- Search previews can be partial projections of multi-line records. If a conclusion depends on a complete stack, traceback, record, state, or surrounding context, materialize the necessary bounded range before concluding.
- Navigation hints and signal hints are coordinates for recovering source text. They are not evidence until materialized and are not relevance or causal rankings.
- `matched_existing_evidence`, repeated evidence, covered ranges, and `status=no_new_evidence` are mechanical session facts. Do not request the same body again merely to confirm it still exists.
- `status=no_match` describes only that exact retrieval request. It is not automatically proof that an event or representation is globally absent.
- Source line order is captured-file order, not automatically event time, execution order, happens-before, lock order, or causality.
- Reuse source SHA/immutable identity when available so citations remain tied to exact bytes.
- Exact materialized source text is evidence. Retrieval metadata, routing, novelty, coverage, hint selection, and tool telemetry are mechanics rather than causal conclusions.

Saving tokens never overrides correctness. If an unresolved fact could materially change the conclusion, investigate it even when novelty is low or the investigation is already expensive.

# Adaptive stopping: value of information

Do not use a fixed investigation-round count as the normal stopping rule. Before each additional TraceCite call, apply a value-of-information check.

## 1. Name the unresolved fact

A new call must answer a concrete unresolved factual question. Avoid goals such as:

```text
look for more evidence
confirm the hypothesis
search for anything else
be extra sure
```

Prefer a question whose answer could distinguish, contradict, refine, or materially change the current explanation.

## 2. Test whether the next call can change the conclusion

Before retrieving, consider the materially different plausible outcomes of that call.

```text
If outcome A is observed, what changes?
If outcome B / absence / contradiction is observed, what changes?
```

Continue only when at least one plausible outcome would materially affect the conclusion, confidence, competing explanation, or required evidence boundary.

If every plausible outcome would leave the material conclusion unchanged, the expected information value is too low for another retrieval. Synthesize and answer instead.

This is an Agent decision. TraceCite does not calculate semantic value of information and does not tell the Agent to stop.

## 3. Distinguish novelty from discriminating evidence

```text
new source lines      != new semantic information
new evidence identity != evidence that changes the explanation
more matching instances != stronger causal proof by default
```

Additional instances of an already-established structure are useful only when multiplicity, frequency, scope, ordering, or variation itself matters to the unresolved question.

Once fully materialized evidence already establishes a mechanism, do not continue simply because more text remains searchable.

## 4. Use diminishing returns as a reassessment trigger

Mechanical low-novelty signals include:

- `status=no_new_evidence`;
- repeated evidence dominating results;
- zero or very small new-line growth;
- repeated materialization of covered context;
- repeated equivalent `no_match` retrievals;
- aggregate/replay/verify operations that do not expand the evidence needed by the unresolved question;
- consecutive calls that add observations but no materially different structure.

One low-novelty result is not a semantic stop signal. Repeated low-novelty results mean: synthesize what is already established and rerun the value-of-information check before another call.

Do not automatically stop merely because novelty is low. A specific unresolved fact that can materially change the conclusion still justifies retrieval.

## 5. Do not manufacture missing pieces from a hypothesis

Do not turn an actor, owner, state, event, or component into a mandatory search target only because the current hypothesis predicts it.

Before searching for a hypothesized missing piece, ask:

1. Would observing or refuting it materially distinguish explanations or change the conclusion?
2. Is that fact observable in the supplied evidence at all?
3. Does the already-observed evidence support a complete explanation without assuming that missing piece?

If the required fact needs source code, telemetry, metrics, traces, or another artifact not supplied, state that evidence boundary instead of repeatedly searching the same source.

## 6. Hard budgets are safety rails, not normal stopping logic

A Host may impose maximum calls, tokens, output, or wall-clock limits to prevent runaway investigations. Treat those as safety bounds.

Normal stopping should come from evidence sufficiency and value of information, not from reaching an arbitrary turn number. If a hard budget is reached while a material fact remains unresolved, state the limitation rather than pretending the evidence is sufficient.

# Evidence visibility rules

## Search previews are not complete logical records

For stacks, goroutine dumps, tracebacks, crash reports, multi-line exceptions, and multi-line logs, a one-line preview may hide the structure required for interpretation.

Do not infer unseen frames, held resources, prior operations, nested state, or surrounding record content from a preview. Materialize the bounded source range when that hidden structure matters.

A current stack also does not enumerate all previously acquired state:

```text
not visible as a current frame != proven never acquired / performed
present in a call path          != proven currently held / active
```

Establish retained/prior state only from evidence that actually supports it.

## Truncated results are subsets

When coverage reports truncation, visible rows are a bounded subset of matches.

```text
not visible in returned rows != not present in source
```

Signal/navigation hints can preserve structurally different source regions omitted from inline rows, but those hints do not establish semantic importance.

# RetrievalSession semantics

RetrievalSession is evidence memory, not reasoning memory. It may track:

- evidence identities already exposed;
- covered immutable/source-generation ranges;
- request fingerprints;
- source generations;
- new/repeated/replay/no-match outcomes;
- line/evidence novelty and coverage.

It does not know:

- the Agent's hypothesis;
- root cause;
- causal relationships;
- which observation matters;
- whether evidence is sufficient;
- whether the Agent should stop.

`status=no_new_evidence` means the operation did not expand the tracked evidence frontier under the session rules. It does not mean the source is empty, the hypothesis is correct, or no useful evidence exists elsewhere.

# Canonical operations

```text
tracecite_retrieve      -> retrieve caller-selected evidence
tracecite_materialize   -> expose exact bounded source context
tracecite_replay        -> intentionally revisit already-covered immutable evidence
tracecite_aggregate     -> deterministic count/distinct/group over caller-selected scope
tracecite_traverse      -> bounded traversal over supplied evidence relations
tracecite_verify        -> mechanical evidence/manifest integrity verification
```

Compatibility aliases may map `tracecite_search` to retrieval and `tracecite_expand` to materialization/replay.

Search success means evidence matched; it does not mean a hypothesis was validated. Aggregate frequency does not imply causal importance. Traversability does not imply causality. Integrity verification does not verify a diagnosis.

# Source identity and citations

Snapshot/evidence refs are citation identities and may not be usable filesystem paths. For later TraceCite calls, prefer explicit `follow_up_file` / `source_path`; reuse SHA when supported.

Cite exact materialized source lines for material factual claims. Keep observed facts separate from inference:

```text
supported            = directly established by observed evidence
inference_supported  = reasoned from observed evidence
unsupported_from_log = requires evidence not supplied
```

Qualify inference rather than presenting it as directly observed.

# Controlled TraceCite-only mode

A Host may expose only TraceCite evidence operations. That changes the evidence channel, not the reasoning owner.

The Agent still chooses questions, queries, ranges, comparisons, hypotheses, conclusions, and stopping. TraceCite runtime must remain evidence/transport/mechanical only.

# What TraceCite mechanics do NOT imply

```text
search match                 != causal proof
search rank                  != causal importance
signal/navigation hint       != diagnosis recommendation
cluster/frequency            != importance
structural similarity        != same root cause
same identifier              != safe correlation
nearby/file-ordered lines    != causal/event ordering
status=ok                    != hypothesis supported
status=no_match              != global absence
status=no_new_evidence       != no useful evidence exists
new lines/evidence           != discriminating information
verified evidence integrity  != verified diagnosis
routing/coverage metadata    != semantic importance
```

# Recommended Agent investigation loop

```text
1. State one concrete unresolved factual question.
2. Retrieve evidence targeted at that question.
3. Materialize any incomplete range whose actual body matters.
4. Record the observed fact and distinguish it from inference.
5. Synthesize it with already-established evidence before another call.
6. Ask what plausible result of the next call could materially change.
7. Continue only if such a discriminating result exists and is observable in supplied evidence.
8. Treat repeated low novelty as a reason to reassess, not an automatic stop.
9. Stop when no unresolved observable fact has enough value of information to change the material conclusion; otherwise state the evidence boundary if the required artifact is unavailable.
```

TraceCite's job is to make the evidence recoverable, bounded, line-addressable, provenance-preserving, and mechanically non-redundant.
The Agent's job is to understand what that evidence means and decide when enough has been learned.
