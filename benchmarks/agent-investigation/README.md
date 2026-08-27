# TraceCite Agent Investigation Benchmark

This benchmark measures complete debugging investigations on public, real-world incidents rather than synthetic grep tasks.

## Goal

Compare the same Agent, question, and source data under three tool modes:

1. `shell_rg` — shell + `rg`/line-context tools.
2. `tracecite` — TraceCite compact/Ledger transport without cross-turn seen-state.
3. `tracecite_context` — TraceCite + Evidence Ledger + Context Engine (`context_id`), so previously seen Evidence is suppressed on later turns.

The primary metric is **total investigation context cost**, not the size of one command response. Correctness and recoverable Evidence are gates: a cheaper run that reaches the wrong conclusion does not win.

## Anti-leak layout

Each case separates Agent-visible input from evaluation-only gold data:

```text
cases/<case-id>/
  case.json      # metadata and public source URLs
  question.md    # the only problem statement shown to the Agent
  gold.json      # evaluator-only root cause / evidence criteria
```

The benchmark host MUST NOT expose `gold.json`, the original issue discussion, fix PR text, or web search to the Agent during a run. Public source files are downloaded into a temporary work directory. Large third-party logs are not vendored into this repository.

## First validated case

`kubernetes-140848` is based on Kubernetes issue #140848 and fix PR #140853. The issue is closed and links a public Prow build plus the original kubelet log. The Agent-facing question removes the issue's `Reason for failure` section; the evaluator keeps the confirmed root cause in `gold.json`.

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

Future benchmark reports should additionally compare wall time, raw bytes scanned, `expand` count, duplicate Evidence suppressed, and model-level total tokens across all three modes.

## Fairness rules

- Same model/version/system prompt for all modes.
- Same `question.md` and downloaded source files.
- No web/GitHub search during diagnosis.
- No issue number in the Agent prompt unless the case explicitly requires it.
- Gold/fix material is evaluator-only.
- Report failures and `unknown` results; do not discard losing runs.
- Run multiple seeds/attempts before making product claims.
