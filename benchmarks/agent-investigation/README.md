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
  case.json      # metadata and public source URLs
  question.md    # the only problem statement shown to the Agent
  gold.json      # evaluator-only root cause / evidence criteria
```

The benchmark host MUST NOT expose `gold.json`, the original issue discussion, fix PR text, or web search to the Agent during a run. Public source files are downloaded into a temporary work directory. Large third-party logs are not vendored into this repository.

## Validated cases

### `kubernetes-140848`

Based on Kubernetes issue #140848 and fix PR #140853. The issue is closed and links a public Prow build plus the original kubelet log. The Agent-facing question removes the issue's `Reason for failure` section; the evaluator keeps the confirmed root cause in `gold.json`.

The public benchmark workflow has successfully downloaded and processed the original kubelet log:

- source size: **14,495,302 bytes**;
- source SHA-256: `6217dc9fd7bb8b44f08920909318d2cf87c920049a267c4fd08d1dca4de5d762`;
- smoke query: `panic|PodLevelResources|KubeletConfiguration|configz`;
- plain TraceCite/Ledger returned 30 Evidence rows on turn 1 and the same 30 again on turn 2;
- TraceCite + Context returned 30 on turn 1 and 0 on turn 2, reporting all 30 as previously seen;
- model-visible JSON over the two turns fell from **12,920** to **8,011** characters, a reduction of **4,909 characters (37.9954%)**;
- the rough `chars / 4` fallback fell from 3,230 to 2,003 visible-output tokens.

This is deliberately labelled a **transport smoke result**, not an Agent benchmark result. The query was fixed rather than model-selected, the second query was intentionally repeated, and no model reasoning tokens were measured. It demonstrates that persistent Seen Evidence / Context Delta works on a real 14.5 MB public log; it does **not** establish that TraceCite beats `shell + rg` on total investigation cost.

### `flutter-179398`

Based on closed Flutter issue #179398 and the complete iOS crash report published by the reporter. Maintainer comments identify it as the same Impeller RoundSuperellipse arbitrary-memory-corruption bug fixed by commit `e09862d`, which landed after Flutter 3.38.

The public input-integrity job successfully downloads the original crash report from the reporter's Gist:

- source size: **84,429 bytes**;
- source SHA-256: `30648164fcb18db2e2dbcce133be619e9bd8de8f3453860825b16d2bd8ff9f9d`;
- Agent-visible `question.md` does not reveal RoundSuperellipse, DrawCircularArc, the related issue, or the fix commit;
- evaluator-only gold checks the rendering subsystem, memory-corruption failure class, decisive stack frames, and the distinction between the crashing libdispatch thread and the earlier corrupting code.

This case gives the benchmark a Mobile/iOS crash workload rather than tuning only for Kubernetes logs.

## Commands

The benchmark helper is intentionally standard-library-only and experimental; it is not part of TraceCite's stable public API.

```bash
# Validate case separation/schema
python -m tracecite.benchmarking validate \
  benchmarks/agent-investigation/cases/kubernetes-140848

# Download public source logs outside the repository
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
