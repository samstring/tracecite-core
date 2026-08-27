# Agent Benchmark Host Protocol

This document defines the host boundary for the **model-level** TraceCite investigation benchmark. It is stricter than the deterministic public-log smoke workflow.

## Isolation

For every run the host creates a fresh temporary workspace containing only:

- the selected case's `question.md` copied to `QUESTION.md`;
- prepared public input files under `inputs/`;
- a writable scratch directory.

The host MUST NOT mount or expose `gold.json`, `case.json` fields that reveal fix references, issue comments, fix commits/PRs, repository checkout history, browser/search tools, or general network access. The model prompt MUST NOT include the upstream issue number unless the Agent-visible question itself requires it.

`run_host.py` constructs this clean workspace, verifies prepared input SHA-256 values, creates the transcript/session, and starts the external Agent Host with a reduced environment. It is **not** an OS/container security sandbox. A publishable run still needs a host/container policy that prevents the Agent from reading evaluator/repository paths outside the workspace and that separates provider API connectivity from browser/search/general network access.

## Controlled variables

Keep these identical across the three modes:

- model provider, model identifier, model configuration, and system prompt;
- Agent-visible question and source files;
- maximum investigation turns;
- overall wall-clock/tool-call budget;
- filesystem contents other than tool-specific private state;
- stopping/evaluation rules.

Only the tool surface changes.

## Modes

### `shell_rg`

Expose a constrained local shell suitable for evidence exploration. The benchmark baseline should permit at least:

- `rg`;
- `sed`;
- `head` / `tail`;
- `wc`;
- read-only file metadata commands.

Do not give this mode TraceCite commands. The shell must not have general network access.

### `tracecite`

Expose TraceCite Agent tools without cross-turn Context State. At minimum:

- `probe`;
- `sample` / `survey` as appropriate;
- `search`;
- `expand` / `expand-many`;
- Evidence Ledger recovery.

The Agent receives bounded Agent-facing projections, but each search is projected independently.

### `tracecite_context`

Expose the same TraceCite tool set and budgets as `tracecite`, but bind every compatible turn to one fresh per-run `context_id`. Previously seen Evidence is therefore suppressed from later Agent-facing views while canonical Results remain in the private Ledger.

Do not add extra semantic hints to this mode merely because Context State is enabled.

## External Host runner

The repository provides a provider-neutral runner:

```bash
python benchmarks/agent-investigation/run_host.py \
  benchmarks/agent-investigation/cases/kubernetes-140848 \
  /tmp/tracecite-bench/kubernetes-140848/prepared.json \
  --mode tracecite_context \
  --model provider/model \
  --seed 1 \
  --output /tmp/runs/kube-context-1.jsonl \
  --pass-env PROVIDER_API_KEY \
  -- python /path/to/agent_host_adapter.py
```

Everything after the literal `--` is executed directly as argv; it is not passed through a shell. This allows provider-specific commands to use their own flags without colliding with benchmark-runner arguments.

The runner exposes these environment variables to the Host adapter:

- `TRACECITE_BENCH_WORKSPACE` — fresh per-run workspace;
- `TRACECITE_BENCH_QUESTION` — path to `QUESTION.md`;
- `TRACECITE_BENCH_INPUTS` — path to the prepared `inputs/` directory;
- `TRACECITE_BENCH_SCRATCH` — writable per-run scratch directory;
- `TRACECITE_BENCH_TRANSCRIPT` — JSONL file the Host must append to;
- `TRACECITE_BENCH_MODE` — one of the three benchmark modes;
- `TRACECITE_BENCH_MODEL` — requested provider/model identifier;
- `TRACECITE_BENCH_SEED` — attempt seed/index supplied by the matrix;
- `TRACECITE_BENCH_RUN_ID` — unique run identifier;
- `TRACECITE_BENCH_CONTEXT_ID` — fresh value only for `tracecite_context`, otherwise empty.

The runner creates the initial `session` event. The Host adapter MUST append `model`, `tool`, and `final` events; it MUST NOT replace the transcript or add a second `session` event.

### Environment and credential boundary

Arbitrary parent-process environment variables are not inherited by default. Only a small OS/runtime allowlist is retained. Provider credentials or provider-specific settings must be passed explicitly with repeated `--pass-env NAME` arguments.

This reduces accidental evaluator/CI secret leakage, but it is not a replacement for process/container isolation. In particular, retaining runtime variables such as `HOME` can be necessary for installed Agent CLIs; a strict benchmark container should mount only the configuration required by the selected Host.

The runner itself does not attempt to distinguish a legitimate model-provider API request from arbitrary web browsing. The selected Host/container must enforce that policy.

## Transcript requirements

The host writes JSONL in chronological order. Record exactly what the model could see, not a larger internal payload.

```json
{"type":"session","run_id":"...","case_id":"kubernetes-140848","mode":"tracecite_context","model":"provider/model","seed":1}
{"type":"model","content":"...visible assistant content...","usage":{"input_tokens":1200,"output_tokens":80,"reasoning_tokens":20,"cached_input_tokens":400}}
{"type":"tool","tool":"search","input":{"query":"panic"},"output":"...exact model-visible tool result..."}
{"type":"final","answer":"...","evidence":["evidence://sha256/...#L10-L12"]}
```

### Provider usage normalization

Provider-reported usage is authoritative when available. Each completed model call SHOULD record a `model` event with a canonical `usage` object. Normalize only fields the provider actually reports:

- `input_tokens`;
- `output_tokens`;
- `reasoning_tokens`;
- `cached_input_tokens`;
- `cache_read_input_tokens`;
- `cache_creation_input_tokens`.

If a provider uses different names, the host adapter maps them to these fields and may retain the unmodified provider payload separately for audit. Do not infer missing fields and do not manufacture a combined `total_tokens`: reasoning and cache accounting differs across providers and may overlap with input/output accounting.

The scorer treats `model` usage as authoritative and does **not** add legacy token fields attached to tool events when model usage exists. Tool-level `input_tokens` / `output_tokens` remain supported only for old benchmark transcripts.

Character-based token estimates are fallback diagnostics only and must never replace available provider usage.

## Required run matrix

A publishable result requires, per case:

- all three modes;
- the same model/version;
- at least 3 independent attempts per mode (prefer 5+ for non-deterministic hosts);
- all attempts retained, including tool errors, `unknown`, and incorrect diagnoses.

Do not rerun only losing modes until they pass.

A simple matrix driver may invoke `run_host.py` repeatedly; the provider/model adapter remains outside TraceCite Core. Do not add a provider SDK dependency merely to automate the matrix.

## Evaluation order

1. Score root-cause concepts and required Evidence markers against evaluator-only `gold.json`.
2. A run that misses the correctness threshold is a failed investigation regardless of token cost.
3. Among correct runs compare provider-reported model input/output usage, separately reported reasoning/cache usage, model-visible tool output, tool calls, repeated output, `expand` calls, wall time, and raw bytes scanned.
4. Report distributions/medians and individual failures; do not publish only the best run.

## Evidence quality

A final answer should distinguish observation from causal Finding and cite evidence that can be recovered from the supplied source. `tracecite` modes should use recoverable Evidence references. `shell_rg` is not penalized for lacking TraceCite URIs, but its final evidence citations must still identify enough source location/text for the evaluator to review the claim.

## Claims policy

A deterministic smoke such as "the same query twice suppressed 30 repeated Evidence rows" may validate Context transport behavior, but it is **not** evidence that TraceCite reduces total Agent tokens or improves diagnosis accuracy. Product-level claims require the model-level matrix above.
