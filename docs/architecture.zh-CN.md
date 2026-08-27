# TraceCite 架构设计

状态：规范性文档（Normative）  
适用范围：TraceCite 主发行包、官方领域扩展以及 Agent/CLI/MCP 等宿主适配器

本文是 TraceCite 的顶层架构依据。Agent 接入、扩展契约、知识治理和验收文档都必须遵守本文边界。规划能力必须明确标注，不能当成当前实现。

## 1. 产品定义

TraceCite 是一个**证据驱动的 Agent 调查框架**：

- Agent 负责理解问题、自由探索、建立假设、选择测试和解释结果。
- TraceCite 负责保存调查状态、确定性处理数据、控制预算、生成可追溯 Evidence，并管理 Knowledge 生命周期。
- Domain Extension 负责 Mobile、CI、Backend、Database 等领域的数据接入与语义。
- Agent/CLI/MCP Adapter 负责把 Runtime 能力投影到具体宿主，不反向定义领域模型。

核心原则：

> 流程约束结论，不约束探索动作。

TraceCite 不是内置 LLM 的自治诊断 Agent，也不是强迫所有问题经过固定命令漏斗的日志搜索器。

## 2. 架构不变量

以下约束除非通过 ADR、版本迁移和验证，不得破坏：

1. Core 只包含通用、确定性、可复现的 Evidence 能力，不包含设备、产品、公司、应用或业务知识。
2. Agent 可自由选择安全的探索方法；最终 Finding 必须关联 Hypothesis、Evidence、Coverage、限制和停止原因。
3. `status` 表示执行状态，`outcome` 表示认识结果；二者不得合并。
4. 零命中、Coverage 不完整、Evidence 缺失和执行失败不能自动证明事件不存在，默认保持 `unknown`。
5. 可引用 Evidence 必须指向不可变快照和范围，或指向完整性已验证的 Manifest。
6. Agent 生成的结论不能自动晋升为可信 Knowledge，也不能作为自己的独立验证。
7. Extension 提供领域事实和能力；Runtime 保留执行、预算、Evidence、验证、安全、停止和 Agent Context 控制权。
8. Core 不导入 Runtime 或领域包；Runtime 不导入具体领域包。领域扩展只依赖公开 TraceCite Contract。
9. 任何有界、抽样、近似或截断操作都必须显式暴露 Coverage。
10. Canonical Result / Evidence 与 Agent-facing View 分离。传输压缩、Token 策略、Seen State、Context Delta 不能成为 Domain Extension 的职责。
11. Extension Protocol 必须优先保持顶层稳定；新增领域能力优先通过独立、版本化 Capability 扩展，而不是继续增加顶层 `register_xxx` API。
12. 新主包能力应证明至少服务两个领域；否则留在领域扩展。

## 3. 逻辑架构

```text
用户问题
   |
   v
Agent Host
理解、推理、选择下一步、与用户交互
   |
   v
Agent / Integration Projection
CLI、MCP、Codex/Claude/ChatGPT 等宿主适配
   |
   v
Investigation Runtime  <---->  Knowledge Registry
状态、预算、安全、停止、流程关联       候选、审核、版本、失效
   |
   v
Evidence Core
Source、Segmenter、Sample、Survey、Filter、Snapshot、Evidence、Manifest、Verify
   |
   v
Evidence Store
冻结输入、过滤产物、事件、报告、Manifest

Stable Extension Protocol v2
   ^
   |
Domain Extensions
Mobile / CI / Backend / Third-party
```

Extension 与 Runtime 之间交换的是稳定 Contract 和 Capability，不是 Runtime 内部对象。当前实现可在内部把 `ScenarioCapability` 适配成 `ScenarioRuntime`，但 `ScenarioRuntime` 不再是 Extension Protocol v2 的长期公共边界。

### 3.1 Agent Host

负责：

- 把自然语言请求转成 Problem 与 Scope。
- 选择直接读取、sample、survey、search、Scenario 或领域 Capability。
- 建立可证伪 Hypothesis 和 Test，同时寻找支持与反证。
- Evidence 不足时保持 `unknown`，必要时请求新输入或授权。

Agent 的推理文本不能被当作独立 Evidence。

### 3.2 Investigation Runtime

Runtime 是唯一的通用调查运行时，负责：

- 保存版本化 `InvestigationState`。
- 把 Execution 关联到 Problem、Hypothesis、Test 和 Finding。
- 控制预算、安全、授权和停止条件。
- 调用已经安装的 Domain Capability。
- 保持 Canonical Result 完整，并为 Integration 提供有界投影所需状态。

领域不再通过“一个领域一个 Runtime”定义系统行为。`ScenarioCapability` 只是领域向通用 Runtime 提供 profile、preset/子场景解析等能力的契约；当前 `ScenarioRuntime` 仅作为内部兼容适配实现。

### 3.3 Evidence Core

`tracecite_core` 是 Python 标准库实现的稳定 Evidence 内核，负责：

- 解析、冻结和校验输入。
- 流式 Segment、Sample、Survey、Filter。
- 生成哈希寻址的 EvidencePointer。
- 管理运行目录、Artifact 和 Manifest。
- Verify 引用和运行完整性。

Core 不理解“白屏”“卡顿”“构建失败”等领域概念，也不判断根因。

### 3.4 Knowledge Registry

负责 Knowledge Candidate 的提案、独立案例验证、审核、晋升、版本与失效。正式流程见[知识治理](knowledge-governance.zh-CN.md)。可信 Knowledge 只能推荐未来的 Hypothesis、Test、Preset 或 Scenario，不能替代本次 Evidence。

### 3.5 Domain Extensions

领域扩展保存领域数据和语义。Mobile 只是一个官方扩展，不是 Core 特例。Extension Protocol v2 使用声明式对象：

- `ExtensionManifest`：扩展身份、领域、版本、协议版本。
- `TraceCiteExtension`：Manifest + Capability 列表。
- Capability 独立版本：`core.plugins`、`agent.capability`、`runtime.assertion`、`runtime.report`、`runtime.scenario` 等。
- 稳定领域值对象：`EvidenceRef`、`Coverage`、`DomainEvent`、`SourceDescriptor`、`SourceCursor`、`SourceChunk`、`CapabilityResult`。

DomainEvent 描述事实，不携带针对某个问题的 relevance、token priority 或 root-cause 判断。正式契约见[扩展契约](extension-contract.md)。

## 4. 调查领域模型

| 概念 | 含义 | 必须关联 |
|---|---|---|
| Problem | 用户真正要回答的问题，不等同于搜索词 | Scope |
| Scope | 数据源、主体、时间、权限与预算边界 | Problem |
| Observation | 未作因果解释的可观察事实 | 来源或 Evidence |
| DomainEvent | Extension 提供的结构化领域事实 | EvidenceRef / Source |
| Hypothesis | 可以被 Evidence 支持或反驳的陈述 | Problem |
| Test | 验证一个 Hypothesis 的具体计划 | Hypothesis |
| Strategy | Test 采用的执行方法 | Test |
| Evidence | 可复查、可寻址的证据 | Test、来源、哈希 |
| Coverage | 覆盖、遗漏、抽样、近似和截断信息 | Test / Evidence / Capability |
| Finding | 对 Hypothesis 的 `supported`、`contradicted` 或 `unknown` 判断 | Evidence、Coverage |
| Knowledge Candidate | 从 Finding 提取的可复用提案 | Investigation、Evidence |
| Knowledge | 通过独立验证和审核的版本化知识 | Candidate、审核记录 |

`DomainEvent` / Observation 与 Finding 必须分离。例如“10:30:04 `/home` 返回 HTTP 504”是事实；“HTTP 504 导致白屏”仍是需要验证的 Hypothesis/Finding。

## 5. 通用调查协议

```text
Problem + Scope
      |
      v
Orient -----> Explore
                 |
                 v
             Hypothesis
                 |
                 v
               Test
                 |
                 v
       Evidence + Coverage
                 |
                 v
              Finding
                 |
                 v
             Stop reason
                 |
                 +----> 可选 Knowledge Candidate -> Review -> Knowledge
```

### 5.1 必要步骤

一次可交付调查必须：

1. 定义 Problem 与 Scope。
2. 建立至少一个可证伪 Hypothesis。
3. 设计至少一个 Test，并说明可能的反证。
4. 检查 Evidence 与 Coverage，包括缺失来源、解析失败、近似与截断。
5. 形成 `supported` / `contradicted` / `unknown` Finding。
6. 记录停止原因。

Orient 和 Explore 是必要认知活动，但不要求固定命令。小而静态的数据可以直接读取；大或陌生的数据应采用有界工具。

### 5.2 条件策略

| Strategy | 适用条件 | 不是必需的情况 |
|---|---|---|
| `probe` | 多文件、大输入、格式或时间覆盖未知 | 输入已知且很小 |
| `sample/peek` | 需要少量原始语境 | 已有明确锚点且无需原文 |
| `survey` | 输入陌生且没有可靠首个查询 | 已有错误码、堆栈、请求 ID 或明确事件 |
| `search` / `grep` | Test 有临时 literal/regex 谓词 | 领域 Capability 能直接产生更合适 Evidence |
| `preset` | 已有版本化、可复用过滤规则 | 一次性临时查询 |
| `expand` | EvidencePointer 上下文不足 | 当前 Evidence 已够用 |
| Scenario | 需要复现、断言、回归或交付产物 | 一次性探索尚未收敛 |
| `verify` | 最终依赖 Scenario Manifest | 未引用 Scenario 结果 |

### 5.3 自适应路由

```text
小型、静态、可安全完整读取
    -> 直接读取 -> 按需固化关键 Evidence

已有错误码、堆栈、时间或请求 ID
    -> Hypothesis -> search/领域 Capability -> expand

大型或陌生输入
    -> probe -> 可选 sample/survey -> 竞争 Hypothesis -> 分别测试
```

`survey` 和 DomainEvent 只能产生 Observation，不自动选择根因。

## 6. Strategy、Preset、Scenario 与 Knowledge

```text
Hypothesis
└── Test
    └── Strategy
        ├── direct read / sample / survey
        ├── grep / search
        ├── preset
        ├── extension capability
        └── Scenario

Knowledge
└── 在适用条件内推荐 Hypothesis、Test、Preset 或 Scenario
```

Scenario 是可重复测试配方，不是领域 Runtime。Extension 可通过 `ScenarioCapability` 提供领域解析和上下文；通用 Runtime 负责执行、预算、Evidence 与安全。

## 7. InvestigationState 契约（v1 已实现）

`InvestigationState` 是跨工具的版本化调查状态。它保存 Problem、Scope、Observation、Hypothesis、Test、Execution、Finding、Stop reason、Knowledge Candidate 以及可复用 SourceSession。其 persisted schema 独立于 Extension Protocol 版本。

工具仍可独立调用；传入 investigation path 时才把有界 Execution 关联到状态。只读 Summary、Timeline 和 Compare 用于恢复与审计，不重放原始 Evidence。参见 [Investigation 摘要](investigation-summary.zh-CN.md)和[时间线/结构比较](investigation-compare.zh-CN.md)。

## 8. 上下文与执行预算

渐进式披露是基本策略：

```text
元数据 -> 有界抽样/概览 -> EvidencePointer -> 按需 expand -> 完整 Artifact
```

Canonical Evidence 和 Result 保持完整可恢复；Agent-facing 投影可以压缩，但必须保留必要 Coverage、截断信号和恢复路径。Runtime 已具备预算、Agent profile、compact projection、Evidence Ledger 与 `expand-many`。Seen Evidence、跨轮 Context Delta、代表性 Evidence Group 和进一步的 Context Engine 属于 Runtime/Integration 演进，不进入 Extension Protocol。

不能为了省 Token 隐藏缺失 Evidence、近似、解析失败或 Coverage 缺口。

## 9. 知识生命周期

```text
Observation / DomainEvent
  -> Evidence-backed Finding
  -> Knowledge Candidate
  -> Independent validation
  -> Review
  -> Versioned Knowledge
```

Agent 不能自行晋升 Knowledge。正式治理规则见[知识治理](knowledge-governance.zh-CN.md)。

## 10. 可扩展性

主包提供机制，领域扩展提供事实和语义：

| 主包公共能力 | 领域扩展示例 |
|---|---|
| Extension Protocol v2 | Mobile、CI、Backend Extension |
| Core Plugin Capability | Source、Segmenter、Preprocessor、Event Transformer 注册包 |
| Agent Capability | 设备查询、CI 状态查询、领域只读/动作工具 |
| Scenario Capability | Mobile/CI 的 profile、preset、scenario resolver |
| Assertion / Report Capability | 领域断言与报告 |
| DomainEvent / EvidenceRef / Coverage | Mobile crash/network、CI build/test 等领域事实 |

`ScenarioRuntime` 是当前 Runtime 内部适配对象，不是 v2 Extension 的长期公共能力。若一个概念只能由单一领域解释，它应留在扩展；跨领域不变量才进入主包。

## 11. 当前实现与目标差距

| 能力 | 状态 |
|---|---|
| Source、Segmenter、Filter、Snapshot、Evidence、Manifest、Verify | 已实现 |
| `probe`、`sample/peek`、`survey`、`search`、`expand`、`run`、`verify` | 已实现 |
| InvestigationState、预算、SourceSession、Summary、Timeline、Compare | 已实现 |
| Knowledge Governance 与显式迁移 | 已实现 |
| Agent profile、compact projection、Evidence Ledger、`expand-many` | 已实现 |
| Agent Capability Registry 与 live safety gate | 已实现 |
| Extension Protocol v2 声明式 Contract 与内部 Scenario 适配 | 已实现 |
| Mobile Extension Protocol v2 迁移 | 待实现 |
| Context Engine：Seen Evidence、跨轮去重、Context Delta、代表样本 | 待实现 |
| MCP 基于 v2 Runtime/Context API 的适配 | 待实现 |
| Mobile 真机与 CI 跨领域验收 | 部分实现：Mobile 离线 fixture 已有；设备与完整 CI 验收尚未完成 |

演进顺序：先稳定公共 Contract 并完成文档/测试，再实现 Context Engine，再迁移 Mobile，最后让 MCP 只依赖公开 Runtime/Context API。

## 12. 架构演进与维护

### 12.1 哪些变更属于架构变更

以下任一变更必须同步更新本文及英文版：

- 包或层之间的依赖方向。
- Problem、Hypothesis、Test、Evidence、Finding、Knowledge 等公共概念或状态迁移。
- Extension Protocol、Capability Contract 或版本策略。
- Canonical Result / Agent View、Token、安全、快照、完整性和可信边界。
- “已实现/未实现”状态变化。

### 12.2 维护要求

1. 架构变更必须在同一个 PR 中更新 `architecture.md` 与 `architecture.zh-CN.md`。
2. 不兼容或有长期权衡的变更必须新增 ADR。
3. Schema 或公共 API 变更必须提供版本策略、迁移说明和测试。
4. 领域边界变化最终必须通过至少两个领域用例验证；否则保持为领域能力。
5. Extension 顶层协议优先稳定；新增功能优先增加可选、独立版本 Capability，而不是继续扩张顶层 API。
