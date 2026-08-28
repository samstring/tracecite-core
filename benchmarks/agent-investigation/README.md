# TraceCite Agent Investigation Benchmark

This benchmark measures complete debugging investigations on public, real-world incidents rather than synthetic grep tasks.

## Goal

Compare the same Agent, question, model configuration, and source data under different tool surfaces:

1. `shell_rg` — constrained shell + `rg` / line-context baseline.
2. `free_shell` — stronger read-only local-tool baseline where the Agent may choose normal investigation commands such as `rg`, `cat`, `sed`, `head`, `tail`, `jq`, `find`, `sort`, and `uniq`.
3. `tracecite` — bounded TraceCite evidence transport.
4. `tracecite_context` — TraceCite + cross-turn seen-Evidence suppression.
5. `tracecite_intelligence` — correlated/grouped/reduced EvidencePackage while the Agent still chooses retrieval operations.
6. `tracecite_investigate` — high-level deterministic evidence exploration below the model loop.

The primary model-level metric is **total investigation context cost**, not the size of one command response. Correctness, required Evidence recall, and recoverable citations are gates: a cheaper run that reaches the wrong conclusion does not win.

The model-level isolation/tool rules are normative; see [HOST_PROTOCOL.md](HOST_PROTOCOL.md). Mode definitions and fairness details are in [EVIDENCE_INTELLIGENCE_MODES.md](EVIDENCE_INTELLIGENCE_MODES.md).

## Anti-leak layout

Each case separates Agent-visible input from evaluation-only gold data:

```text
cases/<case-id>/
  case.json      # metadata, immutable source hash, public source URL
  question.md    # the only problem statement shown to the Agent
  gold.json      # evaluator-only root cause / evidence criteria
```

The benchmark host MUST NOT expose `gold.json`, original issue discussion, fix PR text, or web search to the Agent during a run. Public source files are downloaded into a temporary work directory and pinned by SHA-256.

## Deterministic public transport smoke

The public CI transport smoke is narrower than the full Agent benchmark. It uses fixed queries to compare what the model would see through `rg`, TraceCite columnar JSON, and TCF frame transports, with and without Context State.

It validates real source download, Evidence de-duplication, partial-overlap behavior, bounded state, transport-aware delta selection, and the invariant that Context optimization must not make the selected TraceCite transport larger.

It does **not** measure model reasoning, diagnosis accuracy, model-selected query quality, or total model tokens.

| Case / experiment | `rg` chars | JSON | JSON + Context | Frame | Frame + Context |
| --- | ---: | ---: | ---: | ---: | ---: |
| Kubernetes repeated query | 12,646 | 12,920 | 7,799 | 10,332 | **5,533** |
| Kubernetes changed/overlapping query | **418** | 2,785 | 2,603 | 1,162 | 943 |
| Flutter repeated query | 2,624 | 5,018 | 3,687 | 3,370 | **2,044** |
| Flutter partial-overlap query | **1,061** | 3,330 | 3,060 | 1,781 | 1,299 |

The result intentionally shows both sides of the trade-off. For a narrow already-known anchor, raw `rg` can be smaller because it carries no Coverage, Ledger identity, or recovery metadata. TraceCite should not claim that every individual search is cheaper than `rg`.

## Public incident cases

### `kubernetes-140848`

Based on Kubernetes issue #140848 and fix PR #140853. The Agent-facing question removes the issue's diagnosis text while evaluator-only gold retains the confirmed root cause.

Validated source:

- source size: **14,495,302 bytes**;
- source SHA-256: `6217dc9fd7bb8b44f08920909318d2cf87c920049a267c4fd08d1dca4de5d762`.

### `flutter-179398`

Based on closed Flutter issue #179398 and the complete iOS crash report published by the reporter. Maintainer discussion links it to the Impeller RoundSuperellipse memory-corruption bug fixed by commit `e09862d`; the Agent-visible question does not expose that diagnosis or fix.

Validated source:

- source size: **84,429 bytes**;
- source SHA-256: `30648164fcb18db2e2dbcce133be619e9bd8de8f3453860825b16d2bd8ff9f9d`.

The real-world suite also contains additional Prometheus, Pulumi, and Double Commander cases. The next quality goal is broader independent root-cause coverage rather than simply adding larger log files.

## Real Evidence scale validation

See [SCALE_BENCHMARK.md](SCALE_BENCHMARK.md) for the full protocol.

The active model-level scale ladder is intentionally capped at **50 MiB** for the current Evidence Intelligence experiment:

```text
25 KiB
→ 5 MiB
→ 50 MiB
```

100 MiB / 500 MiB / larger runs are no longer required merge gates. Existing larger workflows may remain as optional stress tooling only.

### 2026-08-28 candidate-first result

Using `MiniMaxAI/MiniMax-M3` through the configured GMI OpenAI-compatible endpoint on a TraceBench HDFS_v3 corruption case derived from real fault records plus real normal background records:

- 25 KiB TraceCite candidate: **PASS**;
- 5 MiB TraceCite candidate: **PASS**;
- 50 MiB TraceCite candidate: **PASS** with all required concepts and Evidence markers;
- paired 50 MiB `free_shell`: `context_window_exceeded` after a very large model-visible tool output.

The 50 MiB TraceCite run recorded approximately:

- `tool_output_chars`: 88,545;
- provider-reported cumulative `input_tokens`: 375,211;
- `cached_input_tokens`: 335,852;
- `output_tokens`: 4,908;
- model calls: 17;
- tool calls: 34.

This supports a bounded-evidence-flow claim, not a universal fixed token-saving percentage.

## Candidate-first and failure semantics

Scale comparisons run the TraceCite candidate before `free_shell`. A pathological baseline must not consume provider quota/rate-limit headroom before the candidate is evaluated.

Classification rules:

- TraceCite quality/context/timeout failure -> candidate failure;
- TraceCite provider quota/rate/unavailable -> infrastructure-inconclusive;
- baseline context/tool/provider failure -> retained as comparison evidence and does not invalidate an already-passing TraceCite candidate.

Context-window overflow is a real baseline capability result, but provider usage from successful earlier requests must not be misread as the total attempted context cost: the oversized failing request may never receive a provider usage record.

## Commands

The benchmark helpers are experimental. Core does not depend on a provider SDK; a provider/Codex/Claude/custom Host is supplied as an external command.

```bash
python -m tracecite.benchmarking validate \
  benchmarks/agent-investigation/cases/kubernetes-140848

python -m tracecite.benchmarking prepare \
  benchmarks/agent-investigation/cases/kubernetes-140848 \
  --work-dir /tmp/tracecite-bench

python benchmarks/agent-investigation/run_host.py \
  benchmarks/agent-investigation/cases/kubernetes-140848 \
  /tmp/tracecite-bench/kubernetes-140848/prepared.json \
  --mode tracecite_context \
  --model provider/model \
  --seed 1 \
  --output /tmp/runs/kube-context-1.jsonl \
  --pass-env PROVIDER_API_KEY \
  -- python /path/to/agent_host_adapter.py

python -m tracecite.benchmarking score \
  benchmarks/agent-investigation/cases/kubernetes-140848 \
  /tmp/runs/kube-context-1.jsonl
```

`run_host.py` reduces accidental environment leakage and validates/copies the workspace, but it is not an OS/container sandbox. The selected Host/container must enforce filesystem isolation and the rule that model-provider connectivity does not turn into browser/search/general network access.

## Transcript schema and token accounting

One JSON object per line. Tool adapters record exactly what the model could see; model events carry provider-reported usage when available.

```json
{"type":"session","mode":"tracecite_context","model":"provider/model"}
{"type":"model","content":"I will inspect the failure.","usage":{"input_tokens":1200,"output_tokens":80,"reasoning_tokens":20,"cached_input_tokens":400}}
{"type":"tool","tool":"search","input":{"query":"panic|configz"},"output":"...exact model-visible tool output..."}
{"type":"final","answer":"...final diagnosis...","evidence":["evidence://sha256/...#L120"]}
```

Provider-reported model usage is authoritative for successful model requests. The scorer keeps input, output, reasoning, cached-input, cache-read, and cache-creation usage as separate dimensions and does not invent a combined total.

Cumulative input tokens across a multi-turn investigation include repeated conversation history. They are **not** the number of unique Evidence tokens extracted from the source file.

When provider usage is unavailable, `ceil(chars / 4)` may be reported only as a clearly labelled rough estimate of visible text size. It is not an exact tokenizer count.

## Metrics

The scorer/host should report or evolve toward reporting:

- model calls and tool calls;
- provider-reported input/output/cache token dimensions;
- tool-output characters and exact duplicate tool-output characters;
- unique Evidence growth and repeated-Evidence ratio;
- source coverage and scanned bytes;
- wall time and peak RSS where available;
- root-cause concept recall;
- required Evidence-marker recall;
- citation accuracy and unsupported claims;
- timeout/context/provider-error status;
- attempted context load where an oversized next request fails before provider usage is emitted.

## Fairness rules

- Same model/version/system prompt for paired modes.
- Same `question.md` and prepared source bytes.
- No web/GitHub search during diagnosis.
- No evaluator-only root-cause/fix hints in Agent-visible input.
- Report failures and `unknown` results; do not discard losing runs.
- Do not use benchmark-only caps to make TraceCite look artificially better.
- Product-level bounded projections/recovery behavior is allowed when it is part of the actual product behavior and reported as such.
- Never present deterministic transport smoke as model-level Agent reasoning evidence.
- A publishable broad product claim needs multiple independent real incidents/domains, not only one scale-derived HDFS case.
