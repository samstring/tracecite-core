# Agent Benchmark Host Protocol

This document defines the host boundary for the **model-level** TraceCite investigation benchmark. It is stricter than the deterministic public-log smoke workflow.

## Isolation

For every run the host creates a fresh temporary workspace containing only:

- the selected case's `question.md` copied to `QUESTION.md`;
- prepared public input files under `inputs/`;
- a writable scratch directory.

The host MUST NOT mount or expose `gold.json`, `case.json` fields that reveal fix references, issue comments, fix commits/PRs, repository checkout history, browser/search tools, or general network access. The model prompt MUST NOT include the upstream issue number unless the Agent-visible question itself requires it.

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

Do not give this mode TraceCite commands. The shell must not have network access.

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

## Evaluation order

1. Score root-cause concepts and required Evidence markers against evaluator-only `gold.json`.
2. A run that misses the correctness threshold is a failed investigation regardless of token cost.
3. Among correct runs compare provider-reported model input/output usage, separately reported reasoning/cache usage, model-visible tool output, tool calls, repeated output, `expand` calls, wall time, and raw bytes scanned.
4. Report distributions/medians and individual failures; do not publish only the best run.

## Evidence quality

A final answer should distinguish observation from causal Finding and cite evidence that can be recovered from the supplied source. `tracecite` modes should use recoverable Evidence references. `shell_rg` is not penalized for lacking TraceCite URIs, but its final evidence citations must still identify enough source location/text for the evaluator to review the claim.

## Claims policy

A deterministic smoke such as "the same query twice suppressed 30 repeated Evidence rows" may validate Context transport behavior, but it is **not** evidence that TraceCite reduces total Agent tokens or improves diagnosis accuracy. Product-level claims require the model-level matrix above.
