# 0002: Agent Evidence Shell and SourceVersion

- Status: accepted
- Date: 2026-09-05
- Owners: TraceCite maintainers
- Supersedes: high-cardinality Agent search projection through complete EvidenceIndex locators
- Superseded by:

## Context

The previous Agent text-search path already provided segmentation, EvidencePointer identity, provenance, RetrievalSession novelty/coverage, materialization, and exact citation, but RCA benchmarks exposed several transport and large-source problems:

- repeated search calls could snapshot, count, or hash the same source again;
- live-source full-copy snapshots became expensive as files grew;
- Agent hot paths wrote and reread `matched_records.jsonl`, `hits.jsonl`, `evidence.log`, and filter history artifacts;
- a high-cardinality search could become a complete `EvidenceIndex` locator list and enter model context;
- multi-step search/filter/aggregate workflows exposed intermediate results at every Agent tool boundary;
- candidate-count limits did not reliably constrain actual token payload.

One RCA comparison demonstrated the failure mode directly: a low-selectivity query matched essentially every row, the EvidenceIndex exposed roughly 173k line locators, and the following model request became hundreds of thousands of fresh input tokens.

TraceCite already contained useful foundations that should be reused rather than replaced: SourceVersion identity, candidate search/recovery primitives, Segmenters, RetrievalSession novelty/repetition/coverage, exact materialization, `live_cut`, and `segment_store`.

## Decision

Adopt a SourceVersion-bound, budget-gated Evidence Shell for Agent text investigation.

1. One user-question retrieval context resolves one stable `QuestionSourceView` / SourceVersion. Repeated Agent search operations in that question reuse the same immutable view.
2. At a later question, a cheap file fingerprint may reuse an already verified snapshot/version, SHA, and line metadata when the source has not changed.
3. Live sources prefer cooperative `live_cut` plus immutable segments. If writer cooperation is unavailable, the fallback captures only newly appended complete bytes after the first capture when append-only continuity is mechanically verified.
4. `tracecite_run` / Evidence Shell is the primary Agent text-search surface. Mechanical search/filter/aggregate/navigation stages execute inside Runtime in one tool call.
5. Existing public `QueryTarget` search reduces to the same Evidence Shell contract rather than the old EvidenceIndex projection.
6. Raw search occurs before logical Record materialization whenever local recovery is safe. The selected Segmenter restores the complete logical Record for each candidate hit. Scoped or semantically unsafe cases may fall back to full Record iteration.
7. The Agent search hot path is artifact-free: it does not require `matched_records.jsonl`, `hits.jsonl`, `evidence.log`, filter history, or unmatched-token summaries.
8. Maximum Evidence transport tokens/bytes are User/Host Policy. Agent tool arguments cannot raise or bypass the configured budget.
9. Ordinary search semantics are all-or-refine. If the complete final matched-record payload exceeds policy, return `status=too_broad`, `reason=MATCHED_EVIDENCE_BUDGET_EXCEEDED`, zero Evidence, and require query/scope refinement.
10. Explicit `first`/`last`/`head`/`tail`/`take`/`near`/`seek` operations are valid only when subset/position semantics are intentionally requested; their incompleteness remains explicit.
11. Aggregate stages may process arbitrarily large intermediate match sets inside Runtime. If the aggregate output itself exceeds the user transport policy, return `AGGREGATE_OUTPUT_BUDGET_EXCEEDED` rather than dumping it.
12. The shell supports literal search, safe regex search, grep-style fixed/regex/invert/case-insensitive predicates, structured `where`, field existence/missing predicates, line scopes, sort/reverse, selection/navigation, and count/group/distinct operations.
13. Once TraceCite establishes SHA for an immutable snapshot/segment, downstream shell EvidencePointer creation, managed materialize, and replay reuse the cached SHA. External mutable paths not owned by SourceVersionStore still require integrity verification.
14. Snapshot creation computes SHA and line count in the same copy/read pass. Agent search no longer performs separate `count snapshot + count original` passes.
15. SourceVersionStore persists both latest source state and question-bound historical views, so old immutable segment SHA metadata remains replayable after a newer source version exists.
16. Existing provenance, RetrievalSession novelty/repeated-evidence suppression/coverage, materialization, and citation semantics remain the canonical Evidence integrity layer downstream of search.
17. The Agent skill explicitly teaches Evidence Shell syntax, user-owned budget behavior, `too_broad` refinement, SourceVersion stability, and exact materialization from the returned immutable pointer path/SHA.

## Source modes

### Mutable file (default Agent local-source mode)

At the first access for a question, TraceCite creates an immutable snapshot while simultaneously calculating SHA and line count. The question then remains bound to that snapshot regardless of later changes to the original path.

At a later question, TraceCite first compares a cheap source fingerprint (`device`, `inode`, `size`, `mtime_ns`, `ctime_ns`). If unchanged and the cached snapshot still exists, the previous snapshot and SHA are reused with no copy, full hash, or line recount.

### Static source

A host may explicitly declare a source static/immutable. TraceCite can use the original path as the immutable segment, calculate identity once, and reuse it while its fingerprint remains unchanged.

### Live source

A live source is logically represented by ordered immutable segments. TraceCite first offers a cooperative LiveCut request to the writer. A cooperating writer can rotate the current file to a stable segment in O(1) filesystem metadata work, then continue writing a new live file.

Without writer cooperation, TraceCite uses an append-only fallback: it verifies continuity at the previous captured boundary and copies only newly appended complete bytes into a new immutable segment. Historical segments are reused and each segment is hashed once.

A QuestionSourceView identity is a digest of the ordered immutable segment manifest; individual EvidencePointer provenance remains bound to the exact segment SHA and segment-local line range.

## Evidence Shell execution model

```text
Agent program
    ↓
QuestionSourceView
    ↓
raw literal / raw regex candidate search
    ↓
Segmenter restores complete Record
    ↓
search / grep / where / exclude / sort / near / aggregate ...
    ↓
intermediate rows remain Runtime-internal
    ↓
User/Host Evidence budget gate
    ├─ too large → too_broad, zero Evidence, refine
    └─ fits      → EvidencePointer candidates
                         ↓
                    materialize
                         ↓
                 exact raw Evidence + citation
```

No complete high-cardinality locator list is part of the Agent search contract.

## Alternatives considered

### Keep native Agent shell as the only search mechanism

Rejected as the TraceCite integration contract. A strong Agent can make native shell token-efficient with one pipeline, but native shell does not automatically enforce immutable source identity, user-owned output budgets, RetrievalSession deduplication, or exact Evidence provenance.

### Keep EvidenceIndex and compact only its rendering

Rejected for Agent text search. It still makes high-cardinality locator navigation an Agent concern and encourages repeated model/tool turns over a large result set.

### Always return a fixed first-N candidate set

Rejected because prior RCA tests lost relevant evidence occurring after the prefix. First-N is only valid as explicit selection semantics.

### Make the Agent choose `max_evidence_tokens`

Rejected because an Agent could respond to an oversized result by increasing the budget and recreate the context-explosion problem.

### Require a public MatchSet API

Deferred. Internal result sets/handles may still be useful later, but the current all-or-refine shell contract does not require a public MatchSet abstraction.

### Copy every live source on every user question

Rejected for large append-heavy sources. LiveCut/immutable segments or verified incremental append capture avoid repeatedly copying and hashing all historical bytes.

## Consequences

Positive:

- high-cardinality search output cannot become an EvidenceIndex dump in the Agent query path;
- token efficiency no longer depends entirely on the Agent writing perfect native shell pipelines;
- multi-step mechanical search executes in one Runtime invocation;
- common literal/regex searches locate raw candidates before JSON/record parsing;
- complete logical Records remain the Evidence admission unit;
- unchanged sources reuse prior snapshot + SHA;
- live sources reuse historical immutable segments;
- managed materialize/replay avoid rehashing already verified snapshots;
- the Agent hot path no longer requires matched-record/filter artifacts.

Costs and risks:

- `AgentResult.status` includes additive `too_broad`;
- Evidence Shell is a public execution surface and requires continued safety/parity validation;
- time-scoped or locally unrecoverable multiline formats can still require full Record scans to preserve semantics;
- host integration must define the user-question retrieval-context boundary when a long-lived host session spans multiple user turns;
- live-cut performance is best with writer cooperation; the fallback assumes mechanically verified append continuity;
- deterministic token estimation is model-agnostic, so the exact byte cap remains a second hard transport guard.

## Migration status

Implemented on `feature_for_agent_refacotr_shell`:

1. `EvidenceShellPolicy`, `EvidenceShellRequest`, `run_evidence_shell`, and `too_broad`.
2. Pi Agent `tracecite_run` without Agent-owned budget parameters.
3. Updated TraceCite Agent skill.
4. Artifact-free logical Record search.
5. Raw-hit candidate-first parsing for locally recoverable formats.
6. Public QueryTarget search routed through Evidence Shell; Agent query path no longer uses EvidenceIndex projection.
7. SourceVersion fingerprint cache and question-bound immutable views.
8. LiveCut + immutable segment/incremental append fallback.
9. SHA/line-count fusion during snapshot creation and SHA reuse during managed materialize/replay.
10. RetrievalSession novelty/repeated Evidence behavior retained after shell admission.

Still intentionally deferred until validation phase:

- running the full existing regression suite;
- Native-vs-TraceCite RCA benchmark reruns and performance measurements;
- any public ResultHandle/MatchSet API.

Validation remains correctness/support/provenance/recoverability first, then token/I/O/wall-time efficiency. `too_broad` must not mutate `seen_evidence`/Coverage because no Evidence was admitted.

## Documentation updates

This decision is reflected in:

- `docs/architecture.md`
- `docs/architecture.zh-CN.md`
- `.agents/skills/tracecite-investigate/SKILL.md`
- `docs/migrations/0002-evidence-shell-too-broad.md`
- Pi Agent benchmark/integration adapter schemas
