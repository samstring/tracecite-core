# 0002: Candidate-first evidence search

- Status: accepted
- Date: 2026-09-04
- Owners: TraceCite Core
- Supersedes:
- Superseded by:

## Context

Historically `filter_text()` segmented every scoped source into logical records before evaluating the query. That ordering preserved record-level regex semantics, but it made a sparse search pay the full segmentation cost for every record. It also accumulated `unmatched_summary` so Runtime could derive `next_queries`, coupling evidence retrieval to query-planning suggestions.

For large logs this was the wrong cost model: a search for a small number of known anchors could still parse and construct every logical record. `next_queries` was advisory Agent navigation rather than Evidence, so it was not a valid reason to require full unmatched-record processing.

The search path must preserve two correctness properties:

1. candidate prefiltering must never introduce false negatives relative to the existing Matcher semantics;
2. a raw candidate must never become Evidence until the original query succeeds on the complete logical record.

This is especially important for multiline regular expressions. A raw expression may appear to span two independent records, while a valid same-record match may span multiple physical lines.

## Decision

`search`/`filter_text` use a conservative candidate-first execution plan whenever Core can prove that the raw prefilter is complete:

```text
raw source
   -> conservative candidate scan
   -> candidate physical lines
   -> reconstruct only intersecting logical records
   -> re-run the original Matcher on each complete record
   -> matched-record artifacts / Evidence
```

The first pass may return false positives. The final full-record Matcher is the semantic gate and removes them.

Candidate-first is currently allowed for:

- pure literal / literal-OR queries;
- regexes for which Core can derive a required literal anchor set that covers every successful match path;
- built-in segmenters whose candidate record can be reconstructed without changing boundary semantics.

Examples:

- `needle` locates physical candidate lines before record construction;
- `(?s)failed.*timeout` may use a required literal anchor, reconstruct the containing multiline record, then re-run the DOTALL regex on that record;
- `failed` in one record and `timeout` in the next may produce a raw candidate, but final record-level re-check rejects the cross-record false positive.

Core must fall back to the segment-first path when completeness cannot be proven. Current intentional fallbacks include:

- regexes with no safe mandatory literal candidate;
- Unicode or scoped ignore-case semantics that the raw prefilter cannot mirror exactly;
- record-semantic scopes such as PID/time/line/tail filtering until equivalent candidate-scoped handling is proven;
- custom segmenters and continuation rules without a sound candidate-boundary contract;
- candidate sets that exceed configured density/size limits and would not provide a useful sparse-search win.

`candidate_strategy` records whether a result used `candidate-first:<strategy>` or `segment-first` so execution behavior remains observable.

`next_queries` is removed from `AgentResult`. Ordinary search no longer analyzes unmatched records to teach the Agent what to search next. `unmatched_summary` is not published by the canonical candidate-first filter result. Query planning belongs to the Agent or to an explicit future exploration capability, not to Evidence retrieval.

`signal_hints` are unaffected. They operate downstream on already matched Evidence artifacts and remain part of evidence navigation, not query planning.

## Alternatives considered

### Segment every record before matching

Rejected as the default because sparse known-anchor searches still pay full record construction/parsing cost.

### Raw regex result becomes Evidence directly

Rejected because raw matching can span logical record boundaries and violate the Evidence contract.

### Candidate-first for every regex

Rejected because a prefilter that cannot prove completeness could silently drop valid Evidence. Correctness takes priority over the fast path.

### Keep `unmatched_summary` / `next_queries` in ordinary search

Rejected because it forces work over nonmatching records for an advisory feature and mixes Agent planning with deterministic Evidence retrieval.

## Consequences

Positive:

- sparse literal and safely anchored regex searches avoid constructing unrelated logical records;
- zero-hit literal searches can complete without segmenting records;
- multiline and cross-record correctness is retained by final full-record re-check;
- Agent planning is decoupled from Evidence retrieval;
- execution strategy is observable for benchmarks and regressions.

Costs and risks:

- some searches still require a full raw scan and a boundary scan, so the optimization is about avoiding full record construction/parsing rather than eliminating O(N) input inspection;
- conservative fallback means complex regexes or scoped searches may retain the old cost;
- candidate extraction must remain a no-false-negative proof. Any new regex/segmenter optimization requires regression tests before enabling it.

Compatibility:

- `next_queries` is intentionally removed without a compatibility shim because this branch is pre-release;
- `unmatched_summary` is no longer part of the canonical filter result projection;
- Evidence artifacts, record-level final matching, EvidencePointer integrity, and `signal_hints` semantics remain unchanged.

## Migration and validation

Validation includes:

- sparse literal search constructs only the candidate record;
- zero-hit literal search constructs zero records;
- multiline DOTALL same-record match succeeds;
- cross-record DOTALL raw false positive is rejected;
- regexes without a safe literal candidate fall back to segment-first;
- scoped local IGNORECASE falls back without missing the match;
- safe ASCII global IGNORECASE remains candidate-first;
- `filter_texts()` inherits the same candidate-first behavior;
- `next_queries` and canonical `unmatched_summary` are absent from published results;
- the full Core CI matrix passes on Linux/macOS and supported Python versions.

The Runtime `search`, Agent `QueryTarget`, Scenario filter path, Core CLI filter path, and Integration CLI search path all route through the canonical filter/search surface. `sample`, `survey`, `probe`, time-range analysis, and downstream event transforms intentionally keep their own record-processing semantics because they are not query-match paths.

## Documentation updates

This ADR records the execution-order invariant and the removal of search-planning suggestions. The existing top-level architecture boundary remains unchanged: Agent owns exploration/planning; Evidence Core owns deterministic retrieval and Evidence production. Follow-up edits to the bilingual top-level architecture documents should incorporate this execution invariant when those documents are next revised; this ADR is normative for candidate-first search behavior in the meantime.
