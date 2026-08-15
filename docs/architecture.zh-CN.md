# TraceCite 架构设计

状态：规范性文档（Normative）  
适用范围：TraceCite 主发行包、官方领域扩展以及 Agent/CLI/MCP 等宿主适配器

本文是 TraceCite 的顶层架构依据。Agent 接入、扩展契约、知识治理和具体验收文档都必须遵守本文边界。本文描述目标架构时会明确标注当前尚未实现的部分，不能把规划能力当成现有行为。

## 1. 产品定义

TraceCite 是一个**证据驱动的 Agent 调查框架**：

- Agent 负责理解问题、自由探索、建立假设、选择测试和解释结果。
- TraceCite 负责保存调查状态、确定性地处理数据、控制预算、生成可追溯证据，并管理知识生命周期。
- 领域扩展负责提供 Mobile、CI、后端、数据库等领域的数据适配与语义。

核心原则是：

> 流程约束结论，不约束探索动作。

TraceCite 不是内置 LLM 的自治诊断 Agent，也不是要求所有问题都经过同一命令漏斗的日志搜索器。

## 2. 架构不变量

以下约束在所有后续演进中必须保持，除非通过明确的架构决策和版本迁移进行修改：

1. Core 只提供通用、确定性、可复现的证据能力，不包含设备、产品、公司、应用或业务知识。
2. Agent 可以自由选择探索方法；最终 Finding 必须说明 Hypothesis、Evidence、Coverage、限制和停止原因。
3. `status` 表示执行状态，`outcome` 表示认识结果；两者不能合并。
4. 零命中、覆盖不完整、证据缺失和执行失败不能自动证明事件不存在，默认保持 `unknown`。
5. 可引用 Evidence 必须指向不可变快照和行号，或指向已通过完整性校验的 Manifest。
6. Agent 生成的结论不能自动晋升为可信 Knowledge，也不能作为自己的独立验证。
7. Extension 提供能力和领域语义；Runtime 保留执行、预算、证据、验证、安全和停止控制。
8. Core 不导入 Runtime 或领域包；Runtime 不导入具体领域包。领域扩展只依赖公开 TraceCite API。
9. 任何有界、抽样、近似或截断结果都必须显式暴露 Coverage，不能静默伪装成完整结果。
10. 新能力应首先证明能服务至少两个不同领域，或明确留在单独的领域扩展中。

## 3. 逻辑架构

```text
用户问题
   |
   v
Agent Host
理解、推理、选择下一步、与用户交互
   |
   v
Investigation Runtime  <---->  Knowledge Registry
调查状态、预算、流程关联          候选、审核、版本、失效
   |
   v
Evidence Core
Source、Segmenter、Sample、Survey、Filter、Snapshot、Evidence、Manifest、Verify
   |
   v
Evidence Store
冻结输入、过滤产物、事件、报告、Manifest

Domain Extensions
通过公共契约向 Core/Runtime 注册 Source、Segmenter、Preprocessor、
Event Transformer、Assertion、Reporter、Preset、Scenario Runtime 等能力。
```

### 3.1 Agent Host

负责：

- 把用户自然语言转成 Problem 和 Scope。
- 决定直接读取、抽样、survey、search、Scenario 或领域工具。
- 建立可证伪 Hypothesis，设计 Test，并同时寻找支持与反证。
- 在证据不足时保持 `unknown`，或向用户请求新的输入和授权。

不负责绕过 Evidence 约束，也不能把推理文本当成独立证据。

### 3.2 Investigation Runtime

负责保存 Investigation 状态，把一次次工具调用关联到 Problem、Hypothesis 和 Test，并实施预算、安全和停止策略。

Runtime 已提供一等公民的、版本化的 `InvestigationState`。工具仍可独立调用；只有传入调查路径时才记录有界的 Execution。

### 3.3 Evidence Core

`tracecite_core` 是 Python 标准库实现的稳定证据内核，负责：

- 解析和冻结输入。
- 流式分段、抽样、概览和过滤。
- 生成哈希寻址的 EvidencePointer。
- 管理运行目录、产物和 Manifest。
- 校验引用和运行完整性。

Core 不理解“白屏”“卡顿”“构建失败”等领域概念，也不决定根因。

### 3.4 Knowledge Registry

负责 Candidate Knowledge 的提案、独立案例验证、审核、晋升、版本与失效检查。正式流程见[知识治理](knowledge-governance.zh-CN.md)。可信 Knowledge 只能为未来调查推荐 Hypothesis、Test、Preset 或 Scenario，不能替代本次 Evidence。

### 3.5 Domain Extensions

领域扩展保存领域数据和语义。Mobile 只是一个扩展，不是 Core 特例。相同公共契约应支持 CI、后端、网络、数据库和安全调查。正式边界见[扩展契约](extension-contract.md)。

## 4. 调查领域模型

| 概念 | 含义 | 必须关联 |
|---|---|---|
| Problem | 用户真正要回答的问题，不等同于搜索词 | Scope |
| Scope | 数据源、主体、时间、权限与预算边界 | Problem |
| Observation | 未作因果解释的可观察事实 | 来源或 Evidence |
| Hypothesis | 可以被证据支持或反驳的陈述 | Problem |
| Test | 验证一个 Hypothesis 的具体计划 | Hypothesis |
| Strategy | Test 采用的执行方法 | Test |
| Evidence | 可复查、可寻址的证据 | Test、来源、哈希 |
| Coverage | 本次操作覆盖、遗漏、抽样、近似和截断信息 | Test 或 Evidence |
| Finding | 对 Hypothesis 的 `supported`、`contradicted` 或 `unknown` 判断 | Evidence、Coverage |
| Knowledge Candidate | 从 Finding 提取的可复用提案 | Investigation、Evidence |
| Knowledge | 通过独立验证和审核的版本化知识 | Candidate、审核记录 |

Observation 与 Finding 必须分开。例如“10:30:04 出现 HTTP 504”是 Observation；“HTTP 504 导致白屏”是需要验证的 Hypothesis 或 Finding。

## 5. 通用调查协议

协议定义每次调查必须回答的问题和保存的产物，不强制每个阶段使用固定命令，也不要求所有阶段各执行一次。

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

一次可交付的调查必须具备：

1. **定义 Problem 与 Scope**：明确问题、允许输入、时间范围、权限、预算和停止条件。
2. **建立至少一个可证伪 Hypothesis**：用户描述可以成为调查目标，但不能不经转换直接成为日志查询或结论。
3. **设计至少一个 Test**：说明预期 Observation、可能的反证以及使用的 Strategy。
4. **检查 Evidence 与 Coverage**：支持证据、反证、缺失来源、时间解析率、近似和截断必须分别检查。
5. **形成 Finding**：只能是 `supported`、`contradicted` 或 `unknown`，并限定在已声明 Scope 内。
6. **记录停止原因**：假设已解决、证据耗尽、预算到达、需要新授权或缺少输入。

Orient 和 Explore 是必要的认知活动，但不要求固定调用某个 TraceCite 工具。对一个很小且静态的文件，Agent 可以直接读取；对大文件或未知输入，应采用有界工具。

### 5.2 条件策略

| Strategy | 适用条件 | 不是必需的情况 |
|---|---|---|
| `probe` | 多文件、大输入、格式或时间覆盖未知 | 输入已知且很小 |
| `sample/peek` | 需要少量原始语境，避免高频模板偏置；可选的有界观察 | 已有明确技术锚点且无需原文语境 |
| `survey` | 输入陌生且没有可靠首个查询 | 已有错误码、堆栈、请求 ID 或明确事件 |
| `search` / `grep` | Test 有临时 literal/regex 谓词 | 领域工具能直接产生更合适证据 |
| `preset` | 已有版本化、可复用过滤规则 | 一次性临时查询 |
| `expand` | EvidencePointer 上下文不足 | 现有证据已包含足够上下文 |
| Scenario | 需要复现、断言、回归或交付产物 | 一次性探索尚未收敛 |
| `verify` | 最终依赖 Scenario Manifest | 未引用 Scenario 结果 |

### 5.3 自适应路由

```text
小型、静态、可安全完整读取
    -> Agent 自由读取 -> 最终按需固化关键 Evidence

已有明确错误码、堆栈、时间或请求 ID
    -> 直接建立 Hypothesis -> search/领域工具 -> expand

大型或陌生输入，缺少可靠搜索锚点
    -> probe -> 可选 sample/survey -> 竞争 Hypothesis -> 分别测试
```

`survey` 是有界描述能力，输出候选 Observation，不能自动选择根因。因果不明确时应保留至少两个竞争 Hypothesis。

`sample`/`peek` 是可选的自由探索观察：需要少量原始语境，或担心
survey 按频率统计造成首视角偏置时可以使用；它不是强制调查漏斗阶段。
Core 默认先冻结不可变 snapshot，提供 SHA-256 与按行可引用指针（Runtime
负责适配为 EvidencePointer），支持 `head-tail` 和确定性 `uniform` 两种
有界策略。`last`、`since`、`until` 时间范围、实际扫描/覆盖范围、采样
省略、字符截断和未返回项都写入 Coverage；结果始终使用
`outcome=not_assessed`，不推断根因或结论。

## 6. Strategy、Preset、Scenario 与 Knowledge

```text
Hypothesis
└── Test
    └── Strategy
        ├── direct read / sample / survey
        ├── grep：本次临时查询
        ├── preset：版本化过滤组件
        ├── extension tool：领域数据操作
        └── Scenario：可重复执行的完整测试配方

Knowledge
└── 在适用条件内推荐 Hypothesis、Test、Preset 或 Scenario
```

`grep` 与 `preset` 同时存在时可以按 Scenario 声明的组合方式执行；当前实现使用 OR。运行记录会保留一个 canonical `filter` provenance 对象，其中包含组合方式、解析后的组件 Pattern、Preset 名称及版本/来源/哈希（缺少版本元数据时明确写为 `unknown`），并在每条命中记录中保留有界、确定性的 `matched_by` 组件 ID；历史顶层最终 `pattern` 为兼容性保留。若领域 Scenario resolver 替换了已经合并的表达式，则最终 `scenario:<name>` 表达式是唯一生效匹配器，preset/grep 只作为 provenance 输入保留。Core 直接调用且未声明组件时使用保留的 `pattern` fallback，并显式标记。命中 Preset 只表示某条记录符合筛选规则，不等于根因成立。

## 7. InvestigationState 契约（v1 已实现）

Runtime 提供版本化、可序列化的调查状态，核心结构如下：

```json
{
  "schema_version": 1,
  "investigation_id": "INV-001",
  "problem": {"question": "为什么启动后白屏"},
  "scope": {"sources": [], "time": {}, "budgets": {}},
  "observations": [],
  "hypotheses": [
    {
      "id": "H1",
      "claim": "首屏请求超时阻止渲染完成",
      "status": "open",
      "test_ids": ["T1"],
      "supporting_evidence": [],
      "contradicting_evidence": []
    }
  ],
  "tests": [
    {
      "id": "T1",
      "hypothesis_id": "H1",
      "intent": "检查首屏请求结果",
      "expected_observation": "请求在白屏前超时",
      "contradicting_observation": "请求成功且渲染仍未完成",
      "strategy": {},
      "coverage": {}
    }
  ],
  "executions": [],
  "findings": [],
  "stop_reason": null,
  "knowledge_candidates": []
}
```

每个 Test 关联 Execution ID，并保存自己声明的 Coverage；`latest_execution_id` 只是导航提示，不能把最后一次 Execution 的 Coverage 误当成整个 Test 的汇总覆盖。Execution 只保存操作状态/结果、参数、Evidence 指针、artifact 指针、verification/run 元数据和 Coverage，不复制 AgentResult 的 `data` 或原始日志正文，并显式记录被省略/截断的字段。Finding 会把 open Hypothesis 转成 `supported`、`contradicted` 或 `unknown`；`supported` Finding 必须包含 supporting Evidence，`contradicted` Finding 必须包含 contradicting Evidence，`unknown` 可以省略二者；stop_reason 会把 active 调查转为 completed。`InvestigationStore` 使用 Core 已有的原子 JSON 写入和文件锁。公共 Python API 为 `InvestigationStore`、`create_investigation`、`load_investigation` 和 `attach_investigation_result`；现有工具增加可选的 `investigation_path`、`hypothesis_id`、`test_id` 参数且保持原有结果契约。

Runtime 还提供显式的 `InvestigationStore.propose_knowledge_candidate()`
操作，把一个符合条件的 `supported` Finding 提交到独立的
`KnowledgeGovernanceStore`。候选必须有支持 Evidence 且至少关联一个 Test；
`unknown` 和 `contradicted` Finding 会被拒绝，不能直接进入可复用声明。
候选 payload 包含调查 ID 与来源 schema/revision、Hypothesis 声明与 outcome、
调用方提供的适用条件/排除条件、支持与反证引用、Coverage/限制以及相关 Test
策略/配方。InvestigationState 只保存候选 ID、Finding ID、候选库链接和最新
状态元数据。操作先写候选再写链接，提案失败时不会让调查状态声称已关联；同一
Finding 只有在规范化 payload 与稳定提案身份一致时才会幂等复用，参数漂移会
返回冲突。支持与反证引用使用不可变的
`evidence://sha256/<64 位十六进制摘要>#L<起始行>[-L<结束行>]` 指针格式。
链接中的 status 是创建链接时的快照；审核/晋升不会静默改写
InvestigationState，需要最新状态时由宿主显式刷新。

调查可以声明带版本的可选 `BudgetPolicy`，以正数限制执行次数、search/query
次数、记录的 Evidence 指针数、`expand` 请求/返回字符数和耗时。关联工具会在
昂贵操作前通过 InvestigationState 锁预留额度，结束时用实际用量结算；额度不足
时返回结构化 `BudgetExhausted`，不执行操作。用量和剩余额度持久化；预算耗尽的
调查会记录 `budget_exhausted` stop reason。Evidence 指针会按操作的有界最坏情况
（例如 search 的结果上限；scenario `run` 在调用扩展前也使用同一公共上限）预留，
因此严格指针上限不足时可以在扫描或执行前保守拒绝，不会在执行后超额；
snapshot=false 的原始语境调用不预留不可变指针。

关联的确定性缓存保持保守范围：只有默认 snapshot、无显式输出副作用的只读
`probe` 和 `search` 可以缓存。Key 包含 operation、规范化参数、来源 SHA-256/
snapshot、segmenter 身份、结果 schema 和缓存工具版本。缓存命中仍会写入新的
Investigation Execution。缓存条目有数量/来源/证据/artifact/字节上限，来源或
artifact 缺失或哈希变化会丢弃条目。`survey`、`sample`、`expand`、`verify`、
`run`、扩展、live source/action、错误、no-snapshot 和输出副作用调用都会显式
绕过缓存。

Runtime 还提供版本化、只读的 Investigation 完整性摘要。它只返回有界计数、未解决
ID、Coverage/记录缺口、停止状态和领域无关的建议动作类别，不复制 claim、Evidence
正文或原始工具数据。摘要只是协调建议，不是强制漏斗、诊断结论，也不能证明调查
已经穷尽。
有界、只读的时间线和结构比较视图可用于审计或恢复调查，而不重放原始证据。它们
只暴露 ID、控制时间戳、状态、计数、Coverage/省略信号、预算差异和关系；结构变化
不是异常或 Finding。参见 [Investigation 摘要](investigation-summary.zh-CN.md)和
[时间线/结构比较](investigation-compare.zh-CN.md)。

## 8. 上下文与执行预算

渐进式披露用于控制上下文范围：

```text
元数据 -> 有界抽样/概览 -> EvidencePointer -> 按需 expand -> 完整 Artifact
```

Runtime 和扩展应遵守：

- 小型输入允许直接读取，避免工具调用成本高于原始内容。
- 大型或变化输入优先返回元数据、统计和引用，而不是正文。
- 相同输入哈希和参数的确定性操作可以复用缓存。
- 大正文写入 Artifact；AgentResult 只返回有限 EvidencePointer 和 Coverage。
- Agent 适配层可以提供可选的紧凑投影，但必须保留可无损还原的 Evidence 身份、
  认识状态和必要的 Coverage/截断信号；省略内联证据时必须保留一个恢复 Artifact。
  canonical Runtime Result 与磁盘 Artifact 不得因投影而改变。
- Agent 适配层可以把 canonical Result 保存到按内容寻址的 Evidence Ledger，只暴露
  经过校验的结果标识。Ledger 条目必须不可变；批量展开必须重新校验源摘要；缺失或
  截断引用必须显式进入 Coverage，不能静默省略。
- 对话适配层只能压缩模型已经读取过的工具结果，并保留最新结果与确定性恢复路径。
  历史压缩只是传输优化，不是删除证据。
- 紧凑投影可以使用只声明一次列名的行式编码和共享合并 Context，但每个 Evidence
  身份仍必须确定性映射到其精确选中行范围和不可变来源。
- Agent 传输 Profile 按单次分析选择，并且只存在于 ``tracecite.integrations``。Profile
  可以改变传输编码和已读历史压缩，但不得改变 canonical Result 语义、选择另一个 Agent，
  也不得引入 Core 到 Integration 的依赖。
- InvestigationState 保存结构化决策，不复制日志正文。
- 每个 Test 关联 Hypothesis，避免没有验证目标的连续搜索。
- 达到用量、查询、时间或证据预算时停止，并记录 `stop_reason`。

不能为了满足预算隐藏截断、近似、解析失败或缺失证据。

## 9. 知识生命周期

```text
Observation
  -> Evidence-backed Finding
  -> Knowledge Candidate
  -> 独立案例验证
  -> 不同审核人审核
  -> Approved Knowledge
  -> 重验证、版本升级或失效
```

Knowledge 至少描述：适用条件、不适用条件、可验证陈述、支持与反证、测试配方、来源版本、审核状态和失效条件。它只能缩小未来探索空间，不能跳过本次 Test 和 Evidence。

治理库使用 schema v2，并提供显式 v1 迁移；所有读-改-写操作使用文件锁。已晋升
知识只有在有效性为 `current` 时可用；`stale`、`expired`、`superseded` 记录仍可
审计，但不会被静默信任。重验证必须由独立审核人完成。语义变化会创建带血缘的
替代版本；仅提出替代候选不会提前废除已晋升旧知识，必须等新版本完成验证和晋升。

## 10. 可扩展性

主发行包提供稳定机制，领域包提供语义：

| 主包公共能力 | 领域扩展示例 |
|---|---|
| Source Provider | APM、CI artifact、数据库查询结果 |
| Segmenter / Format | Android logcat、iOS syslog、构建日志 |
| Preprocessor | 符号化、脱敏、归档解包 |
| Event Transformer | 崩溃、请求、页面、构建阶段事件 |
| Assertion | 主线程阻塞阈值、构建步骤完整性 |
| Reporter | Mobile 报告、CI 报告 |
| ScenarioRuntime | Mobile、CI、Backend Runtime |
| Skill / Knowledge Pack | 领域调查方法、Preset、Scenario、已审知识 |

若一个概念只能由单一领域解释，它应留在领域扩展；只有证据、生命周期、预算和协议等跨领域不变量进入主包。

## 11. 当前实现与目标差距

| 能力 | 状态 |
|---|---|
| Source、Segmenter、Filter、Snapshot、Evidence、Manifest、Verify | 已实现 |
| `probe`、`survey`、`search`、`expand`、`run`、`verify` | 已实现 |
| Scenario、Assertion、Reporting、Extension API | 已实现 |
| Candidate Knowledge 的提案、验证与晋升 | 已实现基础治理 API |
| Skill 中的调查建议和安全边界 | 已实现，但仍主要是文字协议 |
| 版本化 `InvestigationState` | 已实现 v1，原子写入并加锁 |
| 调查级 BudgetPolicy 与确定性缓存 | 已实现：关联工具预留/结算预算，probe/search 使用保守缓存 |
| Hypothesis/Test 与工具调用的结构化关联 | 已实现，校验 ID 与交叉引用 |
| 通用 `sample/peek` | 已实现：默认 snapshot 的有界 head-tail 与确定性 uniform 抽样 |
| Preset 组件级 provenance 与逐命中 `matched_by` | 已实现：有界 OR 组件、确定性命中 ID 以及运行/Manifest 元数据 |
| 调查到 Knowledge Candidate 的统一连接 | 已实现显式、幂等的桥接，调查状态只保存指针元数据 |
| Investigation 完整性建议摘要 | 已实现 v1，为有界只读视图 |
| Investigation 时间线与结构比较 | 已实现 v1，为有界只读视图 |
| Knowledge 锁、有效性、重验证与版本替代 | 已实现 governance schema v2，并提供 v1 迁移 |
| Mobile 公共扩展与 PlatformBackend 离线契约 | 部分实现：离线 fixture 通过，真机验收待执行 |
| CI 领域验收 | 待执行 |

演进时应优先补齐协议状态和跨领域验证，而不是继续把领域知识或更多固定搜索步骤放入 Core。

## 12. 架构演进与维护

### 12.1 哪些变更属于架构变更

以下任一变更都必须同步更新本文及英文版：

- 包或层之间的依赖方向。
- Problem、Hypothesis、Test、Evidence、Finding、Knowledge 等公共概念或状态迁移。
- AgentResult、Evidence、Manifest、Investigation 或 Knowledge 的公开 Schema 语义。
- 必要调查步骤、`status/outcome`、Coverage 或停止规则。
- Extension 注册面、能力边界、加载和授权模型。
- Preset、Scenario、Knowledge 的职责或生命周期。
- Token、安全、快照、完整性和可信边界。
- “已实现/未实现”状态发生变化。

仅有内部重命名、性能优化或不改变上述契约的修复，可以不写架构决策，但仍应保证本文状态准确。

### 12.2 维护要求

1. 架构变更必须在同一个提交或 PR 中更新 `architecture.md` 与 `architecture.zh-CN.md`。
2. 不兼容或存在长期权衡的变更必须在 `docs/adr/` 新增 ADR，记录背景、决策、替代方案、影响和迁移计划。
3. Schema 或公共 API 变更必须提供版本策略、迁移说明和测试。
4. 领域边界变化必须由至少两个领域用例验证；否则保留在领域扩展。
5. 完成目标能力时必须更新第 11 节状态，不能让规划项长期伪装成未实现或已实现。
6. PR/评审应检查本文、[Agent 接入指南](agent-integration.zh-CN.md)、[扩展契约](extension-contract.md)、[知识治理](knowledge-governance.zh-CN.md)和[验证清单](validation-checklist.md)是否需要同步更新。

ADR 流程和模板见 [`docs/adr/README.md`](adr/README.md)；Schema/API 迁移说明见 [`docs/migrations/README.md`](migrations/README.md)。
