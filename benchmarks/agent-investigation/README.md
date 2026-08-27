# TraceCite Agent Investigation Benchmark

This benchmark measures complete debugging investigations on public, real-world incidents rather than synthetic grep tasks.

## Goal

Compare the same Agent, question, and source data under three model-level tool modes:

1. `shell_rg` — shell + `rg`/line-context tools.
2. `tracecite` — TraceCite bounded/Ledger transport without cross-turn seen-state.
3. `tracecite_context` — TraceCite + Evidence Ledger + Context Engine (`context_id`), so previously seen Evidence is suppressed on later turns.

Within the TraceCite modes, the deterministic transport smoke also compares columnar JSON (`stateful-index`) with the text frame (`frame` / TCF) to separate evidence cost from encoding overhead.

The primary model-level metric is **total investigation context cost**, not the size of one command response. Correctness and recoverable Evidence are gates: a cheaper run that reaches the wrong conclusion does not win.

The model-level isolation/tool rules are normative; see [HOST_PROTOCOL.md](HOST_PROTOCOL.md).

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

The public CI smoke is deliberately narrower than the full Agent benchmark. It uses fixed queries and the same Evidence/line/output budgets to compare what the model would see through `rg`, TraceCite columnar JSON, and TCF frame transports, with and without Context State.

It validates real source download, Evidence de-duplication, partial-overlap behavior, bounded state, transport-aware delta selection, and the invariant that Context optimization must not make the selected transport larger.

It does **not** measure model reasoning, diagnosis accuracy, model-selected query quality, or total model tokens.

| Case / experiment | `rg` chars | JSON | JSON + Context | Frame | Frame + Context |
| --- | ---: | ---: | ---: | ---: | ---: |
| Kubernetes repeated query | 12,646 | 12,920 | 7,799 | 10,332 | **5,533** |
| Kubernetes changed/overlapping query | **418** | 2,785 | 2,603 | 1,162 | 943 |
| Flutter repeated query | 2,624 | 5,018 | 3,687 | 3,370 | **2,044** |
| Flutter partial-overlap query | **1,061** | 3,330 | 3,060 | 1,781 | 1,299 |

Context savings within each TraceCite transport:

| Case / experiment | JSON Context saving | Frame Context saving |
| --- | ---: | ---: |
| Kubernetes repeated query | 39.64% | **46.45%** |
| Kubernetes changed/overlapping query | 6.54% | **18.85%** |
| Flutter repeated query | 26.52% | **39.35%** |
| Flutter partial-overlap query | 8.11% | **27.06%** |

The result intentionally shows both sides of the trade-off. For a narrow query with one or a few matching lines, raw `rg` is still much smaller because it carries no Coverage, Ledger identity, or recovery metadata. TraceCite should therefore not claim that every individual search is cheaper than `rg`.

The new finding is that a material part of TraceCite's small-query overhead was transport encoding rather than Evidence itself. On these public cases, TCF frame reduces plain TraceCite output relative to columnar JSON by roughly 20–58%, and frame + Context reduces the stateful output relative to JSON + Context by roughly 29–64%. Hosts that explicitly declare `text_frame` capability can therefore use `auto` to select `frame`; hosts that do not declare it continue to receive JSON.

### `kubernetes-140848`

Based on Kubernetes issue #140848 and fix PR #140853. The issue is closed and links a public Prow build plus the original kubelet log. The Agent-facing question removes the issue's `Reason for failure` section; the evaluator keeps the confirmed root cause in `gold.json`.

Validated source:

- source size: **14,495,302 bytes**;
- source SHA-256: `6217dc9fd7bb8b44f08920909318d2cf87c920049a267c4fd08d1dca4de5d762`.

Repeated-query smoke:

- canonical Agent view returns 30 Evidence rows on both turns;
- Context returns 30 then 0 and records all 30 as previously seen;
- JSON falls from **12,920** to **7,799** characters (**39.64%**);
- frame falls from **10,332** to **5,533** characters (**46.45%**).

Changed-query smoke:

- turn 1 searches the exact kubelet merge/defaulting panic text;
- turn 2 broadens the query to include `PodLevelResourcesFixDefaulting`;
- both searches resolve to the same decisive Evidence line in this source, so the second turn suppresses one repeated Evidence;
- JSON falls from **2,785** to **2,603** characters (**6.54%**);
- frame falls from **1,162** to **943** characters (**18.85%**).

This is intentionally a modest Context win: when only one short Evidence item repeats, state metadata consumes much of the saving. It also demonstrates the `rg` advantage for an already-known exact anchor: only **418** visible characters across two turns.

### `flutter-179398`

Based on closed Flutter issue #179398 and the complete iOS crash report published by the reporter. Maintainer comments identify it as the same Impeller RoundSuperellipse arbitrary-memory-corruption bug fixed by commit `e09862d`, which landed after Flutter 3.38.

Validated source:

- source size: **84,429 bytes**;
- source SHA-256: `30648164fcb18db2e2dbcce133be619e9bd8de8f3453860825b16d2bd8ff9f9d`;
- Agent-visible `question.md` does not reveal RoundSuperellipse, DrawCircularArc, the related issue, or the fix commit.

Repeated-query smoke:

- canonical Agent view returns 7 Evidence rows on both turns;
- Context returns 7 then 0;
- JSON falls from **5,018** to **3,687** characters (**26.52%**);
- frame falls from **3,370** to **2,044** characters (**39.35%**).

Partial-overlap smoke:

- turn 1 returns 2 Evidence rows for `DrawCircularArc|RoundSuperellipseGeometry`;
- turn 2 broadens to also include `_dispatch_cache_cleanup`, returning 3 canonical Evidence rows;
- Context returns exactly **1 new Evidence** and suppresses **2 repeated Evidence**;
- JSON falls from **3,330** to **3,060** characters (**8.11%**);
- frame falls from **1,781** to **1,299** characters (**27.06%**).

This case proves the stateful projection is not an all-or-nothing repeated-query cache: it removes already-seen Evidence while retaining newly introduced Evidence on a real Mobile/iOS crash report.

## Commands

The benchmark helper is intentionally standard-library-only and experimental; it is not part of TraceCite's stable public API.

```bash
python -m tracecite.benchmarking validate \
  benchmarks/agent-investigation/cases/kubernetes-140848

python -m tracecite.benchmarking prepare \
  benchmarks/agent-investigation/cases/kubernetes-140848 \
  --work-dir /tmp/tracecite-bench

python -m tracecite.benchmarking score \
  benchmarks/agent-investigation/cases/kubernetes-140848 \
  /tmp/run.jsonl

python benchmarks/agent-investigation/aggregate_scores.py \
  /tmp/scores/*.json --output /tmp/aggregate.json
```

## Transcript schema

One JSON object per line. Tool adapters record exactly what the model could see; model events carry provider-reported usage when available.

```json
{"type":"session","mode":"tracecite_context","model":"provider/model"}
{"type":"model","content":"I will inspect the failure.","usage":{"input_tokens":1200,"output_tokens":80,"reasoning_tokens":20,"cached_input_tokens":400}}
{"type":"tool","tool":"search","input":{"query":"panic|configz"},"output":"...exact model-visible tool output..."}
{"type":"final","answer":"...final diagnosis...","evidence":["evidence://sha256/...#L120"]}
```

Provider-reported model usage is authoritative. The scorer keeps input, output, reasoning, cached-input, cache-read, and cache-creation usage as separate dimensions and does not invent a combined total. Old transcripts with token fields attached to tool events remain supported as a legacy fallback. When no provider usage exists, `ceil(chars / 4)` is reported only as a clearly labelled rough estimate.

## Metrics

The scorer reports:

- tool calls and model calls;
- tool-output characters and exact duplicate tool-output characters;
- provider-reported input/output tokens when available;
- separately reported reasoning/cache token dimensions when available;
- usage source (`model_events` or legacy fallback);
- estimated visible-output tokens as a fallback;
- root-cause concept recall;
- required evidence-marker recall;
- final pass/fail according to the case's thresholds.

The full Agent benchmark should additionally compare wall time, raw bytes scanned, `expand` count, duplicate Evidence suppressed, and other host-level operational metrics across all three modes.

## Fairness rules

- Same model/version/system prompt for all modes.
- Same `question.md` and downloaded source files.
- No web/GitHub search during diagnosis.
- No issue number in the Agent prompt unless the case explicitly requires it.
- Gold/fix material is evaluator-only.
- Report failures and `unknown` results; do not discard losing runs.
- Run multiple seeds/attempts before making product claims.
- Never present a deterministic transport smoke as a model-level Agent benchmark.
