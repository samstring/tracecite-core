# Real Evidence Scale Benchmark

This benchmark measures how Agent investigation cost and answer quality change as the amount of **real evidence** grows. It must not manufacture scale by repeating one log line or duplicating the same incident fixture.

## Size ladder

| Tier | Target prepared evidence size | Purpose |
|---|---:|---|
| S | 10–50 KiB | fixed Agent/tool overhead and simple incident localization |
| M | 100–500 KiB | small real log bundles |
| L | 1–5 MiB | ordinary application/system logs |
| XL | 10–50 MiB | noisy incident investigation |
| XXL | 100–300 MiB | large production-style evidence |
| XXXL | 500 MiB+ | stress/scale behavior and bounded evidence transport |

The exact byte count does not need to be identical between datasets. Prefer natural dataset boundaries. For paired scaling experiments, use one real target incident/fault and add **different real records/traces from the same source dataset** as background evidence. Do not copy or repeat the target record to reach a requested size.

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

## Paired scale experiment

Preferred experiment for large evidence:

1. Choose one real TraceBench failure scenario with a hidden injected-fault identity.
2. Keep the same target faulty trace(s) at every tier.
3. Add real non-target TraceBench records/traces to reach increasing evidence sizes.
4. Keep question, model, provider, sampling settings and evaluation truth identical.
5. Compare `free_shell` and Tracecite with the exact same prepared evidence bytes.

This isolates the effect of evidence scale/noise from incident difficulty.

## Required measurements

For every mode and tier record:

- prepared evidence bytes;
- provider-reported input/output tokens;
- model calls;
- tool calls;
- tool output bytes/chars;
- exact duplicate tool output;
- wall time;
- peak RSS where available;
- target evidence recall;
- concept/root-cause recall when root-cause-grade;
- citation accuracy / unsupported claims when evaluator support is available;
- timeout/provider-error status.

A token/tool-call win is valid only when answer-quality gates are preserved.

## Large-file fairness rules

- Inputs are downloaded/pinned and checksum-verified before the Agent run.
- Prepared benchmark inputs are immutable. Tracecite adapters may therefore disable redundant per-search snapshots, but this must be stated in results.
- Do not add benchmark-only output caps that differ by mode.
- Product-level bounded projections/recovery mechanisms are allowed and must be reported as product behavior.
- A large-file Tracecite first action should use bounded survey/sample semantics; it must not implement `inspect` by wildcard-returning the entire file.
- Repeated searches that reveal no new evidence should produce an explicit no-growth/coverage signal rather than replaying evidence.

## Candidate public scale anchors

Published Loghub archive sizes provide useful download anchors (compressed archive sizes are not treated as prepared evidence size):

- Proxifier: ~172 KiB archive
- Linux: ~232 KiB archive
- Mac: ~1.5 MiB archive
- HealthApp: ~2.3 MiB archive
- Hadoop: ~3.4 MiB archive
- OpenStack: ~5.4 MiB archive
- BGL: ~57.5 MiB archive
- HDFS_v1: ~186.6 MiB archive
- HDFS_v3 TraceBench: ~567.4 MiB archive
- HDFS_v2: ~823.7 MiB archive

Prepared/uncompressed evidence bytes must be measured after extraction and recorded in the benchmark result.
