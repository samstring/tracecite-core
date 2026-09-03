# Agent integration

[简体中文](agent-integration.zh-CN.md)

Status: current host integration contract for `feature_for_agent` / CA258 baseline.

TraceCite is an **Evidence Runtime**, not an autonomous investigator. A host exposes deterministic TraceCite evidence operations to an external agent; the agent owns hypotheses, investigation order, causal reasoning, sufficiency, the final answer, and stopping.

For general user setup, TraceCite should be installed once at user/global scope. The investigation workflow must not become a generic repository debugging rule. See [Global agent setup](agent-global-setup.md).

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

## 3. Activation and evidence-use rules

TraceCite investigation mode is conditional. It is active only while the current task actually uses TraceCite tools or TraceCite skills. Do not activate TraceCite solely because a task involves debugging, logs, traces, incidents, or root-cause analysis.

While TraceCite mode is active:

1. Use the `tracecite-investigate` skill for TraceCite evidence work.
2. Only supplied artifacts are evidence for incident-specific factual claims unless the user explicitly authorizes an external source.
3. Before another retrieval, identify one unresolved material claim and a discriminator that can change it.
4. Prefer the minimum representative evidence needed to support or contradict that claim.
5. Cite exact materialized line/range evidence for material factual claims.
6. A search match is an observation, not causal proof.
7. A no-match is a retrieval fact, not proof of real-world absence.
8. Truncation, missing evidence, incomplete Coverage, and source changes must remain explicit.
9. Reuse known refs/ranges; use replay when reconsideration is genuinely needed.
10. Once the evidence sufficiently supports the root cause or other conclusion required by the user, answer instead of performing confirmatory searches.
11. The agent decides when evidence is sufficient and when to stop; TraceCite Runtime does not.

The global rule that establishes this activation boundary is defined in [Global agent setup](agent-global-setup.md).

## 4. Shared global skill

The canonical reusable skill source in this repository is:

```text
.agents/skills/tracecite-investigate/SKILL.md
```

For general local use, install it at:

```text
~/.agents/skills/tracecite-investigate/SKILL.md
```

Current Codex, Cursor, and Pi releases all discover user-level skills from `~/.agents/skills/`, so this is the preferred shared location instead of maintaining separate copies per host or per repository.

The skill is designed to be explicit-only where the host supports invocation policy. It must not become a generic “debugging skill” that auto-activates simply because a task looks investigative.

## 5. Codex / OpenAI-compatible agents

For user-level Codex setup:

- install the shared skill at `~/.agents/skills/tracecite-investigate/`;
- append the canonical conditional TraceCite rule to `~/.codex/AGENTS.md`;
- preserve any existing global instructions;
- explicitly invoke the skill as `$tracecite-investigate` when TraceCite is actually being used.

The repository root `AGENTS.md` is only a development contract for this TraceCite repository. It is not the user-level TraceCite investigation policy.

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

For user-level Cursor setup:

- install the shared skill at `~/.agents/skills/tracecite-investigate/`;
- add the canonical conditional rule as a Cursor **User Rule** in `Customize -> Rules` (or the equivalent user-level rule mechanism);
- explicitly invoke the skill as `/tracecite-investigate` when TraceCite is actually being used.

This repository intentionally does not ship a `.cursor/rules/*.mdc` TraceCite investigation rule. `.cursor/README.md` records that boundary so project-level relevance triggering is not reintroduced.

Cursor uses the same CLI/Runtime semantics as Codex. Do not create Cursor-specific notions of Evidence, Coverage, or correctness.

## 7. Pi

For user-level Pi setup:

- install the shared skill at `~/.agents/skills/tracecite-investigate/`;
- append the canonical conditional rule to `~/.pi/agent/AGENTS.md`;
- explicitly invoke the skill as `/skill:tracecite-investigate` when TraceCite is actually being used.

### Validated benchmark setup

The repository's formal Pi A/B harness intentionally keeps its repository-local historical setup for reproducibility:

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

Repository-local benchmark invocation:

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

This benchmark setup is a validation fixture, not the recommended general installation layout. A production Pi host can expose the same canonical evidence semantics through its own adapter.

## 8. CLI transport and Context Engine

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

## 9. Result interpretation

Execution state and epistemic state are separate:

```text
status  = did the operation execute successfully?
outcome = what does the returned evidence support?
```

Agents must inspect Coverage/warnings/missing-evidence and must not infer global absence from a successful zero-match operation.

## 10. Extensions

Domain extensions provide domain facts/capabilities through public TraceCite extension contracts. They must not own model-specific token policy, seen-evidence state, root-cause conclusions, or Agent stopping policy.

See [Extension Contract](extension-contract.md).

## 11. Benchmarking hosts

When evaluating an Agent host:

- use paired conditions and the same base prompt/model;
- record exact model/tool/usage data;
- separate task result from run validity;
- do not count provider 429/quota/outage as a product failure;
- evaluate quality/evidence boundary before efficiency;
- preserve raw scorer output and note scorer limitations.

Current formal results are in [Benchmark results](benchmark-results.md).
