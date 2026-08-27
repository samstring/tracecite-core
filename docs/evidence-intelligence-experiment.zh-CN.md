# Evidence Intelligence 实验

状态：实验性；仅用于 `experiment/evidence-intelligence` 分支验证，不属于 Extension Protocol v2 稳定承诺。

## 目标

在不让 TraceCite 变成自治 Agent、代码搜索器或 Observability 存储平台的前提下，把 runtime evidence 转换成一个可关联、可探索、可压缩、可恢复的 Evidence Space：

1. 通过稳定实体标识建立证据图；
2. 对重复 evidence 做确定性 grouping 和 representative selection；
3. 基于 seed、graph distance、severity、entity expansion、citation 与 source diversity 做确定性排序；
4. 在 Agent token budget 下生成显式暴露 omission / Coverage / recovery 的 EvidencePackage；
5. 用跨轮 Evidence / Group / Relation delta 避免重复上下文；
6. 把“发现稳定实体 -> 再取相关证据”的机械循环下沉到 TraceCite Runtime，减少 Agent 的 search/expand 决策轮次。

核心路径：

```text
Provider
  -> Normalize
  -> Correlate
  -> Explore Entity Frontier
  -> Group / Reduce
  -> Token-aware EvidencePackage
  -> Context Delta / Agent Transport
  -> Agent reasoning
```

## 新增探索闭环

实验分支提供领域无关的 `EvidenceProvider` contract：Provider 只根据 Evidence ID / `EntityRef` 取回事实，不负责相关性排序、根因判断或 Agent 推理。

Runtime 的 `investigate_evidence()` 在 `ExplorationPolicy` 的硬限制下执行：

```text
seed
 -> retrieve
 -> discover EntityRef
 -> retrieve related evidence
 -> correlate
 -> repeat until frontier exhausted / budget stop
```

默认限制包括 depth、retrieval 次数、Evidence 数量、source 数量、wall time、bytes scanned、provider errors、no-growth rounds 和 frontier size。每次自动展开都会记录 reason/provider/status/new evidence，并把超预算、provider failure、缺失 seed、关系悬空等情况暴露为 Coverage/diagnostics。

高层 `investigate()` 将探索结果继续交给 Grouping、Reducer 和 EvidencePackage，因此 Agent 可以用一次高层调用获得 bounded correlated evidence，而无需由模型逐轮执行 session -> request -> trace 的机械查询。

## 边界

- `EntityRef` / `EvidenceRelation` 只描述事实身份与关系，不表达根因。
- Correlation 不生成 Finding；temporal relation 永远是 `< 1.0` confidence 的启发式弱关系，不能冒充 exact entity relation。
- Orchestrator 不产生 Hypothesis / Finding，不使用 LLM planner。
- Provider 不嵌入领域结论；具体 Bugly/Sentry/Datadog/OTel 适配应只负责取证和标准化。
- Reducer 不使用 LLM，不修改 canonical evidence。
- EvidencePackage 是 Agent-facing projection；省 token 不能隐藏 Coverage 缺口。
- Canonical evidence / URI 必须可恢复；Agent projection 可以压缩，但不能破坏 provenance。
- 原有 `EvidenceLedger` / `ContextEngine` 暂不删除。实验验证通过后再设计兼容迁移，而不是直接替换。

## 当前可执行验证

组件级验证包含：

- multi-source `crash -> session -> request -> trace -> callback` 自动探索；
- 噪声 session 不进入目标 Evidence Graph；
- Provider error / retrieval budget 会返回 incomplete/partial；
- namespace 可防止相同 ID 在不同系统间被错误 exact join；
- 10,000 个同实体 Evidence 使用 star correlation，relation 数量保持 O(n)，Grouping 收敛为代表集合；
- EvidencePackage URI 可重新 resolve 到原 Provider record；
- synthetic structural benchmark 比较“Agent 自己逐轮跟实体”与“一次 investigate 调用”的结构性 loop 数。

这些测试证明的是实现正确性、boundedness、结构性 Agent-loop 下沉和组件级 Evidence retention；它们不能证明真实模型 token 或诊断质量收益。

## Model-level benchmark

外部 Agent Host runner 已扩展为五种比较模式：

1. `shell_rg`
2. `tracecite`
3. `tracecite_context`
4. `tracecite_intelligence`
5. `tracecite_investigate`

`tracecite_intelligence` 用于隔离“关联/分组/压缩”的价值；`tracecite_investigate` 用于额外测量“自动 Entity exploration 是否真正减少 Agent/model loop”。详细公平性和指标见 `benchmarks/agent-investigation/EVIDENCE_INTELLIGENCE_MODES.md`。

## 合并验收

最终合并回 `refactor/agent-v2` 前，仍需要真实 Agent Host benchmark 证明：

- provider-reported 总输入 token 明显下降；
- tool calls / model calls / search-expand loops 明显下降；
- evidence recall 不下降；
- answer correctness 不下降；
- citation 可恢复且准确；
- 对有 gold relation 的 case，correlation precision/recall 达到可接受水平；
- wall time 和资源开销没有抵消上下文收益。

只有这些结果成立，才应把实验 API 收敛为正式 Runtime/Integration contract，并开始合并新旧 Ledger/Context 路径。
