---
name: tracecite
description: Use TraceCite through its canonical Evidence Runtime operations. TraceCite finds, bounds, materializes, remembers, aggregates, traverses, and verifies evidence while preserving source provenance and immutable identity. It may compress or navigate large evidence sets, but it never decides hypotheses, causality, evidence sufficiency, root cause, or when the Agent should stop.
compatibility: Requires the TraceCite Pi extension. Canonical Pi tools are tracecite_retrieve, tracecite_materialize, tracecite_replay, tracecite_aggregate, tracecite_traverse, and tracecite_verify. tracecite_search/tracecite_expand may be exposed as compatibility aliases by some Hosts.
---

# TraceCite Evidence Runtime in Pi

TraceCite is an evidence transport and evidence-memory layer for an Agent.

A useful mental model is:

```text
TraceCite = find evidence + preserve provenance + bound output + expose navigation + remember what was already exposed
Agent     = decide what matters + compare evidence + form hypotheses + infer mechanisms + decide sufficiency + conclude
```

TraceCite can help the Agent see the evidence more clearly. It must not be treated as having already interpreted what the evidence means.

The Agent remains responsible for:

- which question is unresolved;
- which source/query/entity/range to inspect;
- which pieces of evidence should be compared;
- whether two observations are related;
- event ordering when ordering is not explicitly present in the evidence;
- causal reasoning;
- root-cause diagnosis;
- evidence sufficiency;
- the final answer;
- when to stop.

## Non-semantic evidence-use contract

This contract is only about using TraceCite as an evidence channel efficiently and correctly. It is not a diagnosis strategy and must not supply a hypothesis, relationship, root-cause hint, or stop decision.

- If the Host reports that native evidence access is blocked, do not retry equivalent native `read`/`grep`/`find`/`ls`/shell attempts against the protected evidence. Resolve the source through TraceCite and then reuse the returned `follow_up_file` / `source_path` / immutable identity for later calls.
- Once a source identity or usable follow-up path has been returned, reuse it instead of repeatedly rediscovering the same source.
- A search `preview` is not necessarily a complete logical record. Materialize bounded source text only when the unseen body is necessary for the Agent's unresolved question.
- `signal_hints` and navigation ranges are recovery pointers produced by bounded retrieval. They can preserve structural variety omitted from inline rows, but they are not relevance or causal rankings and do not instruct the Agent which hypothesis to pursue.
- Session fields such as `matched_existing_evidence`, `repeated_evidence`, covered ranges, and `no_new_evidence` mean that identity/text has already been exposed under the session rules. Do not request the same body again merely to confirm that it still exists. Revisit old text only when the Agent actually needs the exact prior body for a new comparison; use replay where available.
- After genuinely new materialized Evidence is obtained, the Agent should first synthesize it with already-established Evidence before issuing another retrieval. The next call should exist because a concrete unresolved fact could materially distinguish, contradict, refine, or change the conclusion—not because more text or more matching instances are available.
- Saving tokens must never override correctness. If a specific unresolved fact can materially change the conclusion, low novelty or cost alone is not a reason to stop.

TraceCite itself never decides that these conditions are met. The Agent makes those judgments from the evidence and task.

## Canonical operations

The canonical Evidence Runtime surface is:

```text
tracecite_retrieve      -> retrieve
tracecite_materialize   -> materialize
tracecite_replay        -> replay
tracecite_aggregate     -> aggregate
tracecite_traverse      -> traverse
tracecite_verify        -> verify
```

Compatibility aliases may also be available:

```text
tracecite_search        -> retrieve(QueryTarget(...))
tracecite_expand        -> materialize(...) or replay(...)
```

A Host may expose only a subset or compatibility names. The evidence semantics described below still apply.

# Core evidence model

## Evidence, navigation, and interpretation are different things

TraceCite can return several kinds of information. Do not treat them as interchangeable.

### Materialized/raw Evidence

Source text that TraceCite actually materializes with exact provenance and line locations is evidence that the Agent may inspect and cite.

Interpretation of that text remains the Agent's responsibility.

### Search Evidence

Search results are matched, line-addressable evidence observations. Search success means the requested retrieval matched or exposed evidence. It does not mean a proposition, hypothesis, or causal explanation was validated.

Transport operations normally use:

```text
outcome = not_assessed
```

because retrieval itself does not assess a hypothesis.

### Search previews are not necessarily complete logical records

A search row or Agent-facing `preview` is a retrieval projection around a match. It may expose only the matched line or a bounded summary and does not guarantee that the complete logical record is visible.

This distinction matters for sources whose meaning is carried by multi-line structure, for example:

- goroutine or thread dumps;
- stack traces and native backtraces;
- Python/Java tracebacks;
- crash reports;
- multi-line exceptions;
- multi-line log records or protocol blocks.

Do not assume that two similar one-line previews represent the same complete stack, state, or record shape. Likewise, do not infer what a stack is holding, waiting on, calling, or returning from when those facts are outside the visible preview.

If the conclusion depends on the complete call chain, state, nested resource acquisition, surrounding frames, or another multi-line structure, materialize enough of the source record/range to observe that structure before comparing or concluding.

This is a visibility rule, not a relevance rule: TraceCite is not saying that every matching record must be expanded or that a particular record is important. The Agent decides which records require full materialization for the unresolved question.

### Stack/backtrace visibility does not enumerate all prior state

Even after a stack, traceback, or backtrace is fully materialized, it normally describes the current call path and the operation at which execution is presently blocked or running. It does not necessarily enumerate resources, state transitions, or successful operations that occurred earlier in the same call path.

Therefore:

```text
not visible as a current frame != proven not previously acquired / performed
present somewhere in a call path != proven currently held / active
```

When a conclusion depends on previously acquired or retained state, establish that state from evidence that actually supports it: for example explicit runtime metadata, source-visible control flow, state fields, or another independently observed artifact. Do not fill the hidden state from assumption alone.

This is only an evidence-visibility boundary. TraceCite does not infer which prior state exists, which records should be combined, or what mechanism follows from them.

### Navigation-only information

Some TraceCite outputs are deliberately only navigation landmarks. Examples include:

- bounded source samples;
- `signal_hints`;
- projected `navigation_hint` rows;
- suggested bounded stack/context ranges.

These say where the Agent may want to look. They are not a substitute for materializing the referenced source text.

If a conclusion depends on a navigation-only range, materialize the range before citing or reasoning from its body.

# Adaptive retrieval and why outputs can look different

TraceCite uses deterministic adaptive transport routing to prevent small sources from being unnecessarily compressed while keeping large/deep evidence bounded.

The routing modes are transport choices, not semantic judgments:

```text
DIRECT  -> expose exact/raw evidence when it safely fits
BOUNDED -> return bounded search/source evidence and navigation landmarks
FOCUSED -> use tighter transport for deep/high-cardinality investigation
```

The returned `data.routing` information explains transport cost/risk decisions. It does not rank causal importance.

## DIRECT

For a sufficiently small unseen local source, DIRECT may expose the complete line-addressable source rather than forcing the Agent through samples.

For a safe DIRECT query, TraceCite may attach lossless line-addressable raw source text:

```text
data.direct_raw.fidelity = lossless_line_addressable
```

This is full-fidelity source output, not a semantic summary.

A source is not repeatedly dumped simply because it is small. Once it has already participated in the investigation, later retrievals may be bounded unless the Agent explicitly materializes a range.

## BOUNDED

For a larger source, TraceCite may return a deterministic bounded sample or a bounded number of search matches.

A bounded source sample is explicitly navigation-only. The Agent should use it to understand the shape of the source and choose ranges to materialize.

Current default routing budgets include bounded caps such as a limited number of evidence rows and bounded per-row text. These are context-control limits, not evidence-importance thresholds, and policy/Host configuration may change them.

## FOCUSED

When the source or investigation becomes deep/high-cardinality, TraceCite may use a tighter focused representation or a descriptive survey of source structure/templates.

Focused transport is intended to reduce repeated context growth. It does not mean the retained rows are the only relevant rows or that they are the most causally important rows.

# Search visibility boundary

## Returned search rows may be only a subset of all matches

A search can match far more records than can safely be placed in model context.

When fields such as:

```text
coverage.evidence_truncated = true
coverage.truncated = true
```

are present, the visible rows are a bounded subset of the complete match set.

Therefore:

```text
not visible in returned rows != not present in the source
```

Likewise, a small number of returned examples must not be interpreted as the total number of matching records unless the response explicitly establishes complete coverage.

## `no_match` is a retrieval fact, not a global absence proof

`status=no_match` means that particular retrieval request, with its exact query/filter/source semantics, produced no match.

It does not automatically prove:

- the event never happened;
- another spelling/representation is absent;
- another source contains no evidence;
- a broader/narrower time or scope would also miss;
- the current hypothesis is false.

The Agent decides whether a different retrieval strategy is justified.

# Signal hints and truncated-search navigation

When a search is truncated, TraceCite may inspect the already-produced full matched-record artifact and retain a very small set of additional line-addressable navigation candidates.

These are `signal_hints` / navigation hints. They remain outside formal `Evidence/new_evidence` until their source range is materialized.

## How signal-hint selection works

The current selector is deliberately diagnosis-free. It may use mechanical signals such as:

- generic severity vocabulary such as fatal/error/timeout-like terms;
- normalized structural signatures;
- repeated structural clusters;
- structural distinctiveness so rare shapes are not drowned by repeated common shapes;
- optional Drain-style generalized templates for repeated plain-text log patterns;
- strong stack syntax recognition;
- bounded local source structure around an already-selected candidate.

Volatile values such as IDs, addresses, counters, line numbers, UUIDs, or IP-like values may be normalized internally when building structural/template signatures.

These mechanisms exist to preserve diversity under a bounded output budget. They do not establish semantic relevance or root-cause importance.

Therefore:

```text
high severity hint      != root cause
rare structural hint    != anomaly proven important
large cluster_count     != causal importance
Drain/template group    != same causal event
selected hint           != TraceCite recommendation of a diagnosis
```

`cluster_count` is a mechanical frequency/grouping fact only.

## Internal neighborhoods are not automatically visible Evidence

TraceCite may temporarily inspect a bounded neighborhood around a candidate to compute a structural fingerprint. That internal neighborhood is not automatically returned to the Agent and must not be treated as observed Agent evidence.

Only returned/materialized text is available for Agent reasoning.

# Bounded segment navigation

For selected navigation hints, TraceCite may turn a single matching line into a bounded source range that is easier for the Agent to materialize coherently.

For strong stack-shaped text, the current implementation can detect a blank-delimited stack block around the match. The block is hard-bounded so it cannot become an unbounded context dump. If no strong stack block is recognized, TraceCite falls back to a small context neighborhood.

Important distinction:

```text
match line     = the line/range that matched the retrieval candidate
hint range     = the bounded source block suggested for materialization
```

The beginning of the hint range is not necessarily the matching line.

For example:

```text
actual match:       L23115
navigation range:   L23105-L23151
```

This means the match is inside a bounded context/stack segment. It does not mean L23105 itself matched or is more important.

The Agent should materialize the suggested range and reason from the returned frames/text, not from the range boundary itself.

# Source line ordering

Returned refs and ranges such as `L123-L140` describe positions in the captured source output.

Within the same source file:

```text
L123 < L456
```

means only that L123 appears earlier than L456 in that file's captured/output ordering.

Line order is not automatically:

- event-time order;
- execution order;
- happens-before;
- causal order;
- lock acquisition order;
- request order;
- proof that one action occurred before another.

Use line numbers to:

- cite exact output;
- navigate and revisit source ranges;
- inspect nearby output context;
- understand the source's captured ordering.

Do not infer a relationship merely because two ranges are close together or because one appears earlier in the file.

If the evidence itself contains explicit ordering/correlation fields such as timestamps, sequence numbers, trace/span IDs, request IDs, thread IDs, goroutine identities, or another source-defined ordering signal, the Agent may reason from those observed fields separately.

# Source identity, snapshots, and SHA-256

TraceCite distinguishes an evidence citation identity from the path used to make a later tool call.

## Snapshot refs are citations, not necessarily file paths

Search may snapshot source content to provide stable evidence provenance. A returned evidence URI/ref can therefore identify snapshot content rather than being a usable filesystem path.

When the Pi projection supplies fields such as:

```text
follow_up_file
source_path
sha256
```

use the explicit follow-up/source file argument for later TraceCite calls. Do not blindly pass a snapshot citation URI as a filesystem path.

## SHA-256 protects immutable source identity

When TraceCite returns a source SHA-256, reuse it for later materialization/replay when the tool surface supports it.

The SHA ties the range to exact source content. If the file has changed, TraceCite can reject or avoid treating the new bytes as the same immutable evidence.

This prevents an old `L123-L140` citation from silently being applied to different content at the same path.

## Mutable files and source generations

When an explicit immutable SHA is not supplied, RetrievalSession still performs mechanical source-lifecycle bookkeeping for range coverage.

For the same filesystem object, append-only growth can remain in the same source generation so already-covered earlier ranges remain meaningful.

Operations such as file replacement, truncation, or incompatible same-size modification create a new source generation instead of pretending the old coverage still applies.

This is source identity/version bookkeeping only. It has no semantic meaning about the log contents.

# `tracecite_retrieve`

`tracecite_retrieve` performs caller-selected evidence retrieval.

Typical target modes are:

- QueryTarget: search one source for caller-selected text/regex criteria;
- SourceTarget: inspect/probe/sample/survey a source depending on routing;
- ProviderTarget: retrieve from an evidence provider by caller-selected identities/entities.

Important semantics:

- literal matching is the normal query default unless regex is explicitly selected;
- a match is an observation, not proof of causality;
- search output may be bounded/truncated;
- routing and hint selection are transport mechanics;
- `new_evidence` refers to evidence identity novelty inside the current RetrievalSession;
- `matched_existing_evidence` identifies current matches whose evidence identity was already delivered earlier.

`matched_existing_evidence` does not mean the Agent understood or used that evidence previously. It only means the same evidence identity was already exposed in this session.

# `tracecite_materialize`

`tracecite_materialize` reads exact bounded context around an Agent-selected source line/range.

In the Pi surface, radius is intentionally bounded. Current compatibility tooling commonly limits radius to `0..30`.

Use materialize when:

- a search result needs more surrounding context;
- a navigation hint must become actual source Evidence;
- a stack/context range must be inspected;
- a particular line must be cited with surrounding evidence.

Materialized source text is evidence. TraceCite does not interpret it for the Agent.

## Coverage-aware materialization

RetrievalSession remembers immutable/source-generation line ranges already exposed.

If the requested materialization is already fully covered, TraceCite may return:

```text
status = no_new_evidence
new_text = ""
```

instead of duplicating the same body into model context.

For partially overlapping materialization, TraceCite can expose only the unseen numbered lines in `new_text` and report `unseen_ranges`.

This means:

```text
empty new_text != source range contains no text
```

It may simply mean that exact source-version range was already exposed earlier in the RetrievalSession.

Fields such as:

```text
repeated_text_suppressed
unseen_ranges
source_version
```

should be read as mechanical session/coverage facts.

# `tracecite_replay`

`tracecite_replay` intentionally re-reads previously covered immutable evidence.

Use replay when the Agent needs to reconsider exact old source text rather than pretending it is newly discovered evidence.

Replay semantics:

- immutable source identity/SHA is required where the interface specifies it;
- replay does not create new evidence novelty;
- replay does not expand the raw evidence frontier;
- replay is useful for comparing previously seen evidence with a newly formed hypothesis or newly discovered evidence.

# RetrievalSession semantics

RetrievalSession is mechanical evidence memory, not reasoning memory.

It can track facts such as:

- evidence URIs/identities already exposed;
- immutable/source-generation covered line ranges;
- observed relation identities;
- recent retrieval operations;
- request fingerprints;
- source observations/generations;
- new/repeated/replay/no-match outcomes;
- raw-line novelty/progress.

It does not store or infer:

- the Agent's hypothesis;
- root cause;
- causal relationships;
- whether an observation is important;
- evidence sufficiency;
- a stop recommendation.

## Evidence novelty and text novelty are different

A result can involve several kinds of novelty:

- new evidence identity;
- repeated evidence identity;
- newly exposed source lines;
- newly observed provider relations.

Do not collapse all of these into one semantic idea of "new information".

For example, a request can match an old Evidence identity while still exposing previously unseen source lines, or can return no new body because the requested range was already covered.

## `no_new_evidence`

`status=no_new_evidence` is a session-level mechanical result.

It means this operation did not expand the currently tracked evidence frontier under the relevant identity/range rules.

It does not mean:

- no evidence exists;
- the matched evidence is irrelevant;
- the current hypothesis is correct or incorrect;
- the Agent should necessarily stop.

# `tracecite_aggregate`

`tracecite_aggregate` performs bounded deterministic derived operations such as:

- `count`;
- `distinct`;
- `group`.

The Agent supplies the source/query/grouping rule.

Aggregate output is a mechanical derived fact over the requested scope. It does not itself expand raw source coverage and does not rank groups by causal importance.

Examples of safe interpretation:

```text
count=57              -> 57 records matched the specified aggregate scope
12 distinct values    -> 12 mechanically distinct values were observed in that scope
```

Unsafe interpretation:

```text
largest group -> root cause
most frequent -> most important
rare group    -> causal anomaly
```

Those require Agent reasoning and additional evidence.

# `tracecite_traverse`

`tracecite_traverse` performs bounded traversal over provider-supplied Evidence identities/entities/relations using caller-selected seeds and limits.

Traversal follows relationships that are present in the provider/evidence graph. It does not invent a causal relationship merely because two Evidence items are reachable.

Provider relation/traversal semantics are only as strong as the relation type and provenance actually supplied by the provider.

The Agent remains responsible for deciding whether a traversed relation matters to the task.

# Correlation and identity safety

TraceCite may mechanically detect that an identifier appears inside scoped entities and warn when identifier-only correlation would be unsafe.

Examples include fields such as:

```text
identifier_only_correlation_safe = false
minimum safe correlation key
scope_uniqueness_unverified
```

These are evidence-identity constraints, not causal claims.

Do not collapse records from different scopes merely because they share a short/common identifier when TraceCite reports that identifier-only correlation is unsafe.

TraceCite may expose an actionable `missing_evidence` item or suggested uniqueness-check query when scope uniqueness remains unverified. This means an identity/correlation fact is unresolved. It does not mean the overall diagnosis is insufficient or that the suggested query must be followed.

# `tracecite_verify`

`tracecite_verify` performs mechanical integrity/manifest verification for caller-selected Evidence.

Verification can establish things such as source/evidence manifest integrity. It does not verify the truth of the Agent's causal conclusion.

Therefore:

```text
Evidence integrity verified != diagnosis verified
```

Verify also does not expand source evidence coverage by itself.

# Evidence support boundary

When explaining findings, distinguish observed source facts from Agent inference.

A useful conceptual separation is:

```text
supported              -> directly established by observed evidence
inference_supported    -> reasoned from observed evidence, but not literally stated
unsupported_from_log   -> requires evidence not present in supplied sources
```

If a claim is an inference, qualify it.

If a deeper upstream cause or corrective fix would require source code, component-internal logs, telemetry, metrics, traces, or another artifact that is not supplied, state that evidence boundary rather than repeatedly searching the same source for proof that cannot exist there.

# Convergence and repeated investigation

TraceCite exposes mechanical novelty/progress so the Agent can notice when an investigation is looping. A Host may also expose a convergence checkpoint.

Low-novelty/non-frontier signals include:

- `status=no_match` after repeated equivalent retrieval directions;
- `status=no_new_evidence`;
- zero raw-line novelty;
- repeated materialization of already-covered context;
- repeated aggregate/replay/verify calls that do not expand raw evidence;
- repeated searches returning mostly previously exposed evidence;
- Host `agent_feedback.convergence_checkpoint.triggered=true`.

Before a follow-up evidence call, keep an explicit unresolved question in mind and know what materially different evidence the next call is expected to add.

When multiple fully materialized Evidence items already support a coherent candidate mechanism, synthesize and compare those established facts before retrieving more. The existence of additional searchable or materializable context is not, by itself, a reason to continue investigation.

Continue retrieval only when a concrete unresolved question remains and the next operation is expected to add materially different evidence that could distinguish, contradict, refine, or materially change the candidate mechanism. Newly exposed lines are not automatically a new kind of information; additional instances of an already-established structure may add no useful discriminating evidence unless multiplicity itself matters.

Do not turn an entity, actor, owner, event, or state that exists only because the current hypothesis expects it into a mandatory retrieval target. Before searching for a hypothesized missing piece, ask whether observing it would actually distinguish competing explanations or materially change the conclusion, and whether the already-observed Evidence supports a different mechanism without that assumed piece.

This is an Agent reasoning/stop discipline, not a TraceCite sufficiency judgment. TraceCite does not decide that the existing Evidence is enough; the Agent must explicitly compare what is already established against the unresolved question.

Efficiency is subordinate to correctness. Low novelty, repeated evidence, or token cost alone is not a reason to stop when a specific unresolved fact could materially change the conclusion. Conversely, the mere availability of more source text is not a correctness requirement when no such discriminating question remains.

If a Host convergence checkpoint requires `investigation_goal`, state both:

1. the exact unresolved question that still matters; and
2. the materially different evidence expected from the next operation.

Do not use generic goals such as "look for more evidence" or "confirm the hypothesis".

A checkpoint is a request for deliberate reassessment, not a TraceCite decision that the Agent must stop.

# Host tool activity and controlled evidence mode

The Pi extension can observe actual Host tool activity for trajectory/benchmark telemetry. Categories can include:

- canonical TraceCite tools -> `tracecite_evidence`;
- `grep` / `find` -> `native_search`;
- `read` -> `native_read`;
- `bash` -> `opaque_shell`;
- `ls` -> `native_other`.

Host activity telemetry is not source evidence and is not an evidence-sufficiency or root-cause signal.

In a controlled native-vs-TraceCite A/B mode, the Host may intentionally require all evidence-content operations to go through TraceCite while leaving file-location helpers available.

When that mode is active:

- use TraceCite for evidence search, materialization/replay, aggregation, traversal, and verification;
- do not bypass the controlled evidence channel with `grep`, `cat`, shell pipelines, or native `read` against the evidence files;
- after the Host reports such an access is blocked, do not retry equivalent native access to the protected evidence root;
- still use Agent reasoning normally;
- still choose hypotheses, queries, ranges, comparisons, conclusions, and stopping independently.

The controlled mode is a capability comparison, not an instruction to trust TraceCite's retrieval order as a diagnosis.

# What TraceCite mechanics do NOT imply

Keep these distinctions explicit:

```text
search match                  != causal proof
search rank                   != causal importance
signal hint                   != diagnosis recommendation
navigation range              != matched line
cluster_count                 != importance
structural similarity         != same root cause
Drain/template membership     != same event
same identifier               != safe correlation
same file / nearby lines      != related events
file line order               != event-time order
status=ok                     != hypothesis supported
status=no_match               != event globally absent
status=no_new_evidence        != no useful evidence exists
coverage suppression          != empty source text
verified evidence integrity   != verified diagnosis
routing mode                  != semantic importance
```

# Recommended Agent investigation loop

A good TraceCite investigation remains Agent-driven:

```text
1. State the unresolved question.
2. Retrieve evidence targeted at that question.
3. Check whether the result is complete, truncated, repeated, or navigation-only.
4. Materialize any hint/range whose actual body matters.
5. Record the local observed fact from the materialized evidence.
6. Compare that fact with previously established evidence when useful.
7. Distinguish observation from inference.
8. Choose the next retrieval only if it can add materially different evidence.
9. Stop or state the evidence boundary when the supplied artifacts cannot resolve the remaining question.
```

TraceCite's job is to make the evidence recoverable, bounded, line-addressable, and provenance-preserving.

The Agent's job is to understand what that evidence means.