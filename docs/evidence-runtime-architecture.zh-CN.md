# TraceCite Evidence Runtime 架构契约

> 本文档定义 `experiment/evidence-intelligence` 分支重构后的**唯一目标架构**。
>
> 本轮允许 breaking refactor：**不做 v2 命名，不为不合理旧接口保留兼容层，不为了历史 schema 可读性保留错误语义。** 新模型落地后即成为唯一模型。
>
> 若本文档与旧实验文档、旧 handoff、旧 API 说明冲突，以本文档和 `docs/PROJECT_GUARDRAILS.md` 的较新约束为准。

## 1. 产品定位

TraceCite 是：

> **面向 Agent 的 provenance-aware、session-aware Evidence Runtime。**

TraceCite 不负责：

- 生成或排序假设；
- 决定下一步调查哪个实体/来源；
- 做 causal reasoning / root-cause ranking；
- 判断证据是否足够完成任务；
- 建议 Agent 停止；
- 取代 shell / grep / browser / Agent Host；
- 为 benchmark 注入 preferred path 或 hidden answer。

最高级边界保持：

> **Agent 负责想和决定；TraceCite 负责证据。**

## 2. 从历史实验得到的必须解决的问题

本架构不是从抽象设计出发，而是直接覆盖已观察到的问题：

1. **重复证据浪费上下文**：相同 Evidence 多次命中不应重复发送 body。
2. **新 query 命中旧 Evidence 仍有新 relevance**：`new_evidence=0` 不得隐藏当前 query 与旧 Evidence 的匹配关系；必须保留 `matched_existing_evidence`。
3. **Agent 可能忘记旧 Evidence**：dedup 不能等同于禁止重读；必须支持 exact replay/materialize。
4. **大文件上下文不可直接 dump**：Evidence projection 必须 bounded、可恢复、可验证。
5. **Agent 深挖不收敛**：`139417/140268` 显示核心证据很早到达，但 Agent 仍持续几十到上百次工具调用。
6. **只统计 TraceCite 调用不够**：`140039/139417` 显示 Agent 可切回 `bash/grep/read`，绕开 TraceCite telemetry。
7. **native 工具不能被简单禁止**：统计、转换、验证等 native 操作在真实 Agent 工作流中仍合理。
8. **Evidence boundary 必须明确**：`139417/140268` 证明某些 deeper cause / fix 无法由输入日志直接建立；正确回答应允许 `inferred` / `not established`，而不是逼 Agent 找不存在的直接证明。
9. **Identity safety 是 Core 真正价值**：`identifier_only_correlation_safe=false`、`minimum_safe_correlation_key`、`source_uniqueness=unverified` 属于机械 Evidence fact，必须保留。
10. **Provider 429/overload 不能算产品输赢**：benchmark 必须把 task result 与 infra validity 分开。
11. **Token saving 必须受 correctness gate 约束**：少 token + timeout / 低质量答案不算产品收益。
12. **上层稳定性**：Pi / MCP / Mobile / Codex 等上层长期只依赖稳定 canonical API，不依赖 Core 内部实现。

## 3. 三个正式 Contract

### 3.1 Evidence Contract — TraceCite Core 所有

Core 只拥有机械 Evidence 能力：

- source/version identity；
- evidence identity / provenance；
- bounded retrieval；
- exact materialization；
- replay；
- session-scoped seen / repeated / coverage；
- current-query-hit-old-evidence；
- deterministic aggregate；
- caller-scoped mechanical traversal；
- integrity / verification；
- deterministic identity/correlation constraints；
- truncation / omission / missing-evidence / acquisition-end facts。

Core 不产生：

- `root_cause_confidence`；
- `evidence_sufficient`；
- `ready_for_reasoning`；
- `stop_recommended`；
- `next_best_query`；
- causal priority / likelihood。

### 3.2 Host Contract — Pi / MCP / Codex / custom host 所有

Host 可以拥有：

- 全部 tool activity（TraceCite + native）；
- context / token / tool / wall-clock budget；
- native tool observation；
- optional checkpoint / reminder；
- Agent 与工具之间的交互策略。

Host telemetry 不等于 Evidence truth。

TraceCite Core 不假装知道外部 `bash/grep/read/browser` 看到了什么；只有 Host 能观察到的内容才可进入 Host Tool Activity Ledger。

Checkpoint 若存在，只能要求 Agent **重新做决定**，不能替 Agent 给出停止结论。

### 3.3 Evaluation Contract — Benchmark 所有

Benchmark 同时评估：

- answer correctness；
- direct evidence support；
- inference qualification；
- unsupported-from-log boundary；
- citation / provenance；
- overclaim / contradiction；
- tool trajectory；
- model-visible context / token metrics；
- wall time / timeout；
- infra validity（429 / quota / provider unavailable 独立处理）。

## 4. 唯一 Evidence Session Owner

`RetrievalSession` 是 Core 中唯一的 session-scoped Evidence memory owner。

它应直接拥有：

```text
session id / revision
seen evidence identities
seen result identities
seen relation/group identities
covered source-version ranges
source observations / generations
recent retrieval operations
request fingerprints
repeated-evidence accounting
replay state
```

长期不保留并行 owner：

- 不保留独立 `RetrievalSessionTelemetry` sidecar；
- 不让 `InvestigationState.executions` 成为 novelty / coverage source of truth；
- 不让 `EvidenceProgressTracker` 再维护另一份 seen-evidence / range state。

### 4.1 必须保留的 repeated-evidence 语义

第一次：

```text
query A -> Evidence L100 body
```

后来：

```text
query B -> 同一 Evidence L100
```

第二次允许：

```text
new_evidence = 0
repeated_evidence > 0
matched_existing_evidence = [L100 ref]
```

但不得再次自动发送 body。

### 4.2 Recall / Replay

“曾经发送”不等于“Agent 仍记得”。

必须保留显式：

```text
materialize(ref/range)
replay(ref/range)
```

Replay：

```text
replayed = true
new_evidence = 0
```

Replay 不改变 Evidence novelty。

## 5. Canonical Evidence API

最终 Agent-facing canonical API 收敛为六类原语：

### 5.1 `retrieve`

Caller 指定 target/predicate/scope，Core 返回匹配 Evidence、Coverage、Provenance、Novelty。

### 5.2 `materialize`

精确展开 EvidencePointer / source-version range。

### 5.3 `replay`

显式重新读取已经交付过的 Evidence；不计新 Evidence。

### 5.4 `aggregate`

对 caller-supplied scope/predicate 做 deterministic aggregation，例如：

- count；
- distinct；
- group；
- distribution；
- exact occurrence summary。

目的是减少 Agent 仅为了 `grep | wc` / `sort | uniq -c` 而离开 Evidence Runtime。

禁止加入 causal rank / root-cause score。

### 5.5 `traverse`

Caller 指定 seed + scope + limits，Core 做 deterministic mechanical traversal。

`traverse` 不是 Agent investigation planner。

Core 可以机械展开 caller 已指定 scope 内的 stable identities / provider records / exact relations；不能因“看起来重要”而自己选择新的 investigation direction。

### 5.6 `verify`

验证 mechanical predicate / integrity / source version / manifest / exact Evidence fact。

## 6. Compatibility wrapper 原则

`probe/search/expand/sample/survey/...` 如仍有价值，可作为 convenience wrapper 暂时存在；但：

- 不能拥有独立语义；
- 不能维护独立 seen-state；
- 不能绕过 canonical Evidence API；
- 如果 wrapper 只为错误旧行为存在，应直接删除。

本轮不以 API compatibility 为目标。

## 7. 删除错误 Progress / Stop 语义

现有 Runtime 中以下概念与 Guardrails 冲突，应删除而不是换名字保留：

```text
ready_for_reasoning
readiness = ready/insufficient/partial
stop_recommended
“no growth => should stop”
“requirements satisfied => investigation complete”
```

允许保留的仅是机械事实：

```text
new_evidence
new_lines
new_entities
new_relations
source_complete
scope_exhausted
frontier_exhausted
consecutive_no_growth
coverage_status
budget_limit_reached
provider_unavailable
source_changed
```

若 acquisition 因硬限制结束，字段应表达：

```text
acquisition_end_reason
```

而不是 Agent stop recommendation。

## 8. `investigate` 改为 `traverse`

现有 `investigate()` / `EvidenceInvestigation` / `ExplorationFrontier` 容易越界为“Runtime 替 Agent 决定下一步”。

目标：

```text
investigate -> traverse
EvidenceInvestigation -> EvidenceTraversal
ExplorationPolicy -> TraversalLimits
```

语义从：

> Runtime investigates related evidence

收敛为：

> Runtime mechanically traverses a caller-selected evidence scope.

## 9. Routing 只管理 Transport

Routing 可以根据：

- source size；
- model-visible context budget；
- output limit；
- seen/repeated evidence ratio；
- source-version coverage；

决定：

```text
DIRECT / BOUNDED / materialized form
```

Routing 不允许决定：

- 下一个 entity；
- 哪个 hypothesis 更可能；
- 哪条 Evidence 更接近 root cause；
- 是否应该结束调查。

## 10. Evidence Selection 只能是 Transport Heuristic

generic high-signal lexical selection（panic/error/fatal 等）如果保留，必须明确：

- 仅用于 bounded projection；
- 不代表 causal relevance；
- 不成为 root-cause ranking；
- 完整 match set 必须可恢复；
- truncation/omission 必须显式。

## 11. InvestigationState 的新定位

`InvestigationState` 保留为**可选 Agent/Host coordination store**，而不是 Evidence Runtime 必要依赖。

它可以记录：

```text
problem
scope
hypothesis
test
finding
notes
budget
audit links
```

但：

- `retrieve/materialize/replay/...` 在没有 InvestigationState 时必须完整工作；
- RetrievalSession 不读取 hypothesis/finding 决定 retrieval；
- dedup/coverage 不依赖 InvestigationState；
- InvestigationState 不成为 Core stop/sufficiency engine。

## 12. Host Tool Activity Ledger

整个 Agent trajectory 不是 Core state。

官方 Pi adapter（以及支持 hook 的 MCP/Codex host integration）应可记录：

```text
total tool calls
TraceCite evidence calls
native search/read calls
opaque shell calls
context/token/wall time (host/provider 可见时)
```

不得把无法解析的 shell 输出伪装成 canonical Evidence。

Host Ledger 用于：

- observability；
- benchmark trajectory analysis；
- optional checkpoint；
- 发现 Agent 从 TraceCite 切回 native 后继续深挖的问题。

它不进入 RetrievalSession。

## 13. Optional Host Checkpoint

Host 可在 tool budget / wall time / activity threshold 到达时展示机械 summary，并要求 Agent重新选择：继续或回答。

示例语义：

```text
Total tool calls: 40
TraceCite evidence operations: 21
Native evidence-oriented operations: 13
Other tools: 6

TraceCite recent retrieval facts:
new 2 / repeated 2 / no-match 6

Continue or answer based on your own judgment.
```

禁止：

```text
Evidence is sufficient.
You should stop.
Root cause is probably X.
```

Checkpoint 属于 Host policy，不属于 TraceCite Evidence Contract。

## 14. Final Answer / Evaluation Evidence Boundary

Benchmark truth schema 正式区分：

```text
supported
inference_supported
unsupported_from_log
```

Agent最终表达可对应：

```text
Observed
Inferred
Not established
```

但 support-level 判断仍由 Agent答案和 benchmark truth 比较得出，不由 TraceCite Core替 Agent分类。

评分原则：

- Gold `supported`：必须有直接 Evidence / citation；
- Gold `inference_supported`：结论可得分，但必须明确 qualified inference；
- Gold `unsupported_from_log`：明确证据边界应得分；
- 将 inference/unsupported 硬说成 direct fact 视为 overclaim。

## 15. Benchmark Validity

每个 arm 同时产生：

```text
task_result
run_validity
```

`run_validity` 至少区分：

- provider clean；
- 429 / overloaded；
- quota / payment；
- provider unavailable；
- harness failure。

被 infra 污染的 arm 可以用于行为诊断，但不能用于 clean A/B 产品胜负。

## 16. Correctness-first 成功标准

产品改动只有在以下顺序成立后才能称为收益：

1. required answer quality 不下降；
2. Evidence support / boundary 不下降；
3. provenance / replay / recoverability 保持；
4. timeout / pathological trajectory 不增加；
5. tool calls / context / token / wall time 才作为效率收益评估。

禁止用“token 少了”掩盖 timeout 或答案退化。

## 17. 上层依赖原则

Pi / MCP / Mobile / Codex adapter 长期只依赖 canonical Evidence Contract：

```text
EvidenceRequest
EvidenceResult
EvidenceRef / EvidencePointer
SourceVersion
Coverage
RetrievalSession
retrieve
materialize
replay
aggregate
traverse
verify
```

Core 内部 routing / cache / selection / reducer / storage 可以继续演进，不应要求所有上层反复跟改。

## 18. 文档治理

- 本文档：最终架构 source of truth。
- `docs/PROJECT_GUARDRAILS.md`：不可破坏边界。
- `docs/evidence-runtime-refactor-plan.zh-CN.md`：当前工作项、状态、验收、commit/test source of truth。
- `docs/evidence-intelligence-work-progress-handoff.zh-CN.md`：历史进展/交接；若旧章节与新架构冲突，应逐步清理，不再作为新设计依据。

任何 Agent-facing 行为改动，在代码提交前必须能对应到上述文档中的明确条目。