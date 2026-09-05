# 0003: Evidence Compute Runtime vNext

- Status: proposed
- Date: 2026-09-05
- Owners: TraceCite maintainers
- Depends on: `0002-agent-evidence-shell-source-version.md`
- Must comply with: `docs/PROJECT_GUARDRAILS.md`, `docs/adr-agent-runtime-semantic-boundary.zh-CN.md`

## 1. Why this ADR exists

Recent Native-vs-TraceCite RCA runs show that TraceCite can already preserve SourceVersion stability, Evidence identity, provenance, bounded transport, materialization, replay, and session-scoped novelty while handling very large telemetry. The remaining product gap is no longer simply “can TraceCite find evidence?”

The largest current gap is that an Agent using Native shell/Python can compress a large amount of mechanical analysis into one execution, while an Agent using TraceCite still participates in too many mechanical orchestration steps. That creates four coupled costs:

1. more model/tool round trips;
2. repeated context replay and high cached-input usage;
3. more opportunities for confirmatory search loops and hypothesis lock-in;
4. more wall time, especially when provider rate limiting turns every extra model round into retries.

This ADR proposes evolving TraceCite from a primarily **Evidence Search Runtime** into an **Evidence Compute Runtime**.

The product boundary remains unchanged:

> **Agent owns reasoning and decisions. TraceCite owns deterministic computation over evidence, provenance, source/version truth, coverage, and transport control.**

TraceCite must not become a second diagnostic Agent.

---

## 2. First question: if TraceCite did not exist, would the model be better off?

This question is a mandatory design test, not a rhetorical one.

A strong Agent with native shell/Python has important advantages:

- it can invent an analysis program on the spot;
- it can scan/filter/group/join/bucket/compare in one process;
- intermediate data stays inside the script rather than crossing model boundaries;
- arbitrary local transformations do not require TraceCite to predefine an operator;
- one tool call can answer a fairly high-level mechanical question;
- no extra EvidencePointer/materialize protocol is needed when the Agent already has direct file access.

Therefore TraceCite is not automatically beneficial. If TraceCite only adds a constrained query DSL around files, the model may be better without it.

TraceCite earns its complexity only if it provides a combination Native does not provide automatically:

1. **bounded model-visible context independent of evidence size**;
2. **stable SourceVersion / SessionSourceView semantics**;
3. **exact Evidence identity, provenance, materialization, and replay**;
4. **Host-owned access and transport policy that the Agent cannot bypass**;
5. **large internal computation without sending intermediate rows to the model**;
6. **fewer model rounds than Native for equivalent analysis, or at minimum no more wall-time with materially lower context/token load**;
7. **answer quality no worse than Native**.

If those properties cannot be demonstrated in real paired runs, this vNext design should not be considered successful.

---

## 3. What is wrong with simply extending Evidence Shell?

Evidence Shell remains useful, but it must not remain the architectural capability boundary.

Continuing to add compatibility for `grep`, `rg`, `jq`, `sed`, `awk`, `sort`, `uniq`, and every new shell pattern has three problems:

- TraceCite gradually becomes a partial reimplementation of Unix rather than an evidence runtime;
- complex analysis such as before-vs-after, multi-source correlation, window joins, or custom scoring remains awkward;
- every unsupported expression can create another model/tool round.

Decision:

> Evidence Shell becomes a **compatibility frontend** that compiles into the same internal plan representation as other TraceCite APIs.

It is not removed. Existing shell behavior and current architecture invariants remain valid.

---

## 4. Target architecture

```text
                                  Agent
                                    |
                 +------------------+------------------+
                 |                  |                  |
            Analysis API       Program API       Shell Compat
                 |                  |                  |
                 +------------------+------------------+
                                    |
                                    v
                          Evidence Plan IR
                                    |
                                    v
                       Query / Compute Optimizer
                                    |
          +-------------------------+--------------------------+
          |                         |                          |
   Streaming Engine          Sandboxed Pure UDF       Correlation Engine
          |                         |                          |
          +-------------------------+--------------------------+
                                    |
                                    v
                         Typed Record / RecordSet
                                    |
                                    v
                                Segmenter
                                    |
                                    v
                     SessionSourceView / SourceVersion
                                    |
                                    v
                    logs / traces / metrics / code / ...

Cross-cutting:

InvestigationSession
  - SourceVersion bindings
  - Evidence ledger
  - Model-visible ledger
  - Materialization ledger
  - Computation cache
  - Coverage map
  - Result handles
  - Mechanical checkpoints

Transport Gate
  - bounded result types
  - Host-owned transport budget
  - no intermediate RecordSet crossing
  - explicit materialization only
```

---

## 5. What stays from current TraceCite

This proposal does **not** replace the existing evidence foundation.

The following remain core architecture:

### 5.1 Segmenter

Raw line hits are not necessarily complete Evidence. Segmenter remains the boundary that restores a complete logical Record before record-level computation is treated as authoritative.

```text
raw bytes / lines
    -> candidate location
    -> Segmenter
    -> complete logical Record
```

Multiline stack traces, format-dependent records, structured JSONL, traces, and future domain segmenters continue to use this layer.

### 5.2 Record

Record becomes more important. Compute operators act on Records/RecordSets rather than arbitrary physical lines whenever record semantics are required.

Common mechanical fields may include:

- stable record identity;
- source version;
- source/range provenance;
- timestamp where available;
- entity/service where mechanically extracted;
- structured fields;
- raw text or a recoverable raw handle.

Typed forms such as `LogRecord`, `TraceSpanRecord`, `MetricRecord`, and `CodeRecord` may exist above the common Record contract.

### 5.3 Evidence / EvidencePointer

Evidence remains the provenance root. It is no longer required to be the main thing returned after every computation.

Derived results must have lineage to the underlying Records/Evidence and SourceVersion. The Agent should usually see compact derived facts plus a few representative Evidence handles; it can explicitly materialize exact evidence when needed for reasoning/citation.

### 5.4 SourceVersion / SessionSourceView

Unchanged and non-negotiable. Every dependent computation in one InvestigationSession must observe the same bound evidence world unless the Host explicitly starts a new session/refresh semantic.

### 5.5 Materialize / Replay

Retained as exact evidence primitives. Their frequency should decrease because broad mechanical work should happen in Compute Runtime, but exact recovery/citation remains mandatory.

### 5.6 Host/User Evidence policy

Retained and extended. The Agent must not control the budgets that determine how much evidence or result payload may cross into model context.

---

## 6. Evidence Plan IR

The central architectural addition is a common **Evidence Plan IR** (Intermediate Representation).

Different Agent-facing syntaxes compile to this IR:

```text
Shell-like syntax  ---+
Analysis API       ----+--> Evidence Plan IR --> optimizer --> executor
Program API        ---+
```

Example logical IR:

```text
Scan(traces)
  -> Filter(serviceName == "route")
  -> Filter(statusCode >= 500)
  -> GroupBy(operationName)
  -> Count()
  -> TopK(10, count desc)
```

The IR separates two concerns that are currently coupled:

- how the Agent expresses a request;
- how the Runtime executes it efficiently.

The optimizer may safely use predicate pushdown, streaming aggregation, top-K heaps, time-window pruning, shared scans, cached field extraction, and backend-specific indexes without changing Agent syntax.

### IR restrictions

IR operators must be deterministic/mechanical. They may calculate facts but may not encode epistemic conclusions such as:

- likely root cause;
- hypothesis confidence;
- recommended next hypothesis;
- evidence sufficient;
- stop recommended.

---

## 7. Three Agent-facing surfaces

### 7.1 Analysis API — preferred high-level surface

An Agent should be able to request a bounded mechanical analysis rather than micromanage each search step.

Examples of generic mechanical requests:

- compare field/group distributions across caller-defined windows;
- compute deltas between caller-defined cohorts;
- correlate records from caller-selected sources by mechanical keys/time windows;
- return top-K changes and bounded representative evidence;
- execute several caller-selected aggregates in one shared scan.

The Agent still chooses what comparison is relevant. TraceCite does not decide which hypothesis should be tested.

### 7.2 Program API — flexibility escape hatch

To approach native programming flexibility, the Agent needs more than a fixed operator catalog.

The Program API should support a pure, capability-sandboxed evidence language with at least:

- variables;
- expressions and arithmetic;
- strings and regex;
- conditionals;
- bounded loops/reduce;
- pure functions/lambdas;
- list/dict/tuple-like local values;
- timestamp/duration arithmetic;
- RecordSet operations;
- pure user-defined functions (UDFs).

It must not expose:

- arbitrary filesystem access;
- network;
- process/subprocess execution;
- OS shell;
- environment variables/secrets;
- arbitrary side effects.

The execution environment may eventually use a custom VM or WASM-style capability boundary, but implementation technology is secondary to the capability contract.

### 7.3 Shell Compatibility

Existing Evidence Shell remains supported and compiles into IR when possible. Unsupported shell syntax should not define the compute engine's long-term capability ceiling.

---

## 8. Why generic programming flexibility does not require unrestricted Python

The goal is not “Python can do anything, therefore embed Python with host access.”

The goal is:

> provide near-general computation **over authorized evidence objects** while keeping external capabilities closed.

The design uses two levels:

1. declarative/recognizable dataflow for common operations, so the optimizer can execute them efficiently;
2. a pure UDF escape hatch for custom transformations/scoring/classification when the Runtime does not know the domain-specific function in advance.

For example, the Agent may define a pure function that computes a custom score from fields. TraceCite need not contain a product-specific `detect_some_fault()` operator.

This is a primary anti-overfitting property: generic primitives compose into case-specific analysis without case-specific product logic.

---

## 9. Runtime-side computation versus model-visible information

A hard architectural boundary is required:

```text
                         Runtime World
----------------------------------------------------------------
Raw Source
Segmented Records
RecordSets
Intermediate tables
Full match sets
Join results
Indexes
Computation cache
Execution plan
Full lineage

======================= TRANSPORT GATE =========================

                          Model World
ScalarResult
Small AggregateResult
Small ContrastResult
TopKResult
Representative Evidence handles
Explicit bounded MaterializedEvidence
Mechanical checkpoint
```

### Rule

> Large data may enter Runtime. Large intermediate data must not enter the model by default.

This is enforced by architecture, not by prompting the Agent to “be careful.”

### Bounded result types

Public Agent responses should use bounded result families rather than arbitrary `list[Record]` / unbounded nested dictionaries.

Candidate result families:

- `ScalarResult`;
- `AggregateResult`;
- `ContrastResult`;
- `TopKResult`;
- `EvidenceSample`;
- `MaterializedEvidence`;
- `MechanicalCheckpoint`.

Each result type has Host-defined row/byte/token ceilings and explicit truncation/coverage semantics.

---

## 10. Evidence count is not Evidence transport

If 12,431 records match a predicate, the model does not need 12,431 locators.

The Runtime may return:

```text
match_count = 12431
coverage = complete
representatives = [E1, E2, E3]
result_handle = result://...
```

The full set remains Runtime-side and recoverable by handle/lineage.

This preserves a key current invariant: no high-cardinality locator dump enters context.

---

## 11. ResultHandle / RecordSetHandle

vNext should introduce handles only where they reduce model transport and repeated scanning.

Example:

```text
failed = result://A   # 18,742 records, Runtime-side
route  = result://B   # 5,103 records, Runtime-side
```

The Agent can ask the next computation to consume `result://B` without receiving or resending those rows.

A handle must be bound to:

- InvestigationSession;
- SourceVersion(s);
- exact normalized Plan identity;
- schema/type;
- coverage/completeness facts.

Handles are not Evidence bodies and must not weaken provenance/replay semantics.

---

## 12. `emit` / Transport Gate as the only model crossing

Program execution may create arbitrarily many Runtime-internal variables/RecordSets within Compute Budget. Only explicit bounded outputs cross the transport boundary.

If an Agent attempts to emit an unbounded RecordSet, Runtime returns a mechanical error such as:

```text
transport_too_broad
```

with generic alternatives such as aggregate/top-K/sample/bounded projection. It must not silently first-N the result and claim completeness.

---

## 13. Three separate budgets

vNext should distinguish:

### Compute Budget

Limits Runtime work:

- bytes scanned;
- CPU/instruction budget;
- memory;
- wall time;
- join complexity;
- UDF instruction count.

### Transport Budget

Limits Runtime -> model output:

- encoded bytes;
- estimated tokens;
- rows/groups;
- representative handles.

### Materialization Budget

Limits explicit raw Evidence body delivery.

These budgets are Host/User policy and are not Agent-upgradable.

This lets Runtime process 100 MB internally while returning 1–8 KB to the model.

---

## 14. Shared scan and compute fusion

A major performance objective is to eliminate repeated scans that Native would naturally combine in one script.

If a caller requests several compatible mechanical aggregates over one source/scope, Runtime should plan one scan with multiple accumulators where possible:

```text
scan traces once
  -> accumulator: error count
  -> accumulator: group by service
  -> accumulator: latency top-K
  -> accumulator: status distribution
```

This is more important than micro-optimizing individual response JSON.

---

## 15. Contrast/window/join are generic compute primitives, not RCA rules

Before/after, cohort comparison, time windows, joins, and deltas are useful in debugging, observability, data analysis, code archaeology, CI failures, security logs, and many other domains.

They belong in the generic compute engine only as caller-selected mechanical operations.

TraceCite must not encode rules such as:

- always compare a specific error before/after an incident;
- healthy-period occurrence means “not root cause”;
- inspect memory when a process restarts;
- choose a specific service or metric family.

The Runtime may calculate a requested contrast. The Agent interprets it.

This distinction is essential to prevent benchmark-specific reasoning from leaking into product code.

---

## 16. InvestigationSession becomes a mechanical workspace

RetrievalSession semantics expand into an InvestigationSession workspace while preserving the old mechanical ownership boundary.

It may own:

- bound SourceVersions;
- seen Evidence identities;
- materialized-body ledger;
- result handles;
- computation cache;
- plan fingerprints;
- coverage facts;
- model-visible-result ledger;
- mechanical checkpoints.

It must not own:

- Agent hypotheses;
- root-cause ranking;
- causal confidence;
- sufficiency;
- stopping decisions.

---

## 17. Model-visible ledger

A specific new concern is preventing already-delivered content from repeatedly re-entering the model.

The Runtime/Host should mechanically remember:

- Evidence bodies already delivered;
- derived results already delivered;
- result identities/hashes already delivered;
- stable handles already exposed.

When the same exact content is used again, the transport can reference the prior identity instead of resending the body, while preserving explicit recall/materialize behavior.

This is mechanical content identity, not semantic “information gain” reasoning.

---

## 18. Checkpointing and model context

Even a 2 KB tool response repeated 100 times creates large context. Therefore reducing per-call payload alone is insufficient.

The Host integration should support bounded investigation checkpoints so old tool history need not stay fully model-visible forever.

A mechanical checkpoint may contain:

- bound source/version identities;
- executed computation handles;
- exact coverage facts;
- materialized evidence handles;
- delivered result identities.

Any semantic reasoning checkpoint such as “candidate X is unlikely” must be produced by the Agent/Host reasoning layer, not inferred by Runtime.

Target model working set:

```text
problem
+ current Agent reasoning summary
+ mechanical checkpoint
+ recent analysis result(s)
+ selected exact Evidence
```

not the entire history of every intermediate tool result.

---

## 19. Main disadvantages introduced by TraceCite vNext

The design must explicitly acknowledge its costs.

### 19.1 Extra system complexity

IR, optimizer, session cache, lineage, sandboxing, and transport rules are a substantial implementation surface.

### 19.2 Risk of becoming a second data platform

If every possible operator/backend/domain abstraction is added, TraceCite can become over-engineered. The design must prefer a small composable core plus pure UDF escape hatch.

### 19.3 Optimizer semantic bugs

Any optimized execution path can diverge from canonical semantics. Fast paths must be equivalence-tested against canonical behavior, as recent Unix compatibility regressions demonstrated.

### 19.4 Restricted program environment

Some native scripts will remain easier to express than a capability-sandboxed environment. Native remains the flexibility ceiling for unrestricted local computation.

### 19.5 Lineage cost

Exact provenance for derived results adds bookkeeping. It must remain bounded and stored Runtime-side rather than becoming another large model-visible index.

### 19.6 Cache/session complexity

Stale or incorrectly keyed cached results would be severe correctness bugs. Cache keys must include SourceVersion and normalized Plan identity.

### 19.7 Tool/API learning overhead

If Agent-facing APIs are more complex than writing one native script, TraceCite loses. Public tool count and conceptual burden must stay small.

### 19.8 Provider interaction remains external

TraceCite cannot eliminate provider 429/overload. Its responsibility is to reduce unnecessary model calls/context pressure; infrastructure failures must be separately classified in benchmarks.

---

## 20. Self-review round 1: is this genuinely general?

Question: does the proposal contain mechanisms that only make sense because of the current RCAEval case?

Review:

- Segmenter, SourceVersion, Evidence, IR, filter/group/top-K/window/join/contrast, handles, budgets, and pure UDF are general data/evidence mechanisms.
- No product rule references the current benchmark's service name, fault type, OTel, JVM, memory, or incident answer.
- `contrast` is acceptable only as a caller-selected operation. Runtime must not autonomously choose “healthy vs incident” because that would become investigation strategy.
- checkpointing and model-visible ledgers are general context-management mechanisms.

Result: **passes generality condition**, provided implementations keep analysis selection caller-owned.

---

## 21. Self-review round 2: are we rebuilding Spark/Pandas unnecessarily?

Question: if generic compute becomes large, are we creating an entire data platform just to save model calls?

Risk: yes.

Correction:

- phase 1 must not implement a broad programming language, WASM VM, graph engine, SQL parser, or every join type;
- start with a minimal typed IR that subsumes capabilities already proven necessary in real Agent traces;
- prioritize shared scan, multi-aggregate, bounded result handles, and transport control before adding a general UDF VM;
- only add a Program/UDF escape hatch after measurements show fixed IR operators are the remaining flexibility bottleneck.

Result: **architecture remains the target, implementation must be incremental and evidence-driven.**

---

## 22. Self-review round 3: would Native still be simpler and faster?

Question: after adding IR and transport, could Native still win because it executes one arbitrary script locally?

Yes. That is the strongest competing design.

Therefore vNext must not be accepted because the architecture “looks cleaner.” It needs paired evidence showing:

- fewer or equal meaningful Agent rounds;
- lower fresh+cached context pressure;
- wall time no worse;
- answer quality no worse;
- provenance/SourceVersion guarantees preserved.

If Native consistently remains faster while TraceCite only saves a modest amount of tokens, the additional architecture may not justify itself.

Result: **benchmark outcome is a design gate, not a marketing metric.**

---

## 23. Self-review round 4: can fewer model-visible bytes hurt reasoning?

Yes. Over-compression can hide the qualitative detail needed for diagnosis.

Rules:

- compact derived results never replace recoverable canonical Evidence;
- representative evidence selection must be mechanically defined/caller-controlled, not “most causally relevant” inferred by Runtime;
- coverage/truncation must remain explicit;
- Agent must be able to materialize selected exact records;
- if a derived result does not preserve enough lineage to recover support, it is invalid.

Result: **Transport Gate must reduce transport, not evidence truth.**

---

## 24. Self-review round 5: can the Runtime accidentally take over reasoning?

High-level `analyze` is dangerous if it accepts vague requests such as “find the root cause” and internally chooses what matters.

Decision:

- the first implementation of Analysis API must be a structured mechanical plan, not a natural-language diagnostic planner;
- natural-language planning, if ever added, belongs to Agent/Host, which compiles its chosen plan into TraceCite IR;
- Runtime executes the plan but does not generate investigation strategy.

Result: **passes semantic-boundary condition only with structured caller-owned analysis.**

---

## 25. Self-review round 6: how do we actually reduce model-call count?

Reducing output bytes is insufficient. The architecture must remove entire model boundaries.

Priority mechanisms:

1. one call can request multiple mechanical aggregates;
2. one call can perform a caller-defined comparison across windows/cohorts;
3. one call can perform bounded representative selection plus optional exact materialization;
4. shared scans fuse compatible operations;
5. Runtime handles let subsequent operations consume large internal result sets without round-tripping them through the model;
6. exact repeated results/bodies are referenced rather than resent;
7. Host checkpointing prevents old tool outputs from accumulating indefinitely.

Target behavior is to move from dozens of `query -> model -> query -> model` loops toward a small number of `mechanical analysis -> model reasoning` loops.

---

## 26. What should actually be sent to the model?

Default model-visible content should be limited to what the Agent needs to reason or cite:

### Send

- compact scalar/aggregate/contrast values;
- explicit coverage/completeness/truncation facts;
- source/version identity when relevant to trust/replay;
- stable result/evidence handles;
- a small caller/request-bounded set of representative evidence previews;
- exact materialized evidence only when explicitly requested or included under a bounded caller-selected materialization stage;
- small mechanical checkpoint/delta.

### Do not send by default

- full intermediate RecordSets;
- complete high-cardinality locator arrays;
- repeated Source/SHA/URI metadata on every row when it can be shared at the envelope;
- complete lineage graphs;
- full prior session history;
- raw scan diagnostics unless requested for debugging;
- large schema descriptions repeatedly;
- exact previously delivered bodies.

---

## 27. Public tool surface target

Do not expose every IR operator as an MCP tool.

Long-term target is approximately:

```text
tracecite_analyze      # structured mechanical plan / common case
tracecite_program      # pure evidence program escape hatch
tracecite_materialize  # exact evidence body
tracecite_replay       # explicit exact reread
tracecite_session      # bounded mechanical state/handles
```

Existing `tracecite_run` remains as compatibility while migration is validated.

The exact names are not yet accepted API; the design principle is a small tool surface with richer Runtime-side work per call.

---

## 28. Implementation plan

Implementation must proceed in measured phases. Do not start with a full rewrite.

### Phase 0 — documentation and baseline freeze

- keep this ADR `proposed`;
- record current Native/TraceCite RCA baseline artifacts and current architecture invariants;
- change RCA experimental Agent timeout to 7 minutes per arm;
- preserve blind/manual-no-gold evaluation;
- require same model/provider for architectural value tests when possible; when intentionally using different GMI endpoints, label the provider variable explicitly.

Exit: architecture review accepts the minimal first coding slice.

### Phase 1 — minimal IR over existing Evidence Shell semantics

Introduce internal typed plan nodes for the already-supported deterministic pipeline, without changing public semantics:

- Scan/Source;
- literal/regex predicate;
- structured filter;
- project;
- group/count/distinct;
- sort/top-K;
- explicit selection;
- bounded emit/result.

Evidence Shell compiles to IR; canonical execution remains the correctness oracle while equivalence tests are built.

Do not add natural-language planning or RCA-specific operators.

### Phase 2 — multi-aggregate shared scan

Add one-call plans that calculate multiple caller-selected aggregates over the same scope in one scan.

This phase directly targets Native's “one script, many counters” advantage.

Acceptance:

- result equivalent to independent canonical operations;
- lower/equal source scans;
- bounded output;
- no extra model-visible intermediate state.

### Phase 3 — bounded result handles and compute reuse

Introduce session-bound ResultHandles for large intermediate sets/results where repeated computations currently cause rescans or round trips.

Requirements:

- handle includes Session/SourceVersion/Plan identity;
- no raw large set crosses model boundary;
- invalid after incompatible session/source world;
- lineage recoverable Runtime-side.

### Phase 4 — caller-defined window/contrast/join primitives

Add only mechanical operations:

- caller-defined temporal windows;
- cohort comparison/delta;
- mechanically keyed/time-window joins;
- bounded top changes.

No automatic incident strategy.

### Phase 5 — Host/model-visible ledger and checkpoint delta

Prevent exact result/evidence bodies from repeatedly entering context and provide bounded mechanical checkpoints.

Measure cached-input reduction separately from Runtime execution cost.

### Phase 6 — pure Program/UDF escape hatch, only if needed

Do not implement unless benchmarks show that fixed IR expressiveness is still forcing extra Agent rounds compared with Native.

Start with a tiny pure expression/UDF environment and strict compute/instruction budgets. WASM/custom VM is a possible implementation, not a requirement.

---

## 29. Coding Go/No-Go decision before implementation

Coding may begin only if all are true:

1. the change can be expressed as a generic evidence-compute mechanism;
2. no current-case names/fault semantics/hidden answer enter Runtime, MCP projection, Skill, or tests;
3. current SourceVersion/Segmenter/Evidence/provenance/budget invariants remain intact;
4. the first slice targets a measured inefficiency seen across more than one operation pattern, not merely a speculative feature;
5. it can be regression-tested mechanically against canonical behavior;
6. it has a plausible path to reducing full model boundaries, not only shaving JSON bytes.

Current decision after the review above:

> **GO for a narrow Phase 1 + Phase 2 implementation. NO-GO for a full rewrite, general UDF VM, autonomous analysis planner, or large public API redesign at this stage.**

The first implementation should therefore focus on a minimal IR/shared-scan compute layer that reuses the current canonical Evidence/Segmenter/SourceVersion foundations.

---

## 30. RCA benchmark loop after coding

The previously used RCAEval blind case may be reused as a regression/performance probe, but must never influence product semantics.

### Case handling

- use the same anonymous telemetry bytes for Native and TraceCite;
- hide case/fault annotation from both Agents until both final answers are complete;
- no gold/scorer input to the Agent;
- final correctness is manually reviewed against the source annotation/actual failure definition only after both answers finish.

### Timeout

Set the Agent investigation timeout to **420 seconds (7 minutes) per arm**.

Timeout is a product failure only when attributable to the product path. Provider/infrastructure failures require classification and rerun.

### 429 / overload handling

For any run with material provider 429/overload:

1. count and classify provider incidents;
2. measure whether TraceCite generated materially more model attempts/context pressure that could reasonably trigger rate limits;
3. distinguish `rate limit exceeded`, provider overload, quota, and context-size errors;
4. rerun the affected comparison when provider instability could dominate the 7-minute result;
5. do not “fix” TraceCite Runtime for a pure provider outage;
6. if TraceCite's unnecessary rounds drive sustained token/request throughput and Native does not, treat the extra rounds as a TraceCite efficiency defect even though the HTTP error is external.

### Acceptance gates

A TraceCite run is not a win unless all correctness/infrastructure gates pass.

Required target on the current paired probe:

1. **Answer quality:** manual review not worse than Native. Root component, concrete mechanism precision, causal chain, caveats, and unsupported inference are reviewed separately.
2. **Time:** valid TraceCite wall time must not exceed valid Native wall time. Both must fit 420 seconds.
3. **Token/context:** TraceCite must use less model context/token load than Native on the paired valid run. Track fresh input, cached input, output separately; do not invent a universal combined metric when provider accounting is ambiguous.
4. **Model rounds:** should be materially reduced; a token win obtained via much more orchestration is not the intended architecture result.
5. **Evidence guarantees:** provenance, replay, SourceVersion stability, and Host budget still pass regression suites.

If any of the first three fail, re-enter diagnosis rather than declaring success.

---

## 31. Iterative benchmark-driven repair rules

After each failed pair:

1. manually review Native and TraceCite answers before reading hidden annotation;
2. then inspect actual case truth and classify answer gaps;
3. inspect Agent trajectory and Runtime timing;
4. classify the failure into one of:
   - Runtime semantic/correctness bug;
   - transport/context defect;
   - unnecessary model-boundary/orchestration defect;
   - performance implementation defect;
   - Agent reasoning error with adequate evidence available;
   - capability gap generic enough to justify product work;
   - provider/infrastructure invalid run;
5. modify product code only for concrete generic defects;
6. add a generic regression test before rerunning;
7. rerun with the same blind protocol;
8. repeat until acceptance gates pass or the architecture itself is judged not worthwhile.

A model reasoning error alone is not permission to insert a reasoning rule into TraceCite.

---

## 32. Anti-overfitting / benchmark firewall

Forbidden product changes include:

- current RCAEval case ID;
- service names from the case;
- fault ID/type from hidden annotation;
- OTel/JVM/memory-specific rules added because of this case;
- prompt text that teaches the preferred diagnosis path;
- root-cause-specific stop rules;
- gold/regex/scorer hacks;
- special-case source/file names except generic schema adapters already justified independently;
- “if this exact error exists, compare X” logic.

Allowed changes must remain useful if the benchmark is replaced by an unrelated large-log/code/trace investigation.

Every benchmark-motivated code change should answer:

> Would I still want this behavior if I had never seen the hidden case answer?

If no, reject the change.

---

## 33. What success would look like

A successful TraceCite vNext should change the Agent interaction pattern from:

```text
query -> model
query -> model
materialize -> model
aggregate -> model
query -> model
...
```

toward:

```text
mechanical analysis plan -> Runtime performs large computation -> compact result
                                             |
                                             v
                                       model reasons
                                             |
                            next caller-selected analysis plan
```

Typical complex investigations should aim for a small number of meaningful reasoning rounds rather than dozens of mechanical orchestration rounds.

The architectural promise is:

> **Computation scale may grow with evidence size; model-visible working-set size should remain bounded.**

and:

> **Native-like mechanical flexibility/efficiency where possible, plus TraceCite's provenance, SourceVersion, Evidence identity, replay, and Host-policy guarantees.**

---

## 34. Final design judgment at proposal time

After adversarial review, the proposal is considered reasonable only in incremental form.

The strongest reason to proceed is not that IR or a compute engine is aesthetically better. It is that current real runs show a specific architectural cost: too many mechanical steps cross the model boundary, while Native can keep those steps inside one script.

The strongest reason to stop is equally clear: if a minimal shared-scan/IR implementation cannot beat or at least match Native wall time and answer quality while reducing context/token use, then expanding TraceCite into a larger programming runtime would be unjustified complexity.

Therefore the next action is deliberately narrow:

1. implement Phase 1 minimal IR behind current semantics;
2. implement Phase 2 shared multi-aggregate execution;
3. preserve existing public behavior and all Evidence invariants;
4. run regression suites;
5. run the 7-minute blind paired benchmark;
6. judge with correctness-first manual review;
7. continue only when measured results justify the next layer.
