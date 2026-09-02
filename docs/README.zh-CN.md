# TraceCite 文档地图

[English](README.md) | **简体中文**

状态：`feature_for_agent` 合入 CA258 验证基线后的当前文档索引（2026-09-02）。

TraceCite 文档分为 **Living Contract** 与 **历史归档**。Living Contract 必须描述当前实现并随代码同步；ADR / migrations 则刻意保留当时的决策/迁移语义，不应为了“看起来最新”而重写历史。

## Living 文档

| 文档 | 用途 | 状态 |
|---|---|---|
| [`../README.md`](../README.md) / [`../README.zh-CN.md`](../README.zh-CN.md) | 项目简介、优势、Pi/Codex/Cursor 使用、对比数据、整体架构 | Current |
| [`architecture.md`](architecture.md) / [`architecture.zh-CN.md`](architecture.zh-CN.md) | 规范架构与职责边界 | **Normative / Current** |
| [`agent-integration.md`](agent-integration.md) / [`agent-integration.zh-CN.md`](agent-integration.zh-CN.md) | Agent Host 接入、Pi/Codex/Cursor 方法、Evidence 语义 | Current |
| [`benchmark-results.md`](benchmark-results.md) / [`benchmark-results.zh-CN.md`](benchmark-results.zh-CN.md) | 已验证 Agent paired A/B 数据与 caveat | Current |
| [`context-engine.md`](context-engine.md) / [`context-engine.zh-CN.md`](context-engine.zh-CN.md) | 跨轮 Evidence Delta、Ledger 恢复、Context transport | Current |
| [`extension-contract.md`](extension-contract.md) | Extension Protocol / Domain Capability Contract | Current |
| [`knowledge-governance.md`](knowledge-governance.md) / [`knowledge-governance.zh-CN.md`](knowledge-governance.zh-CN.md) | Knowledge Candidate / review / version 生命周期 | Current |
| [`investigation-summary.md`](investigation-summary.md) / [`investigation-summary.zh-CN.md`](investigation-summary.zh-CN.md) | InvestigationState summary 语义 | Current |
| [`investigation-compare.md`](investigation-compare.md) / [`investigation-compare.zh-CN.md`](investigation-compare.zh-CN.md) | Investigation timeline / compare 语义 | Current |
| [`PROJECT_GUARDRAILS.md`](PROJECT_GUARDRAILS.md) | Evidence/Agent 产品硬边界 | Current |
| [`architecture-governance.md`](architecture-governance.md) | 架构变更治理 | Current |
| [`validation-checklist.md`](validation-checklist.md) | 当前 release/change 验收门禁 | Current |
| [`adr-agent-runtime-semantic-boundary.zh-CN.md`](adr-agent-runtime-semantic-boundary.zh-CN.md) | 已接受的 Agent/Runtime 语义边界 ADR | Accepted ADR |

## 历史归档

以下目录刻意保留历史，不作为当前状态页：

- [`adr/`](adr/)：Architecture Decision Records。
- [`migrations/`](migrations/)：Schema / API / behavior migration notes。

发生冲突时使用：

```text
PROJECT_GUARDRAILS
    -> architecture.md / architecture.zh-CN.md
    -> 当前 integration / contract docs
    -> accepted ADRs
    -> migrations / historical records
```

## 已删除的过期过程文档

CA258 成为 `feature_for_agent` 验证基线后，以下只描述旧实验/交接/重构计划的文档从 Living Tree 删除：

- `evidence-intelligence-experiment.zh-CN.md`
- `evidence-intelligence-work-progress-handoff.zh-CN.md`
- `evidence-runtime-refactor-plan.zh-CN.md`
- `evidence-runtime-architecture.zh-CN.md`

旧 target architecture 中已经落地的 RetrievalSession / canonical API / Host boundary 已合并进规范 `architecture*.md`。旧过程材料仍可通过 Git history 审计。

## 文档维护规则

代码改动如果改变以下任意内容，必须在同一个 change 更新 Living docs：

- dependency direction / layer ownership；
- canonical Evidence API / semantics；
- RetrievalSession / evidence identity / Coverage 行为；
- Agent/Host integration / tool surface；
- Context / Ledger / recovery 语义；
- Extension / Knowledge trust boundary；
- 作为当前事实展示的 benchmark 状态；
- supported platform / version / package status。

临时实验进度、handoff、refactor plan 不再进入 Living Docs；使用 Issue、实验分支、Benchmark Artifact 或 ADR 记录历史。
