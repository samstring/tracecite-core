# Agent integration

[简体中文](agent-integration.zh-CN.md)

Status: current host integration contract for `feature_for_agent` / CA258 baseline.

TraceCite is an **Evidence Runtime**, not an autonomous investigator. A host exposes deterministic TraceCite evidence operations to an external agent; the agent owns hypotheses, investigation order, causal reasoning, sufficiency, the final answer, and stopping.

## 1. Host contract

```text
raw evidence
    -> TraceCite Core/Runtime
    -> bounded Evidence + Coverage + Provenance
    -> host adapter
    -> Agent
```

A host may own tool telemetry, model/context budgets, native tool access, and policy prompts. Host telemetry is not canonical Evidence.

TraceCite owns:

- source/version and evidence identity;
- provenance and exact materialization;
- Coverage, truncation, omission, missing-evidence and source-change facts;
- RetrievalSession seen/repeated/covered-range memory;
- explicit replay;
- deterministic aggregate/traverse operations;
- bounded evidence projection and recovery paths;
- integrity verification.

TraceCite does **not** own:

- hypotheses or causal conclusions;
- root-cause likelihood/ranking;
- evidence sufficiency;
- the next investigation direction;
- a recommendation that the agent should stop.

## 2. Canonical Evidence semantics

The long-term Evidence API is expressed as six mechanical primitives:

| Primitive | Meaning |
|---|---|
| `retrieve` | Caller-selected target/scope/predicate -> Evidence + Coverage + Provenance + novelty |
| `materialize` | Exact context for an immutable source/version range |
| `replay` | Deliberately re-read already-seen evidence without making it “new” |
| `aggregate` | Deterministic count/distinct/group-style operations |
| `traverse` | Mechanical traversal under caller-selected seed/scope/limits |
| `verify` | Integrity/source-version/Manifest/evidence verification |

CLI/host adapters may expose convenience names such as `probe`, `search`, `expand`, and `expand-many`; those wrappers do not own a second evidence or stopping model.

## 3. Evidence-use rules for every agent

1. Only supplied artifacts are evidence for incident-specific factual claims unless the user explicitly authorizes an external source.
2. Before another retrieval, identify one unresolved material claim and a discriminator that can change it.
3. Prefer the minimum representative evidence needed to support or contradict that claim.
4. Cite exact materialized line/range evidence for material factual claims.
5. A search match is an observation, not causal proof.
6. A no-match is a retrieval fact, not proof of real-world absence.
7. Truncation, missing evidence, incomplete Coverage, and source changes must remain explicit.
8. Reuse known refs/ranges; use replay when reconsideration is genuinely needed.
9. Do not perform an evidence census after the required causal proof is already supported.
10. The agent decides when evidence is sufficient and when to stop.

## 4. Pi

### Validated setup

The repository's formal Pi A/B harness uses:

- `.pi/skills/tracecite/SKILL.md`;
- `benchmarks/agent-investigation/pi_tracecite_extension.ts`;
- only `tracecite_search` and `tracecite_expand` for evidence access in the TraceCite arm;
- a bounded system prompt.

Validated base prompt:

```text
You are a coding agent investigating supplied runtime evidence. Keep the investigation bounded. Once the root cause is sufficiently supported, answer immediately instead of performing confirmatory searches. Cite exact evidence lines for material factual claims.
```

TraceCite addition:

```text
Follow the user's explicit request to use TraceCite. All runtime-evidence content must be obtained through TraceCite tools; do not use native file-access tools for the evidence.
```

Repository-local invocation pattern:

```bash
BASE_PROMPT='You are a coding agent investigating supplied runtime evidence. Keep the investigation bounded. Once the root cause is sufficiently supported, answer immediately instead of performing confirmatory searches. Cite exact evidence lines for material factual claims.'
TRACE_PROMPT="$BASE_PROMPT Follow the user's explicit request to use TraceCite. All runtime-evidence content must be obtained through TraceCite tools; do not use native file-access tools for the evidence."

pi \
  --extension ./benchmarks/agent-investigation/pi_tracecite_extension.ts \
  --tools tracecite_search,tracecite_expand \
  --no-skills --skill ./.pi/skills/tracecite/SKILL.md \
  --no-prompt-templates --no-context-files \
  --system-prompt "$TRACE_PROMPT" \
  "Use TraceCite to investigate this problem: ${QUESTION}"
```

The benchmark extension is an adapter, not a new evidence layer. A production Pi host can expose the same semantics through a separately packaged adapter.

## 5. Codex / OpenAI-compatible agents

Repository-wide durable constraints live in root `AGENTS.md`. The reusable evidence workflow lives in:

```text
.agents/skills/tracecite-investigate/SKILL.md
```

The skill documents canonical Evidence API/trust semantics and is intentionally separate from `AGENTS.md` so detailed workflow context is loaded only when relevant.

Recommended request:

```text
Use $tracecite-investigate to investigate <problem> from the supplied evidence.
Keep retrieval bounded. Cite exact materialized evidence for material factual claims.
Do not fill evidence gaps with external knowledge; qualify unsupported parts explicitly.
```

Codex can use the TraceCite CLI through shell tools:

```bash
tracecite probe ./logs --glob "*.log" --recursive
tracecite search app.log "<discriminator>" --snapshot \
  --agent-profile stateful-index \
  --ledger-dir .tracecite/ledger \
  --context-id incident-42
tracecite expand-many .tracecite/ledger RESULT_ID '#L120' '#L188-L190'
```

For small, already-bounded evidence, direct reads remain legitimate; TraceCite is most useful when evidence volume, provenance, repetition, or cross-source correlation makes raw reads expensive or unsafe.

## 6. Cursor

This repository ships a project rule:

```text
.cursor/rules/tracecite-investigation.mdc
```

The rule is relevance-triggered (`alwaysApply: false`) and is intended for logs, traces, support bundles, crash reports, and root-cause investigations. Cursor can apply it intelligently or the user can reference the rule explicitly.

Recommended request:

```text
Use the TraceCite investigation rule for this incident.
Investigate only from the supplied evidence, keep retrieval bounded,
and cite exact evidence ranges for the causal claims in the final answer.
```

Cursor uses the same CLI/Runtime semantics as Codex. Do not create Cursor-specific notions of Evidence, Coverage, or correctness.

## 7. CLI transport and Context Engine

For one-shot use:

```bash
tracecite search app.log "timeout" --snapshot
```

For stateful host sessions, pair the Ledger with a stable host-owned context ID:

```bash
tracecite search app.log "timeout" --snapshot \
  --agent-profile stateful-index \
  --ledger-dir .tracecite/ledger \
  --context-id incident-42
```

The canonical Result is recoverable through the Ledger before context delta is applied. Already-seen evidence may be omitted from the next model-facing view only when it remains recoverable and omission is explicitly represented.

Use `expand-many` to recover exact ranges from a Ledger result:

```bash
tracecite expand-many .tracecite/ledger RESULT_ID '#L120' '#L188-L190'
```

See [Context Engine](context-engine.md).

## 8. Result interpretation

Execution state and epistemic state are separate:

```text
status  = did the operation execute successfully?
outcome = what does the returned evidence support?
```

Agents must inspect Coverage/warnings/missing-evidence and must not infer global absence from a successful zero-match operation.

## 9. Extensions

Domain extensions provide domain facts/capabilities through public TraceCite extension contracts. They must not own model-specific token policy, seen-evidence state, root-cause conclusions, or Agent stopping policy.

See [Extension Contract](extension-contract.md).

## 10. Benchmarking hosts

When evaluating an Agent host:

- use paired conditions and the same base prompt/model;
- record exact model/tool/usage data;
- separate task result from run validity;
- do not count provider 429/quota/outage as a product failure;
- evaluate quality/evidence boundary before efficiency;
- preserve raw scorer output and note scorer limitations.

Current formal results are in [Benchmark results](benchmark-results.md).
