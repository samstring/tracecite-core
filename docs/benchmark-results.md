# TraceCite Agent benchmark results

[简体中文](benchmark-results.zh-CN.md)

Status: validated paired measurements for the `feature_for_agent` CA258 baseline. Updated 2026-09-02.

## How to read these numbers

These are paired Native-vs-TraceCite Agent runs under the same model conditions. They measure a specific host/model/prompt/case combination; they are **not** a universal claim that TraceCite always saves a fixed percentage of tokens or always beats `grep`.

Evaluation order is correctness first:

1. the run must be infrastructure-valid;
2. answer quality/evidence support must not regress materially;
3. provenance/recoverability must be preserved;
4. then context/token/model/tool efficiency is compared.

Provider 429/quota/outage or harness failures are infrastructure-invalid and are not counted as product/model failures.

## Validated bounded Pi setup

The formal paired runs use Pi with a shared bounded prompt:

```text
You are a coding agent investigating supplied runtime evidence. Keep the investigation bounded. Once the root cause is sufficiently supported, answer immediately instead of performing confirmatory searches. Cite exact evidence lines for material factual claims.
```

Native adds:

```text
Use only evidence from files in the current working directory and do not use external knowledge.
```

TraceCite adds:

```text
Follow the user's explicit request to use TraceCite. All runtime-evidence content must be obtained through TraceCite tools; do not use native file-access tools for the evidence.
```

TraceCite exposes only `tracecite_search` and `tracecite_expand` through the Pi adapter and loads `.pi/skills/tracecite/SKILL.md`.

## Suite A: four public root-cause cases, two repeats

Cases:

1. containerd #6772
2. Kubernetes #140039 / runc #5347
3. Kubernetes #141283 compatibility feature gate
4. Kubernetes #141402 PodCertificate readiness

Model: MiniMax M3. Eight paired outputs (four cases × two repeats).

| Metric | Native | TraceCite | TraceCite delta |
|---|---:|---:|---:|
| Pass | 6 / 8 | 6 / 8 | equal |
| Concept recall | 78.125% | 87.500% | +9.375 pp |
| Evidence marker recall | 93.750% | 90.625% | -3.125 pp |
| Input tokens | 543,333 | 341,232 | -37.2% |
| Output tokens | 89,533 | 52,644 | -41.2% |
| Cache-read tokens | 23,973,873 | 5,991,938 | -75.0% |
| Model calls | 530 | 195 | -63.2% |
| Tool calls | 477 | 357 | -25.2% |
| Input + output | 632,866 | 393,876 | -37.8% |
| Input + output + cache | 24,606,739 | 6,385,814 | -74.0% |

Workflow run: https://github.com/samstring/tracecite-core/actions/runs/33620265562

Interpretation: scored pass rate was unchanged, average concept recall improved, marker recall was slightly lower, and TraceCite materially reduced model-visible/context-cache work in this suite.

## Suite B: MB-scale public evidence, two repeats

Cases:

- Longhorn #7843: ~17.8 MB model-visible original evidence.
- Harvester #6253: ~7.7 MB model-visible original evidence.

The benchmark branch was created from the exact CA258 implementation/skill/runtime baseline and added only case/workflow files for this run. Model: MiniMax M3. Four paired outputs (two cases × two repeats).

| Metric | Native | TraceCite | TraceCite delta |
|---|---:|---:|---:|
| Pass | 2 / 4 | 2 / 4 | equal |
| Concept recall | 87.5% | 87.5% | equal |
| Evidence marker recall | 75.0% | 75.0% | equal |
| Input tokens | 494,553 | 289,824 | -41.4% |
| Output tokens | 32,836 | 34,194 | +4.1% |
| Cache-read tokens | 13,193,560 | 3,078,682 | -76.7% |
| Model calls | 276 | 83 | -69.9% |
| Tool calls | 193 | 196 | +1.6% |
| Input + output | 527,389 | 324,018 | -38.6% |
| Input + output + cache | 13,720,949 | 3,402,700 | -75.2% |

Workflow run: https://github.com/samstring/tracecite-core/actions/runs/33638574962

### Longhorn aggregate

| Metric | Native | TraceCite |
|---|---:|---:|
| Pass | 2 / 2 | 2 / 2 |
| Input tokens | 269,345 | 120,760 |
| Output tokens | 18,190 | 11,567 |
| Cache-read tokens | 6,075,402 | 633,725 |
| Model calls | 116 | 25 |
| Tool calls | 72 | 50 |

Observed deltas: input -55.2%, cache -89.6%, model calls -78.4%, tool calls -30.6%.

### Harvester aggregate

| Metric | Native | TraceCite |
|---|---:|---:|
| Concept recall | 87.5% | 100% |
| Evidence marker recall | 50% | 50% |
| Input tokens | 225,208 | 169,064 |
| Output tokens | 14,646 | 22,627 |
| Cache-read tokens | 7,118,158 | 2,444,957 |
| Model calls | 160 | 58 |
| Tool calls | 121 | 146 |

Observed deltas: input -24.9%, cache -65.7%, model calls -63.8%, tool calls +20.7%, output +54.5%.

This is a useful example of the runtime trading more targeted evidence operations for fewer model rounds/context replay.

## Scorer caveats

The tables above preserve raw benchmark scorer output; no manual points are added.

Manual review of Longhorn gmi1 found that the TraceCite answer explicitly stated that the old `NodeUnpublishVolume` happened **after** the new pod's `NodePublishVolume`. That is logically equivalent to the gold concept “new publish before old unpublish,” but the concept regex expected the opposite wording order and marked it missing. This is a scorer false-negative, not an evidence-retrieval miss.

Longhorn gmi2 was different: the relevant Publish/Unpublish evidence had been retrieved, but the final answer did not explicitly correlate the old/new pod events into that temporal edge. That is an evidence-synthesis gap, not a retrieval-availability gap.

Harvester failures in this suite were primarily strict exact-marker/citation presentation failures. TraceCite reached 100% concept recall in both Harvester repeats.

## What the benchmark supports

The validated evidence supports the following limited claims:

- TraceCite can preserve comparable scored root-cause quality while substantially reducing input/cache/model-round cost on the tested bounded Pi cases.
- The reduction is not simply “fewer tool calls.” In the MB suite, total tool calls were essentially equal (193 vs 196) while model calls fell from 276 to 83 and cache-read tokens fell by 76.7%.
- Benefit depends on evidence topology and Agent behavior; highly selective local `grep` remains a strong baseline.
- Correctness and evidence boundary remain acceptance gates. A smaller run that times out, overclaims, or loses required causal support is not a win.

## What it does not prove

These runs do not prove that:

- every TraceCite query is smaller than `grep`/`rg`;
- every model will show the same percentage reduction;
- larger evidence automatically improves TraceCite's relative advantage;
- the benchmark scorer perfectly captures semantic equivalence;
- token reduction alone establishes better diagnosis.

When adding new benchmark results, preserve the exact model, prompt, cases, run validity, raw scorer output, and usage totals so comparisons remain auditable.
