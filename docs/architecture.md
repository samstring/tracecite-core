# TraceCite architecture

[简体中文](architecture.zh-CN.md)

Status: **Normative / Current** for `feature_for_agent`, official extensions, and Agent/CLI/MCP/custom host adapters. Updated for the validated CA258 baseline.

> **The Agent thinks and decides; TraceCite owns evidence.**

This is the top-level living architecture contract. `PROJECT_GUARDRAILS.md` and this document take precedence over old experiment/handoff notes; ADRs and migrations preserve historical decisions/transitions.

## 1. Product boundary

The Agent owns:

- problem/scope interpretation;
- hypotheses and investigation direction;
- causal reasoning and competing explanations;
- evidence sufficiency;
- final answer and qualification;
- the stop decision.

TraceCite owns deterministic evidence mechanics:

- source/version and evidence identity;
- acquisition, snapshot, provenance, Coverage, and integrity;
- RetrievalSession seen/repeated/covered-range memory;
- exact materialization and explicit replay;
- deterministic aggregation and caller-scoped traversal;
- bounded evidence projection/selection with recovery;
- optional InvestigationState coordination metadata;
- extension/trust contracts.

TraceCite Runtime must not expose `root_cause_confidence`, `evidence_sufficient`, `next_best_query`, or `stop_recommended` as runtime truth.

## 2. Architecture invariants

1. Core is generic/deterministic and contains no device/product/company/application/domain knowledge.
2. Core does not import Runtime or concrete domain packages.
3. Runtime may depend on Core; Runtime does not import concrete domain packages.
4. Extensions depend only on public TraceCite contracts and contribute domain facts/capabilities, not Agent reasoning policy.
5. Canonical Evidence/Result stays recoverable when the Agent-facing view is bounded/deduplicated.
6. Lossy/bounded operations expose Coverage, truncation/omission, or equivalent recovery/boundary facts.
7. `status` (execution) and epistemic `outcome` stay separate.
8. Zero matches, incomplete Coverage, missing evidence, source changes, and provider failure do not prove real-world absence.
9. Search matches are observations, not automatically causal proof.
10. RetrievalSession owns mechanical evidence-session memory; never hypotheses/root cause/sufficiency/stopping.
11. Host tool telemetry is not canonical Evidence.
12. Agent conclusions cannot validate themselves or auto-promote to trusted Knowledge.
13. Extension Protocol stays small; domain growth happens through versioned capabilities.
14. Public evidence/schema changes require migration notes/tests; long-lived architectural trade-offs require an ADR.
15. Efficiency changes are accepted only after correctness/support/provenance/recoverability remain acceptable.

## 3. Logical architecture

```text
                                  Domain Extensions
                              Mobile / CI / third-party
                                        |
                                        v
Raw Sources -> Evidence Core -> Evidence Runtime -> Integrations -> Agent Host
               |                |                  |              |
               |                |                  |              +-- Pi
               |                |                  |              +-- Codex
               |                |                  |              +-- Cursor
               |                |                  |              +-- MCP/custom
               |                |                  |
               |                |                  +-- projection / Ledger / Context
               |                |
               |                +-- RetrievalSession
               |                +-- bounded evidence selection
               |                +-- identity/correlation safety
               |                +-- aggregate / traverse
               |                +-- InvestigationState (optional)
               |
               +-- source/version identity
               +-- snapshot / provenance / manifest / verify

Agent owns: hypothesis -> causal reasoning -> sufficiency -> answer -> stop
```

![Architecture overview](../architecture.svg)

## 4. Layer ownership

### `tracecite_core` — Evidence Core

Owns domain-neutral source descriptors, immutable source/version identity, segmentation/filtering/snapshotting, Evidence pointers/ranges, manifests, and deterministic verification. It does not decide importance, causality, or sufficiency.

### `tracecite.runtime` — Evidence Runtime

Owns canonical evidence mechanics, including RetrievalSession, bounded routing/selection, novelty/repetition/Coverage/acquisition-end facts, identity/correlation safety, deterministic aggregation/traversal, and optional InvestigationState coordination.

Canonical local acquisition is implemented in `tracecite.runtime.acquisition`. `tracecite.runtime.tools` is a compatibility facade for legacy callers/integrations and is not an internal Runtime dependency.

Runtime may report mechanical facts such as:

```text
new_evidence = 0
repeated_evidence > 0
frontier_exhausted = true
budget_limit_reached = true
source_changed = true
```

Those facts are not stop/sufficiency advice.

### `tracecite.integrations` — transport / host integration

Owns Agent-facing projection, Evidence Ledger/recovery, Context Engine/delta, capability/profile negotiation, CLI presentation, and host adapters. Pi/Codex/Cursor/MCP/custom hosts must share canonical Evidence/Coverage semantics.

### `tracecite.extension` — domain capability contract

Extensions provide domain source parsing, events, scenario/assertion/report capabilities, and domain Agent capabilities through public contracts. They do not own model-specific token policy, RetrievalSession seen-state, root-cause ranking, or stopping policy.

### `tracecite.knowledge` — reviewed reusable knowledge

Knowledge is downstream of evidence-backed findings and requires independent validation/review/version/expiry. Current-incident Evidence is never replaced by stored Knowledge.

## 5. Canonical Evidence API

Long-term semantics converge on six mechanical primitives:

- `retrieve`: caller-selected source/scope/predicate -> bounded Evidence + Coverage + Provenance + novelty/repetition.
- `materialize`: exact context for a caller-selected immutable source/version range/ref.
- `replay`: deliberate re-read of old immutable evidence; novelty remains zero.
- `aggregate`: deterministic caller-selected count/distinct/group operations; not causal ranking.
- `traverse`: mechanical traversal under caller-selected seed/scope/direction/limits; not investigation planning.
- `verify`: integrity/source-version/Manifest/exact-evidence verification; not validation of an Agent causal claim.

`probe`, `search`, `expand`, and `expand-many` are convenience CLI/adapter surfaces. They must reduce to canonical semantics and must not own a separate session/reasoning model.

## 6. RetrievalSession: single mechanical evidence-memory owner

RetrievalSession owns:

```text
session id / revision
seen evidence/result identities
covered immutable source-version ranges
source generations/observations
recent retrieval operations
request fingerprints
repeated-evidence accounting
replay state
```

Required repeated-evidence behavior:

```text
query A -> body E
query B -> same E again

new_evidence = 0
repeated_evidence > 0
matched_existing_evidence = [E ref]
```

The current query's relevance is preserved without automatically resending E's body. Explicit materialize/replay is the recall path. RetrievalSession never stores the Agent's hypothesis, proof, sufficiency, or stop decision.

## 7. Selection, routing, identity safety

Routing/selection is transport only. It may use source size/version, output/context limits, covered ranges, repeated-output ratio, and bounded lexical/structural diversity. Lossy selection requires explicit omission/truncation and recoverability.

Selection is never equivalent to “most causal,” “most likely root cause,” or “next best entity.”

Correlation constraints are deterministic identity-safety facts. Do not collapse timelines from an unsafe identifier, nearby address values, or filename proximity unless supplied evidence establishes the relation.

## 8. Agent / Host boundary

A Host may own model/tool/context/wall-time budgets, tool exposure, prompts, native-tool telemetry, and optional mechanical checkpoints. A checkpoint may report activity/budget facts and ask the Agent to reconsider continue-vs-answer; it must not claim evidence is sufficient or choose the root cause.

Current repository integrations:

- Pi: bounded prompt + `.pi/skills/tracecite/SKILL.md` + Pi evidence adapter.
- Codex/OpenAI-compatible: root `AGENTS.md` + `.agents/skills/tracecite-investigate/SKILL.md`.
- Cursor: `.cursor/rules/tracecite-investigation.mdc`.

See [Agent integration](agent-integration.md).

## 9. Context Engine / Evidence Ledger

Canonical Results are recoverable first; only then may the Agent-facing view omit bodies already seen by a stable host context. Omission must be explicit and recoverable, and delta is used only when it is actually smaller.

Context state is transport memory, not Evidence truth and not InvestigationState. Different context IDs do not share seen-state; unaddressable evidence is not silently deduplicated.

See [Context Engine](context-engine.md).

## 10. InvestigationState and Knowledge

InvestigationState is optional coordination metadata for problem/scope/hypothesis/test/finding/notes/audit links and explicit user/Agent stop reasons. It is not required for evidence retrieval and is not the source of truth for novelty/Coverage/sufficiency.

Knowledge lifecycle:

```text
Evidence-backed Finding -> Candidate -> independent validation -> review -> versioned Knowledge -> expiry/revalidation
```

See [Knowledge governance](knowledge-governance.md).

## 11. Correctness and benchmark validity

Efficiency is evaluated only after correctness/support/provenance/recoverability gates. Formal Agent benchmarks separate `task_result` from `run_validity`; provider 429/quota/outage/harness failure is infrastructure-invalid, not a model/product loss.

See [Benchmark results](benchmark-results.md).

## 12. Dependency direction

```text
tracecite_core
     ^
     |
tracecite.runtime
     ^
     |
+----+------------------+
|                       |
tracecite.extension   tracecite.integrations
|                       |
Domain Extensions     CLI / Pi / Codex / Cursor / MCP/custom
```

No domain package may become a required dependency of Core or Runtime.

## 13. Implementation status

| Capability | Status | Current baseline |
|---|---|---|
| Evidence Core: source/version, snapshot, provenance, manifest, verify | Implemented | `feature_for_agent` |
| Canonical Evidence semantics: retrieve/materialize/replay/aggregate/traverse/verify | Implemented | Runtime + compatibility wrappers |
| RetrievalSession seen/repeated/range/replay memory | Implemented | CA258 baseline |
| Bounded evidence selection, Coverage, identity/correlation safety | Implemented | CA258 baseline |
| Candidate-first literal search fast path | Implemented | Parity-proven single-line literal subset; Runtime search dispatch uses deterministic legacy fallback and multiline local recovery remains internal |
| Canonical acquisition implementation ownership | Implemented | `tracecite.runtime.acquisition` owns deterministic acquisition; `runtime.tools` is compatibility-only |
| Evidence Ledger + Context Engine / cross-turn delta | Implemented | `tracecite.integrations` |
| Pi bounded investigation integration | Implemented | Validated A/B adapter + `.pi` skill |
| Codex/OpenAI-compatible repository skill integration | Implemented | `AGENTS.md` + `.agents/skills` |
| Cursor project-rule integration | Implemented | `.cursor/rules/tracecite-investigation.mdc` |
| Extension Protocol / domain capability contracts | Implemented | Public extension layer |
| MCP / other host adapters as a single packaged universal integration | Partially implemented | Host-specific adapters evolve separately |

## 14. Documentation / governance rule

Architecture-boundary changes must update both `architecture.md` and `architecture.zh-CN.md` in the same change. Incompatible architecture changes require an ADR; public schema/API changes require migration notes and tests.

Current documentation map: [docs/README.md](README.md).
