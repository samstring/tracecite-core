# 0002: Agent Evidence Shell and SourceVersion

- Status: accepted
- Date: 2026-09-05
- Owners: TraceCite maintainers
- Supersedes: high-cardinality Agent search projection through complete EvidenceIndex locators
- Superseded by:

## Context

The current Agent text-search path already provides segmentation, EvidencePointer identity, provenance, RetrievalSession novelty/coverage, materialization, and exact citation. However, the validated RCA benchmarks exposed several transport and large-source problems:

- repeated search calls may snapshot, count, or hash the same source again;
- live-source full-copy snapshots become expensive as files grow;
- Agent hot paths write and reread `matched_records.jsonl`, `hits.jsonl`, `evidence.log`, and filter history artifacts;
- a high-cardinality search can be projected as a complete `EvidenceIndex` locator list, allowing hundreds of thousands of locators to enter model context;
- multi-step search/filter/aggregate workflows can expose intermediate results at every Agent tool boundary;
- candidate-count limits do not reliably constrain the actual token payload admitted to Agent context.

One RCA comparison demonstrated the failure mode directly: a low-selectivity query matched essentially every row, the EvidenceIndex exposed roughly 173k line locators, and the following model request became hundreds of thousands of fresh input tokens. The architecture must make oversized intermediate results impossible to transport by default rather than relying on the Agent to remember to write an optimal `grep | ... | head` pipeline every time.

At the same time, TraceCite already contains useful foundations that should be reused rather than replaced: `SourceVersion` identity, `candidate_search`, Segmenters, RetrievalSession novelty/repetition/coverage, exact materialization, `live_cut`, and `segment_store`.

## Decision

Adopt a SourceVersion-bound, budget-gated Evidence Shell for Agent text investigation.

1. One user question resolves one stable `QuestionSourceView` / `SourceVersion`. All search/run/materialize/replay operations in that investigation use that same immutable version.
2. At a later user question, a cheap file fingerprint may reuse an already verified snapshot/version, SHA, and line/index metadata when the source has not changed.
3. Live sources prefer cooperative `live_cut` plus immutable segments instead of copying the entire accumulated file on every question. Historical segments are reused and hashed once.
4. Introduce `tracecite_run` / Evidence Shell as a small Agent-facing program surface for composing mechanical search/filter/aggregate/navigation work in one tool invocation.
5. The shell must preserve the semantics of existing search capabilities. Backend execution may use candidate scanning, regex, structured extractors, or other registered primitives without exposing backend-specific Agent tools.
6. Raw search hits are passed through the selected Segmenter before Evidence admission. The complete logical record is the minimum candidate unit.
7. Maximum Evidence transport tokens/bytes are User/Host Policy. The Agent request does not contain fields that can raise or bypass the configured budget.
8. Ordinary search semantics are all-or-refine: if the complete final matched-record payload exceeds the configured Evidence budget, return `status=too_broad`, `reason=MATCHED_EVIDENCE_BUDGET_EXCEEDED`, zero Evidence bodies, and an instruction to refine the query/scope. Do not silently return first-N as if complete.
9. Explicit first/last/top/take/sample operations remain valid only when selection semantics are intentionally requested; their incompleteness must remain explicit.
10. Oversized match sets and intermediate sets stay inside Runtime. A future stable result handle may reference a server-side MatchSet, but complete locator sets must not be dumped into model context.
11. The new Agent shell path does not use high-cardinality EvidenceIndex projection. Legacy retrieve/index behavior may remain temporarily for compatibility while callers migrate.
12. The target Agent search hot path streams logical Records directly. `matched_records.jsonl`, `hits.jsonl`, `evidence.log`, and filter history may remain optional legacy/debug artifacts but must not be required for Agent execution.
13. Once TraceCite establishes a SHA for an immutable SourceVersion/segment, downstream search, materialize, and bridge code reuse it. Revalidation remains necessary for external mutable paths TraceCite has not frozen.
14. Existing provenance, RetrievalSession novelty/repeated-evidence suppression/coverage, materialization, and citation semantics remain the canonical Evidence integrity layer downstream of search.
15. The Agent skill must explicitly teach `tracecite_run`, the user-owned budget contract, `too_broad` refinement behavior, SourceVersion stability, and exact materialization/citation.

The initial implementation may temporarily reuse `search_text` behind Evidence Shell to retain regex/time/fold/segmenter parity. That compatibility implementation is transitional and does not change the target hot-path decision above.

## Alternatives considered

### Keep native Agent shell as the only search mechanism

Rejected as the TraceCite integration contract. A strong Agent can make native shell token-efficient with one pipeline, but native shell does not automatically enforce immutable source identity, user-owned output budgets, RetrievalSession deduplication, or exact Evidence provenance. TraceCite should make those guarantees runtime defaults rather than Agent coding conventions.

### Keep EvidenceIndex and compact only its rendering

Rejected as the primary Agent search model. A compact index can reduce one payload, but it still makes high-cardinality locator navigation an Agent concern and encourages multiple model/tool turns over a large result set. The preferred behavior is to refine mechanically before Evidence crosses the boundary.

### Always return a fixed first-N candidate set

Rejected because previous RCA tests showed correctness loss when important evidence occurred after the initial prefix. First-N is valid only as explicit selection semantics, not as a hidden approximation to a complete search.

### Make the Agent choose `max_evidence_tokens`

Rejected because an Agent could respond to an oversized result by increasing the budget and recreate the context-explosion problem. Budget is user/host policy; the Agent controls query selectivity instead.

### Introduce a large public MatchSet API first

Deferred. MatchSet/result handles are useful internal/runtime concepts, especially for cross-call reuse, but the minimal P0 can be implemented with the Evidence Shell contract and `too_broad` gate. Public result-set APIs should be added only if real workflows require them.

### Copy every live source on every user question

Rejected for large append-heavy sources. Cooperative live cuts and immutable segments preserve a question-time evidence boundary without repeatedly copying and hashing all historical bytes.

## Consequences

Positive:

- high-cardinality search output is prevented from entering model context by contract;
- token efficiency no longer depends entirely on the Agent writing perfect native shell pipelines;
- Agent mechanical search can be composed inside one tool invocation;
- full logical records, not arbitrary physical hit lines, remain the evidence candidate boundary;
- immutable source/provenance/session semantics are preserved;
- unchanged and live sources can reuse previously frozen/hash-verified bytes;
- the target Agent hot path removes repeated artifact I/O and redundant full-file passes.

Costs and risks:

- `AgentResult.status` gains the additive `too_broad` value, so strict consumer enums must migrate;
- the Evidence Shell parser/runtime becomes a new public execution surface that requires safety and parity tests;
- the first implementation still uses legacy `search_text` artifacts internally, so the I/O/snapshot optimization is not complete yet;
- question-bound SourceVersion caching requires a clear host/user-turn boundary;
- live cut requires writer cooperation or a safe fallback such as CoW clone or a provably append-only bounded view;
- token estimation must be deterministic and conservative enough for transport policy while remaining dependency-light.

## Migration and validation

Migration is staged on `feature_for_agent_refacotr_shell`:

1. Add `EvidenceShellPolicy`, `EvidenceShellRequest`, `run_evidence_shell`, and the additive `too_broad` status.
2. Expose `tracecite_run` in Agent adapters without any Agent-controlled Evidence budget field.
3. Update Agent skill guidance for `too_broad` refinement and materialization.
4. Add tests for under-budget complete results, over-budget zero-Evidence responses, pipeline refinement, structured predicates, aggregate behavior, explicit selection semantics, RetrievalSession repeated-evidence suppression, and `too_broad` session non-pollution.
5. Replace the shell's temporary `search_text` dependency with a streaming Record search hot path that preserves all existing search semantics while dropping required legacy artifacts.
6. Add question-level SourceVersion cache/fingerprint reuse and eliminate redundant snapshot/SHA/count passes.
7. Integrate existing `live_cut` / `segment_store` primitives with immutable segment metadata and per-segment SHA reuse.
8. Re-run existing Native-vs-TraceCite RCA benchmarks, comparing correctness, provider fresh-input tokens, maximum single tool output, full-file I/O passes, and wall time.

Validation gates remain correctness/support/provenance/recoverability first, then efficiency. `too_broad` must not mutate `seen_evidence`/Coverage because no Evidence body was admitted to the Agent.

Rollback remains branch-level until the refactor is accepted back into `feature_for_agent`; legacy canonical operations remain compatibility surfaces during migration.

## Documentation updates

This decision updates or adds:

- `docs/architecture.md`
- `docs/architecture.zh-CN.md`
- `.agents/skills/tracecite-investigate/SKILL.md`
- `docs/migrations/0002-evidence-shell-too-broad.md`
- Pi Agent benchmark/integration adapter documentation and tool schemas as implemented

The implementation-status tables in both architecture documents must accurately distinguish implemented, partially implemented, and planned stages during the refactor.
