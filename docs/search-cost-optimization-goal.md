# TraceCite Search Cost Optimization Goal

Status: active
Date: 2026-09-04
Branch: `experiment/evidence-intelligence-search-cost-v2`
Baseline: `experiment/evidence-intelligence`

## Goal

Large local evidence sources must not pay repeated whole-file work for every query beyond what is required to preserve evidence correctness and provenance.

Keep the existing evidence contract:

- immutable evidence identity is content-based (`sha256`)
- evidence remains line-addressable (`source_path` + `start_line` / `end_line`)
- raw candidates never become Evidence directly
- every candidate logical record is re-checked by the exact Matcher before becoming a match
- truncated Agent output must still preserve bounded late high-signal navigation (`signal_hints`)
- materialization must verify that the requested immutable content version is still the expected version

## Performance principles

1. Prove a source/content version once per operation, not once per layer or EvidencePointer.
2. Never hash the same path repeatedly inside one operation when the same verified digest can be reused.
3. Candidate search should avoid a second whole-file pass when the segmenter can reconstruct the complete logical record during the first pass (especially JSONL / raw line).
4. Keep full match discovery for coverage and `signal_hints`, but do not require full match materialization merely because only a bounded number of EvidencePointers are returned to the Agent.
5. Do not replace cryptographic integrity with mtime/size-only checks in this optimization pass.
6. `next_queries` and planner-style recommendations must not be produced internally and stripped later; Runtime should expose evidence facts and gaps, not query planning.

## Acceptance gates

### Correctness

- Existing Core/runtime tests pass.
- Candidate-first no-false-negative regressions pass.
- EvidencePointer SHA + line-range provenance remains unchanged.
- Late high-severity matches remain discoverable as `signal_hints` even when inline Evidence is truncated.
- Materialize/replay integrity tests pass.

### Large-file search benchmark

Use RCAEval case `re3tt_ts-route-service_f3_6` (`traces.jsonl`, ~76 MB / ~242k lines), matching the previous profile.

Prior baseline before candidate-first was approximately 59 seconds/search. Current candidate-first baseline measured in this work is approximately:

- zero-match query: 7.4 s
- `503`: 8.45 s
- `ts-route-service`: 11.9 s

The optimization is not considered complete merely because it is faster than 59 seconds. The remaining repeated whole-file costs must be removed where correctness does not require them.

### Real Agent test

Run a real model/Pi investigation against the same large RCAEval source through the canonical TraceCite tool path. Record:

- every TraceCite search query
- per-tool wall time
- number of searches/materializations
- whether the answer is supported by cited Evidence
- whether repeated queries repeatedly pay avoidable whole-file work

If the real Agent path still exhibits large repeated per-search overhead caused by TraceCite implementation rather than unavoidable query scanning/match volume, continue optimizing and repeat the gates.

## Non-goals for this pass

- replacing full SHA verification with metadata-only fingerprints
- introducing a persistent inverted index / external search engine
- weakening snapshot/evidence immutability semantics
- teaching TraceCite which query the Agent should run next
