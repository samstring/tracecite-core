# TraceCite 架构设计

[English](architecture.md) | **简体中文**

状态：**规范性 / 当前（Normative / Current）**。适用于 `feature_for_agent`、官方领域扩展以及 Pi / Codex / Cursor / CLI / MCP / 自定义 Host。已更新到 CA258 验证基线。

> **Agent 负责想和决定；TraceCite 负责证据。**

本文是最高级 Living Architecture Contract。旧实验/交接说明不再作为当前架构依据；ADR / migrations 保留历史决策/迁移语义。

## 1. 产品边界

Agent 负责：

- 理解 Problem / Scope；
- 建立 Hypothesis 与调查方向；
- 因果推理和竞争解释；
- 判断 Evidence 是否足够；
- 最终答案和限定；
- Stop decision。

TraceCite 负责确定性的 Evidence 机制：

- source/version 与 evidence identity；
- acquisition、snapshot、provenance、Coverage 与 integrity；
- RetrievalSession 的 seen/repeated/covered-range memory；
- 精确 materialization 与显式 replay；
- deterministic aggregate 与 caller-scoped traverse；
- bounded evidence projection/selection 与恢复；
- 可选 InvestigationState coordination metadata；
- Extension / trust contract。

TraceCite Runtime 不得把 `root_cause_confidence`、`evidence_sufficient`、`next_best_query` 或 `stop_recommended` 当成 Runtime truth。

## 2. 架构不变量

1. Core 只提供通用、确定性的 Evidence 机制，不包含设备/产品/公司/应用/领域知识。
2. Core 不导入 Runtime 或具体 Domain package。
3. Runtime 可依赖 Core；Runtime 不导入具体 Domain package。
4. Extension 只依赖公开 TraceCite contract，贡献领域事实/能力，不贡献 Agent reasoning policy。
5. Agent-facing view 即使被有界/去重，Canonical Evidence / Result 仍必须可恢复。
6. Lossy/bounded operation 必须显式暴露 Coverage、truncation/omission 或等价恢复/边界事实。
7. `status`（执行）与认识层 `outcome` 分离。
8. Zero match、Coverage 不完整、missing evidence、source change、provider failure 都不能证明真实世界不存在。
9. Search match 是 Observation，不自动等于 causal proof。
10. RetrievalSession 只拥有机械 Evidence-session memory；不拥有 Hypothesis/root cause/sufficiency/stopping。
11. Host tool telemetry 不是 canonical Evidence。
12. Agent 结论不能自我验证，也不能自动晋升为可信 Knowledge。
13. Extension Protocol 顶层保持小，领域扩展通过独立版本化 Capability 演进。
14. 公开 Evidence/schema 变化需要 migration + tests；长期架构取舍需要 ADR。
15. Efficiency 只有在 correctness/support/provenance/recoverability 可接受后才算收益。

## 3. 逻辑架构

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

## 4. 分层职责

### `tracecite_core` — Evidence Core

负责 domain-neutral Source descriptor、不可变 source/version identity、segmentation/filtering/snapshotting、Evidence pointer/range、Manifest 和 deterministic verification。它不判断重要性、因果或 Evidence 是否足够。

### `tracecite.runtime` — Evidence Runtime

负责 canonical Evidence mechanics，包括 RetrievalSession、bounded routing/selection、novelty/repetition/Coverage/acquisition-end facts、identity/correlation safety、deterministic aggregate/traverse，以及可选 InvestigationState coordination。

Runtime 可以报告：

```text
new_evidence = 0
repeated_evidence > 0
frontier_exhausted = true
budget_limit_reached = true
source_changed = true
```

这些只是机械事实，不是 stop/sufficiency advice。

### `tracecite.integrations` — Transport / Host Integration

负责 Agent-facing projection、Evidence Ledger/recovery、Context Engine/delta、capability/profile negotiation、CLI 与 Host adapter。Pi/Codex/Cursor/MCP/custom Host 共享同一 canonical Evidence/Coverage 语义。

### `tracecite.extension` — Domain Capability Contract

Extension 通过公开 Contract 提供 Domain Source 解析、Event、Scenario/Assertion/Report capability 和领域 Agent capability。Extension 不拥有 model-specific token policy、RetrievalSession seen-state、root-cause ranking 或 stopping policy。

### `tracecite.knowledge` — 经审核的可复用 Knowledge

Knowledge 位于 Evidence-backed Finding 下游，需要独立验证、审核、版本和失效治理。Stored Knowledge 不能替代当前 Incident 的 Evidence。

## 5. Canonical Evidence API

长期语义收敛为六类机械原语：

- `retrieve`：caller 指定 source/scope/predicate -> bounded Evidence + Coverage + Provenance + novelty/repetition。
- `materialize`：精确展开 caller 指定的不可变 source/version range/ref。
- `replay`：显式重读旧不可变 Evidence；novelty 仍为 0。
- `aggregate`：确定性的 caller-selected count/distinct/group；不做 causal ranking。
- `traverse`：在 caller 指定 seed/scope/direction/limits 下机械遍历；不做 investigation planning。
- `verify`：验证 integrity/source-version/Manifest/exact Evidence；不独立验证 Agent 的因果结论。

`probe`、`search`、`expand`、`expand-many` 是 CLI/Adapter convenience surface，必须归约到 canonical semantics，不拥有第二套 session/reasoning model。

## 6. RetrievalSession：唯一机械 Evidence Memory Owner

RetrievalSession 保存：

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

重复 Evidence 的要求：

```text
query A -> body E
query B -> same E again

new_evidence = 0
repeated_evidence > 0
matched_existing_evidence = [E ref]
```

当前 query 与 E 的 relevance 保留，但不自动重复发送 body。需要重新考虑时使用显式 materialize/replay。RetrievalSession 不保存 Agent 的 Hypothesis、proof、sufficiency 或 stop decision。

## 7. Selection / Routing / Identity Safety

Routing/selection 只属于 Transport，可以依据 source size/version、output/context limit、covered range、repeated ratio 和有界 lexical/structural diversity。Lossy selection 必须显式 omission/truncation 并保持可恢复。

Selection 不能被解释为“最因果”“最可能根因”或“下一个最该查的 entity”。

Correlation constraint 是 deterministic identity-safety fact。如果 supplied Evidence 没建立关系，不得凭 unsafe identifier、附近 address 或 filename proximity 合并 timeline。

## 8. Agent / Host Boundary

Host 可以拥有 model/tool/context/wall-time budget、tool exposure、prompt、native-tool telemetry 和可选机械 checkpoint。Checkpoint 可以报告 activity/budget 并让 Agent 重新决定继续还是回答，但不能声称“Evidence 已足够”或替 Agent 选择 root cause。

当前仓库方法：

- Pi：bounded prompt + `.pi/skills/tracecite/SKILL.md` + Pi Evidence adapter。
- Codex/OpenAI-compatible：根 `AGENTS.md` + `.agents/skills/tracecite-investigate/SKILL.md`。
- Cursor：`.cursor/rules/tracecite-investigation.mdc`。

详见 [Agent 接入](agent-integration.zh-CN.md)。

## 9. Context Engine / Evidence Ledger

Canonical Result 先可恢复，再允许 Agent-facing View 省略稳定 Host context 已见的 Evidence body；省略必须显式、可恢复，并且只有实际更小时才使用 Delta。

Context state 是 Transport Memory，不是 Evidence truth，也不是 InvestigationState。不同 context ID 不共享 seen-state；没有稳定 identity 的 Evidence 不会被静默去重。

详见 [Context Engine](context-engine.zh-CN.md)。

## 10. InvestigationState 与 Knowledge

InvestigationState 是可选 coordination metadata，可以记录 Problem/Scope/Hypothesis/Test/Finding/Notes/Audit link 和显式 user/Agent stop reason。它不是 Evidence retrieval 的前提，也不是 novelty/Coverage/sufficiency source of truth。

Knowledge 生命周期：

```text
Evidence-backed Finding -> Candidate -> independent validation -> review -> versioned Knowledge -> expiry/revalidation
```

详见 [Knowledge governance](knowledge-governance.zh-CN.md)。

## 11. Correctness 与 Benchmark Validity

只有在 correctness/support/provenance/recoverability gate 后才评价效率。正式 Agent benchmark 区分 `task_result` 与 `run_validity`；Provider 429/quota/outage/harness failure 是 infrastructure-invalid，不是 model/product loss。

详见 [Agent 对比数据](benchmark-results.zh-CN.md)。

## 12. Dependency Direction

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

任何 Domain package 都不得成为 Core 或 Runtime 的 required dependency。

## 13. 当前实现与目标差距

| Capability | Status | 当前基线 |
|---|---|---|
| Evidence Core：source/version、snapshot、provenance、manifest、verify | 已实现 | `feature_for_agent` |
| Canonical Evidence 语义：retrieve/materialize/replay/aggregate/traverse/verify | 已实现 | Runtime + compatibility wrappers |
| RetrievalSession seen/repeated/range/replay memory | 已实现 | CA258 baseline |
| Bounded evidence selection、Coverage、identity/correlation safety | 已实现 | CA258 baseline |
| Evidence Ledger + Context Engine / cross-turn delta | 已实现 | `tracecite.integrations` |
| Pi bounded investigation integration | 已实现 | 已验证 A/B adapter + `.pi` skill |
| Codex/OpenAI-compatible repository skill integration | 已实现 | `AGENTS.md` + `.agents/skills` |
| Cursor Project Rule integration | 已实现 | `.cursor/rules/tracecite-investigation.mdc` |
| Extension Protocol / Domain Capability Contract | 已实现 | Public extension layer |
| MCP / 其他 Host 作为单一 packaged universal integration | 部分实现 | Host-specific adapter 独立演进 |

## 14. 文档 / Governance 规则

架构边界变化必须在同一个 change 同时更新 `architecture.md` 和 `architecture.zh-CN.md`。不兼容架构变化需要 ADR；公开 schema/API 变化需要 migration note + tests。

当前文档地图：[docs/README.md](README.md)。
