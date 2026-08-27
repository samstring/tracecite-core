# TraceCite Agent Investigation Benchmark

This benchmark measures complete debugging investigations on public, real-world incidents rather than synthetic grep tasks.

## Goal

Compare the same Agent, question, and source data under three tool modes:

1. `shell_rg` — shell + `rg`/line-context tools.
2. `tracecite` — TraceCite compact/Ledger transport without cross-turn seen-state.
3. `tracecite_context` — TraceCite + Evidence Ledger + Context Engine (`context_id`), so previously seen Evidence is suppressed on later turns.

The primary metric is **total investigation context cost**, not the size of one command response. Correctness and recoverable Evidence are gates: a cheaper run that reaches the wrong conclusion does not win.

The model-level isolation/tool rules are normative for this benchmark; see [HOST_PROTOCOL.md](HOST_PROTOCOL.md).

## Anti-leak layout

Each case separates Agent-visible input from evaluation-only gold data:

```text
cases/<case-id>/
  case.json      # metadata, immutable source hash, public source URL
  question.md    # the only problem statement shown to the Agent
  gold.json      # evaluator-only root cause / evidence criteria
```

The benchmark host MUST NOT expose `gold.json`, the original issue discussion, fix PR text, or web search to the Agent during a run. Public source files are downloaded into a temporary work directory. Large third-party logs are not vendored into this repository. Every validated public input is pinned by SHA-256 so an upstream edit fails preparation rather than silently changing the benchmark.

## Deterministic public transport smoke

The public CI smoke is deliberately narrower than the full Agent benchmark. It uses fixed queries to compare model-visible transport for `rg`, plain TraceCite, and TraceCite + Context. It validates real source download, Evidence de-duplication, partial-overlap behavior, bounded state, and the rule that Context optimization must not produce a larger Agent view.

It does **not** measure model reasoning, diagnosis accuracy, model-selected query quality, or total model tokens.

| Case / experiment | shell `rg` visible chars | TraceCite visible chars | TraceCite + Context | Context saving vs TraceCite |
| --- | ---: | ---: | ---: | ---: |
| Kubernetes repeated query | 12,646 | 12,920 | 7,794 | **39.67%** |
| Kubernetes changed/overlapping query | 418 | 2,785 | 2,598 | **6.71%** |
| Flutter repeated query | 2,624 | 5,018 | 3,682 | **26.62%** |
| Flutter partial-overlap query | 1,061 | 3,330 | 3,055 | **8.26%** |

These numbers intentionally show both sides of the trade-off. For a narrow query with one or a few matching lines, raw `rg` output is much smaller than TraceCite because TraceCite also carries structured Coverage/recovery metadata. The current demonstrated Context benefit is primarily **cross-turn duplicate suppression**, not making every individual search cheaper than `rg`.

### `kubernetes-140848`

Based on Kubernetes issue #140848 and fix PR #140853. The issue is closed and links a public Prow build plus the original kubelet log. The Agent-facing question removes the issue's `Reason for failure` section; the evaluator keeps the confirmed root cause in `gold.json`.

Validated source:

- source size: **14,495,302 bytes**;
- source SHA-256: `6217dc9fd7bb8b44f08920909318d2cf87c920049a267c4fd08d1dca4de5d762`.

Repeated-query smoke:

- plain TraceCite returned 30 Evidence rows on both turns;
- TraceCite + Context returned 30 then 0 and reported all 30 as previously seen;
- visible JSON fell from **12,920** to **7,794** characters (**39.6749%**).

Changed-query smoke:

- turn 1 searches the exact kubelet merge/defaulting panic text;
- turn 2 broadens the query to include `PodLevelResourcesFixDefaulting`;
- both searches resolve to the same decisive Evidence line in this source, so Context suppresses the repeated line;
- visible JSON falls from **2,785** to **2,598** characters (**6.7145%**).

The changed-query result is intentionally modest. When only one short Evidence item is repeated, Context metadata consumes much of the saving.

### `flutter-179398`

Based on closed Flutter issue #179398 and the complete iOS crash report published by the reporter. Maintainer comments identify it as the same Impeller RoundSuperellipse arbitrary-memory-corruption bug fixed by commit `e09862d`, which landed after Flutter 3.38.

Validated source:

- source size: **84,429 bytes**;
- source SHA-256: `30648164fcb18db2e2dbcce133be619e9bd8de8f3453860825b16d2bd8ff9f9d`;
- Agent-visible `question.md` does not reveal RoundSuperellipse, DrawCircularArc, the related issue, or the fix commit.

Repeated-query smoke:

- plain TraceCite returned 7 Evidence rows on both turns;
- TraceCite + Context returned 7 then 0;
- visible JSON fell from **5,018** to **3,682** characters (**26.6242%**).

Partial-overlap smoke:

- turn 1 returns 2 Evidence rows for `DrawCircularArc|RoundSuperellipseGeometry`;
- turn 2 broadens to also include `_dispatch_cache_cleanup`, returning 3 canonical Evidence rows;
- Context returns exactly **1 new Evidence** and reports **2 repeated Evidence**;
- visible JSON falls from **3,330** to **3,055** characters (**8.2583%**).

This case is important because it proves the stateful projection is not only an all-or-nothing repeated-query cache: it can remove already-seen Evidence while retaining newly introduced Evidence on a real Mobile/iOS crash report.

## Commands

The benchmark helper is intentionally standard-library-only and experimental; it is not part of TraceCite's stable public API.

```bash
# Validate case separation/schema
python -m tracecite.benchmarking validate \
  benchmarks/agent-investigation/cases/kubernetes-140848

# Download public source logs outside the repository and verify SHA-256
python -m tracecite.benchmarking prepare \
  benchmarks/agent-investigation/cases/kubernetes-140848 \
  --work-dir /tmp/tracecite-bench

# Score a JSONL Agent transcript
python -m tracecite.benchmarking score \
  benchmarks/agent-investigation/cases/kubernetes-140848 \
  /tmp/run.jsonl

# Aggregate multiple already-scored runs (for example 3 modes x several seeds)
python benchmarks/agent-investigation/aggregate_scores.py \
  /tmp/scores/*.json --output /tmp/aggregate.json
```

## Transcript schema

One JSON object per line. Tool adapters should record exactly what the model could see.

```json
{"type":"session","mode":"tracecite_context","model":"example-model"}
{"type":"tool","tool":"search","input":{"query":"panic|configz"},"output":"...model-visible tool output...","input_tokens":120,"output_tokens":530}
{"type":"final","answer":"...final diagnosis...","evidence":["evidence://sha256/...#L120"]}
```

Token fields are optional. When host-reported token usage is absent, the scorer reports a clearly labelled character-based estimate (`ceil(chars / 4)`) rather than pretending it is an exact tokenizer count.

## Metrics

The scorer reports:

- tool calls;
- tool-output characters;
- exact duplicate tool-output characters;
- host-reported input/output tokens when available;
- estimated visible-output tokens as a fallback;
- root-cause concept recall;
- required evidence-marker recall;
- final pass/fail according to the case's thresholds.

The full Agent benchmark must additionally compare wall time, raw bytes scanned, `expand` count, duplicate Evidence suppressed, and model-level total tokens across all three modes.

## Fairness rules

- Same model/version/system prompt for all modes.
- Same `question.md` and downloaded source files.
- No web/GitHub search during diagnosis.
- No issue number in the Agent prompt unless the case explicitly requires it.
- Gold/fix material is evaluator-only.
- Report failures and `unknown` results; do not discard losing runs.
- Run multiple seeds/attempts before making product claims.
- Never present a deterministic transport smoke as a model-level Agent benchmark.
