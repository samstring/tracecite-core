# 0003 Review: Evidence Compute Runtime vNext

- Status: design-review companion to ADR 0003
- Date: 2026-09-05
- Reviewed proposal: `docs/adr/0003-evidence-compute-runtime-vnext.md`
- Purpose: adversarially challenge the design before any vNext execution code is accepted

## 1. Review rule

The review asks repeatedly:

1. Is the mechanism generic, or is it useful only because we know the current benchmark?
2. Would a strong Agent with native shell/Python simply do better without TraceCite?
3. Does TraceCite add enough value to justify the extra abstraction?
4. What new failure modes does TraceCite introduce?
5. What exactly needs to cross into the model, and what must stay Runtime-side?
6. Does the proposal remove full model boundaries, or merely shrink individual JSON responses?
7. Can correctness/provenance still be verified without recreating a giant hidden index?
8. Can the first implementation be measured without committing to a full rewrite?

The design is allowed to proceed only after these questions have concrete answers.

---

## 2. Finding: existing Skill currently contains investigation strategy and must not be used as the vNext benchmark contract

Current `tracecite-mcp/skills/tracecite/SKILL.md` contains rules that go beyond API semantics, including guidance to:

- stop when a particular level of causal chain is considered sufficient;
- perform temporal contrast before promoting an error/config/resource signal to root cause;
- interpret a signal unchanged across healthy/faulty periods as background unless another observation changes that interpretation.

Those ideas may be reasonable Agent reasoning heuristics, but they are **investigation strategy**, not TraceCite Runtime semantics. They conflict with the existing project boundary that Agent owns hypotheses, causal reasoning, sufficiency, and stopping.

They are especially inappropriate for the current benchmark loop because temporal contrast was added after observing a concrete RCA misattribution.

### Required correction before vNext benchmark

The TraceCite Skill must be reduced back to tool/API semantics:

- session reuse;
- `too_broad` meaning;
- Evidence budget ownership;
- bounded outputs;
- materialize/replay semantics;
- how to use a caller-selected compute/analyze plan;
- exact meanings of coverage/novelty/result handles.

It must **not** tell the Agent what causal test to perform or when to stop.

This correction is generic architecture cleanup, not a benchmark-specific optimization.

---

## 3. Finding: an internal IR alone does not reduce model calls

If Phase 1 only rewrites `tracecite_run` internally as:

```text
Shell -> IR -> same result
```

then the Agent still makes the same number of calls. The architecture becomes more complex without delivering the main claimed benefit.

### Correction

The first measurable coding slice must include both:

1. a minimal internal IR / canonical compute representation; and
2. a structured **batch mechanical analysis** entry point capable of requesting multiple named outputs in one call.

Conceptual example:

```json
{
  "source": "traces.jsonl",
  "analyses": [
    {"name": "status", "program": "group statusCode"},
    {"name": "services", "program": "where statusCode >= 500 | group serviceName"},
    {"name": "slow", "program": "sort duration desc numeric | head 5"}
  ]
}
```

The concrete public schema may evolve, but the product property is mandatory:

> several already-known mechanical computations over one source/scope can be submitted through one model/tool boundary and fused Runtime-side where safe.

This remains generic. The Agent chooses the analyses; TraceCite does not choose hypotheses.

---

## 4. Finding: the first API should be structured, but it should reuse existing program semantics initially

A brand-new large declarative language would delay validation and create semantic risk.

The first `analyze/compute` surface may therefore accept multiple bounded normalized Evidence programs as named outputs, compile each into minimal IR, and share scan/parse work where compatible.

This is intentionally transitional:

```text
Agent batch request
   -> normalized existing Evidence programs
   -> minimal IR
   -> shared executor
```

Later Analysis/Program frontends may compile directly to the same IR.

This avoids making Shell the long-term architecture while reusing already-tested semantics during migration.

---

## 5. Finding: model context replacement cannot be guaranteed by TraceCite Core

TraceCite can bound every new response and avoid resending exact bodies, but it cannot universally delete tool output that a Host has already placed into model conversation history.

Therefore ADR 0003 checkpointing must be scoped correctly:

- **Core guarantee:** bounded new transport, mechanical identity/delta, no repeated exact body by default;
- **Host-dependent optimization:** replacing/compacting old conversation history with a checkpoint;
- **portable primary strategy:** reduce the number of full model boundaries in the first place.

The benchmark must not claim context-history savings that depend on a Host feature not actually used by Pi.

---

## 6. Finding: lineage must not recreate EvidenceIndex under another name

A derived aggregate over 100,000 records cannot store or transmit 100,000 Evidence IDs merely to claim provenance.

### Lineage rule

For deterministic derived results, lineage should normally be represented by a compact computation recipe:

```text
SourceVersion identity
+ normalized plan identity
+ execution/runtime semantic version
+ complete/incomplete coverage facts
+ bounded result identity/hash
```

Because the SourceVersion is immutable, TraceCite can deterministically recompute/verify the derived result when needed.

Only explicitly surfaced representative/materialized Evidence requires individual pointers in model-visible output.

This keeps provenance strong without a high-cardinality member list.

---

## 7. Finding: ResultHandle lifecycle must be bounded

Runtime-side handles can themselves create unbounded memory/disk state if every intermediate set is retained forever.

### Handle contract

A ResultHandle should be:

- session-scoped;
- immutable;
- keyed by SourceVersion + normalized Plan identity;
- typed;
- coverage-aware;
- subject to Host-owned cache/storage budget;
- evictable.

If evicted, a deterministic handle may be recomputed from immutable SourceVersion when policy allows, rather than requiring permanent storage of a large membership set.

A handle is an optimization, not a new canonical evidence store.

---

## 8. Finding: representative Evidence can create hidden bias

Automatically returning “representative” records can influence Agent reasoning even when selection is mechanical.

### Rule

Representative selection must have explicit semantics and never imply causal relevance.

Allowed examples:

- first/last by explicit ordering;
- evenly spaced sample;
- deterministic sample by stable hash;
- first N per caller-selected group;
- top-K by a caller-selected numeric field.

The response should label the selection strategy and completeness.

TraceCite must not invent “most relevant evidence” ranking using hidden diagnostic heuristics.

For some aggregate responses, returning zero raw representatives by default may be better than automatically choosing examples.

---

## 9. Finding: tool-schema/context overhead matters

A highly expressive `tracecite_analyze` schema can itself become a large prompt/tool-description cost.

### Rule

The first public tool must remain compact:

- one session/source scope;
- a bounded list of named mechanical programs/outputs;
- a small number of generic transport options owned/limited by Host;
- no enormous nested per-operator JSON schema.

Agent-facing examples belong in a concise Skill, but the Skill must teach syntax/semantics rather than investigation strategy.

Measure schema/skill context cost in the benchmark; do not assume it is free.

---

## 10. Finding: shared scan must preserve Segmenter correctness

Shared scan cannot optimize by parsing raw lines independently when the canonical semantics require complete logical Records.

Execution planner requirements:

1. bind one SessionSourceView;
2. choose a scan/recovery mode that is safe for all requested analyses;
3. restore complete Records through Segmenter where required;
4. parse reusable structured fields once per Record when possible;
5. update multiple analysis accumulators;
6. finalize bounded outputs;
7. apply Transport Gate.

If two requested analyses require incompatible safe execution modes, Runtime may split them into more than one internal pass while still keeping the work inside one Agent tool call.

Correctness has priority over scan fusion.

---

## 11. Finding: Native remains the unrestricted flexibility ceiling

No capability-sandboxed environment will be as unconstrained as local Python with filesystem/process/network access.

The product should not claim otherwise.

The intended advantage is narrower:

> for deterministic computation over authorized evidence, approach Native's composability while adding SourceVersion, provenance, Host policy, bounded transport, and reproducibility.

If a task fundamentally requires arbitrary external actions, TraceCite is not the replacement for Native tools.

---

## 12. Finding: a generic Program/UDF VM is not justified yet

The target architecture may eventually need pure UDFs, but current benchmark evidence does not yet justify implementing a custom VM/WASM layer.

Implementing it now would add security, language, optimizer, and debugging complexity before proving the simpler compute layer is worthwhile.

### Decision

- keep Program/UDF in target architecture;
- do not implement it in the first coding cycle;
- revisit only if paired trajectories show the remaining gap is genuinely “cannot express custom pure computation in one call.”

---

## 13. Finding: transport budget and compute budget must fail differently

Two distinct failures must remain observable:

- computation cannot finish inside Host compute policy;
- computation succeeds but the requested model-visible result is too large.

These must not collapse into one generic `too_broad` state.

Conceptually:

```text
compute_budget_exceeded
transport_too_broad
```

The Agent may alter its requested computation/selection, but cannot enlarge Host budgets.

---

## 14. Finding: batch execution needs per-output coverage

One batch may contain outputs with different completeness states.

The response must not expose only a single ambiguous batch-level `complete=true`.

Each named output should carry its own:

- status;
- coverage;
- selection semantics;
- count/group completeness where applicable;
- error if one output cannot execute.

The batch should support partial mechanical success without converting one failed output into fake absence for another.

---

## 15. Finding: benchmark fairness requires controlling provider/model variance

The historical parallel setup used Native/GMI1 and TraceCite/GMI2, which is useful for throughput but confounds product behavior with provider/model endpoint behavior.

For architectural acceptance, preferred order is:

1. same Agent + same model + same provider/endpoint, run sequentially if necessary;
2. if separate endpoints are required, use a cross-over pair where practical:
   - Native on endpoint A / TraceCite on B;
   - Native on B / TraceCite on A;
3. classify 429/overload runs as infrastructure-affected and repeat when they could dominate wall time or answer completion.

The user's requested 7-minute Agent limit remains fixed at 420 seconds for valid product comparisons.

---

## 16. Finding: token success needs an explicit engineering metric

Provider token fields may distinguish fresh input, cache reads, and output with provider-specific billing semantics.

For this development loop record at least:

- fresh input tokens;
- cached input tokens;
- output tokens;
- model calls;
- tool calls;
- model-visible tool-result bytes where measurable.

Engineering context-read volume may be compared as `fresh_input + cached_input`, but it must be labeled as an engineering context-volume metric rather than universal billing cost.

Acceptance requires TraceCite to be clearly lower in model context pressure; a tiny token reduction with substantially more orchestration is not sufficient.

---

## 17. Final first coding slice

After this review, the initial implementation scope is narrowed to:

### Core

1. introduce minimal internal Plan/IR structures only for currently supported deterministic Evidence operations needed by batch aggregate/selection execution;
2. add a batch compute request containing a bounded number of named analysis programs;
3. bind all programs to the same SessionSourceView/source version;
4. fuse compatible JSONL/Record scans and field parsing where safe;
5. produce per-output bounded aggregate/top-K/scalar results;
6. preserve canonical Evidence/Segmenter/SourceVersion semantics and use canonical fallback when fusion is unsafe;
7. add equivalence tests comparing batch outputs with independent canonical calls;
8. add large-JSONL performance regression for one scan vs repeated scans.

### MCP

1. expose one compact `tracecite_analyze`/`tracecite_compute` style tool for the batch request;
2. keep transport projection bounded and avoid duplicated metadata;
3. remove investigation-strategy rules from the TraceCite Skill;
4. teach only the generic semantics: batch already-known mechanical work into one call; Runtime does not choose what analysis is relevant.

### Explicitly deferred

- autonomous natural-language analysis planning;
- RCA-specific contrast policy;
- causal ranking;
- general UDF/VM/WASM;
- arbitrary joins;
- automatic Host history rewriting;
- broad public API migration away from `tracecite_run`.

---

## 18. Go / No-Go after adversarial review

### Generality

**GO.** The first slice is generic batching/shared computation over authorized evidence and does not encode the current case.

### Semantic boundary

**GO only after Skill cleanup.** Runtime executes caller-selected mechanics; causal strategy/stopping guidance must be removed from TraceCite product instructions.

### Complexity

**GO for the narrow slice. NO-GO for full vNext rewrite.** Minimal IR + batch/shared scan is small enough to validate; a full programming VM is not justified yet.

### Native comparison

**Conditional GO.** The architecture must prove itself in paired runs. If the narrow slice cannot reduce model/context cost without losing time or answer quality, do not keep adding layers just to justify the design.

### Final decision

> **Proceed to coding only for the narrow Core batch/shared-scan + compact MCP analyze surface, after removing strategic Skill coaching. Keep ADR 0003 `proposed` until regression and 7-minute paired acceptance gates pass.**

---

## 19. Post-code acceptance loop

After implementation:

1. full relevant Core/MCP regression must pass;
2. run the blind RCA pair with 420-second Agent timeout;
3. manually compare Native and TraceCite answers before consulting hidden annotation;
4. then check actual fault truth and classify errors;
5. compare wall time, fresh/cached input, output, model calls, tool calls, spill/timeout behavior;
6. inspect 429s separately and rerun infrastructure-affected pairs;
7. for every product failure, fix only a concrete generic defect and add a generic regression;
8. rerun;
9. continue until TraceCite is lower-context/token, no slower on a valid pair, and manually no worse in answer quality, or until evidence shows the architecture itself should be rejected/rethought.

No current-case rule is permitted to enter Runtime, MCP projection, Skill, or tests during this loop.
