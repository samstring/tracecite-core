# Real Evidence Scale Benchmark

This benchmark measures how Agent investigation cost and answer quality change as the amount of **real evidence** grows. It must not manufacture scale by repeating one log line or duplicating the same incident fixture.

## Current scale boundary

For the Evidence Intelligence experiment, **50 MiB is the maximum required model-level scale gate**.

The project has already established the scale behavior it needed to observe at 25 KiB, 5 MiB, and 50 MiB. Runs at 100 MiB, 500 MiB, or larger are no longer required for the current merge decision. Existing larger workflows or dataset notes may remain as optional stress tooling, but they are not part of the acceptance ladder and should not block product work.

The reason is deliberate: after 50 MiB, simply increasing input size provides less decision value than validating that the same evidence-progress semantics live in the canonical runtime and that TraceCite works across multiple real root-cause domains.

## Active size ladder

| Tier | Target prepared evidence size | Purpose |
|---|---:|---|
| S | 10–50 KiB | fixed Agent/tool overhead and simple incident localization |
| L | 1–5 MiB | ordinary application/system logs and context-growth behavior |
| XL | 10–50 MiB | noisy incident investigation and context-boundary behavior |

The exact byte count does not need to be identical between datasets. Prefer natural dataset boundaries. For paired scaling experiments, use one real target incident/fault and add **different real records/traces from the same source dataset** as background evidence. Do not copy or repeat the target record to reach a requested size.

## Verified scale result

The current TraceBench HDFS_v3 corruption experiment uses real fault records plus real normal TraceBench records as deterministic background noise. It is not a hand-written synthetic error log.

With `MiniMaxAI/MiniMax-M3` through the configured GMI OpenAI-compatible endpoint:

- 25 KiB TraceCite candidate: quality gate passed;
- 5 MiB TraceCite candidate: quality gate passed;
- 50 MiB TraceCite candidate: quality gate passed with all required concepts and evidence markers;
- the paired 50 MiB `free_shell` baseline exceeded the model context window after a very large tool result;
- the TraceCite 50 MiB run kept model-visible tool evidence bounded while preserving the required evidence and citations.

This supports a scale-dependent claim: TraceCite's demonstrated value is **bounded, provenance-aware evidence flow**, not that every individual TraceCite search is smaller or faster than `rg`.

These results do **not** justify a universal percentage claim for token savings. Provider-reported cumulative input tokens, model-visible tool-output size, model/tool calls, quality, and context failures must be interpreted together.

## Truth grades

### Root-cause-grade

A case can support root-cause claims only when the hidden evaluator has independent truth such as:

- maintainer diagnosis plus merged fix commit/PR;
- controlled fault injection identity that is not exposed to the Agent;
- a dataset trace class whose fault type is independently recorded by the experiment.

The Agent receives runtime evidence only. Hidden diagnosis/fault identity/fix data must not appear in the question or input evidence unless that information is naturally observable in the runtime evidence itself.

### Retrieval-grade

Datasets with anomaly/alert labels but no causal diagnosis are useful for:

- locating the correct abnormal trace/window/component;
- evidence recall;
- false-positive rate;
- tool/model calls and provider tokens;
- wall time and peak memory.

They must not be used to claim root-cause accuracy.

## Initial real datasets

- Existing pinned GitHub incident cases: small root-cause-grade cases using independent maintainer fixes as hidden truth.
- Loghub HDFS_v3 / TraceBench: root-cause-grade candidate. TraceBench contains normal traces and traces collected under injected faults, including process, network, data, system and known Hadoop bug scenarios.
- Loghub HDFS_v1: retrieval-grade. Traces are grouped by block id with normal/anomaly ground truth.
- Loghub BGL: retrieval-grade. Real Blue Gene/L supercomputer logs with alert/non-alert labels.
- Loghub OpenStack: retrieval-grade by default; individual failure-injection cases may be promoted to root-cause-grade only after their injected fault truth is pinned and independently verified.

Large public datasets remain useful as future optional stress/retrieval fixtures, but dataset size alone is no longer a current milestone.

## Paired scale experiment

Preferred experiment for active scale validation:

1. Choose one real TraceBench failure scenario with a hidden injected-fault identity.
2. Keep the same target faulty trace(s) at every active tier.
3. Add real non-target TraceBench records/traces to reach increasing evidence sizes, up to 50 MiB.
4. Keep question, model, provider, sampling settings and evaluation truth identical.
5. Run the TraceCite candidate before a potentially pathological baseline so baseline quota/context behavior cannot starve the candidate.
6. Compare `free_shell` and TraceCite with the exact same prepared evidence bytes.

This isolates the effect of evidence scale/noise from incident difficulty.

A baseline context-window or tool-capability failure is retained as comparison evidence; it does not convert a passing TraceCite candidate into a failure. Provider quota/rate/unavailability affecting the TraceCite candidate is infrastructure-inconclusive and should not be classified as a product failure.

## Required measurements

For every mode and tier record:

- prepared evidence bytes;
- provider-reported input/output tokens;
- provider-reported cached input tokens when available;
- model calls;
- tool calls;
- tool output bytes/chars;
- exact duplicate tool output;
- estimated tool-output tokens as a clearly labelled estimate only;
- wall time;
- peak RSS where available;
- target evidence recall;
- concept/root-cause recall when root-cause-grade;
- citation accuracy / unsupported claims when evaluator support is available;
- timeout/context/provider-error status.

The benchmark should additionally evolve toward reporting scanned bytes, unique evidence growth, repeated-evidence ratio, source coverage, and attempted context load. These are especially important when a baseline fails before the provider can return a usage record for the oversized next request.

A token/tool-call win is valid only when answer-quality gates are preserved.

## Large-file fairness rules

- Inputs are downloaded/pinned and checksum-verified before the Agent run.
- Prepared benchmark inputs are immutable. TraceCite adapters may therefore disable redundant per-search snapshots, but this must be stated in results.
- Do not add benchmark-only output caps that differ by mode.
- Product-level bounded projections/recovery mechanisms are allowed and must be reported as product behavior.
- A large-file TraceCite first action should use bounded survey/sample semantics; it must not implement `inspect` by wildcard-returning the entire file.
- Repeated searches that reveal no new evidence should produce an explicit no-growth/coverage signal rather than replaying evidence.
- Fixture build, hashing, validation, and other benchmark infrastructure should stream large inputs rather than using unnecessary whole-file `read_text()` / `read_bytes()` copies.

## What comes after scale validation

The active next steps are not larger byte tiers. They are:

1. move proven Evidence Progress / novelty / coverage stop semantics from the benchmark adapter into the canonical runtime;
2. improve investigation-cost metrics and repeated-evidence reporting;
3. expand the real root-cause suite across independent domains with maintainer diagnosis/fix truth;
4. rerun 25 KiB / 5 MiB / 50 MiB only when product-runtime changes can affect those gates.
