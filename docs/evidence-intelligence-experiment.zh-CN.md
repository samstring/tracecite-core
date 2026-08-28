# Evidence Intelligence 实验

状态：实验性；仅用于 `experiment/evidence-intelligence` 分支验证，不属于 Extension Protocol v2 稳定承诺。

更新时间：2026-08-28

## 目标

在不让 TraceCite 变成自治 Agent、代码搜索器或 Observability 存储平台的前提下，把 runtime evidence 转换成一个可关联、可探索、可压缩、可恢复的 Evidence Space：

1. 通过稳定实体标识建立证据图；
2. 对重复 evidence 做确定性 grouping 和 representative selection；
3. 基于 seed、graph distance、severity、entity expansion、citation 与 source diversity 做确定性排序；
4. 在 Agent token budget 下生成显式暴露 omission / Coverage / recovery 的 EvidencePackage；
5. 用跨轮 Evidence / Group / Relation delta 避免重复上下文；
6. 把“发现稳定实体 -> 再取相关证据”的机械循环下沉到 TraceCite Runtime，减少 Agent 的 search/expand 决策轮次；
7. 对已覆盖 range、重复 Evidence、无新增 Evidence、source/frontier exhausted 等状态提供可解释的确定性停止信号。

核心路径：

```text
Provider
  -> Normalize
  -> Correlate
  -> Explore Entity Frontier
  -> Group / Reduce
  -> Evidence Progress / Coverage
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

## Evidence Progress 实验结论

实验分支已经建立 `EvidenceProgressTracker`，并在 scale benchmark adapter 中验证了以下行为：

- 已覆盖 range 的重复 `get` 可以确定性返回 `NO_NEW_EVIDENCE`；
- 不同 query 如果只返回已经见过的 canonical Evidence URI，也可以返回 `NO_NEW_EVIDENCE`；
- duplicate inspect/search 不需要重复向 Agent 回放原始 Evidence；
- 256 个 signal signature 达到容量后，高 severity 新信号可以替换更低 severity retained signal，保持 bounded 的同时降低关键异常被噪声挤掉的风险；
- progress/coverage/no-growth 信号可以明显减少重复 evidence transport。

**重要边界：这些 semantics 目前在 benchmark `ScaleRuntime` 中验证得最完整，还没有全部下沉到 canonical `src/tracecite/runtime/tools.py` / investigation path。** 后续产品化工作的重点是让正式 API 获得同样的行为，而不是继续只增强 benchmark adapter。

## 边界

- `EntityRef` / `EvidenceRelation` 只描述事实身份与关系，不表达根因。
- Correlation 不生成 Finding；temporal relation 永远是 `< 1.0` confidence 的启发式弱关系，不能冒充 exact entity relation。
- Orchestrator 不产生 Hypothesis / Finding，不使用 LLM planner。
- Provider 不嵌入领域结论；具体 Bugly/Sentry/Datadog/OTel 适配应只负责取证和标准化。
- Reducer 不使用 LLM，不修改 canonical evidence。
- EvidencePackage 是 Agent-facing projection；省 token 不能隐藏 Coverage 缺口。
- Canonical evidence / URI 必须可恢复；Agent projection 可以压缩，但不能破坏 provenance。
- 原有 `EvidenceLedger` / `ContextEngine` 暂不删除。实验验证通过后再设计兼容迁移，而不是直接替换。
- TraceCite 的目标不是让单次搜索永远比 `rg` 更小或更快，而是控制完整 investigation 中的 Evidence flow、重复上下文和 provenance。

## 当前可执行验证

组件级验证包含：

- multi-source `crash -> session -> request -> trace -> callback` 自动探索；
- 噪声 session 不进入目标 Evidence Graph；
- Provider error / retrieval budget 会返回 incomplete/partial；
- namespace 可防止相同 ID 在不同系统间被错误 exact join；
- 10,000 个同实体 Evidence 使用 star correlation，relation 数量保持 O(n)，Grouping 收敛为代表集合；
- EvidencePackage URI 可重新 resolve 到原 Provider record；
- synthetic structural benchmark 比较“Agent 自己逐轮跟实体”与“一次 investigate 调用”的结构性 loop 数；
- scale host 对 range coverage、cross-query novelty、failure classification、severity-aware retention 的 deterministic tests。

组件级测试证明实现正确性、boundedness、结构性 Agent-loop 下沉和组件级 Evidence retention；真实 token / diagnosis 结论必须来自真实模型 Agent Host benchmark。

## Model-level benchmark

外部 Agent Host runner 支持：

1. `shell_rg`
2. `free_shell`
3. `tracecite`
4. `tracecite_context`
5. `tracecite_intelligence`
6. `tracecite_investigate`

`free_shell` 是当前更强的现实 baseline：Agent 可以自由选择只读本地工具（如 `rg`、`cat`、`sed`、`head`、`tail` 等），用来回答“聪明 Agent + shell/rg 是否已经足够”的问题。

`tracecite_intelligence` 用于隔离“关联/分组/压缩”的价值；`tracecite_investigate` 用于额外测量“自动 Entity exploration 是否真正减少 Agent/model loop”。详细公平性和指标见 `benchmarks/agent-investigation/EVIDENCE_INTELLIGENCE_MODES.md`。

### 2026-08-28 已验证规模结果

当前真实模型使用 `MiniMaxAI/MiniMax-M3`（GMI OpenAI-compatible endpoint）。

TraceBench HDFS_v3 corruption case 使用真实故障记录，并混入同一公开数据集中的真实 normal records 作为 deterministic background noise；不是手写 synthetic fault。

正式 scale gate 当前结论：

```text
25KB TraceCite  -> PASS
5MB TraceCite   -> PASS
50MB TraceCite  -> PASS
```

50MB TraceCite：

- required concepts：6/6；
- evidence markers：3/3；
- model-visible tool output：约 88.5K chars；
- provider-reported cumulative input tokens：375,211；
- cached input tokens：335,852；
- output tokens：4,908；
- model calls：17；
- tool calls：34。

同一 50MB evidence 下，`free_shell` baseline 在一次约 5.2M chars 的工具输出之后，下一轮模型请求触发 `context_window_exceeded`。

因此当前规模实验支持的是：

> TraceCite 能把大规模真实 runtime evidence 转换成 bounded、可引用、可恢复的 Evidence flow，降低自由 shell Agent 因低选择性原始输出把模型上下文打爆的风险。

这不是“TraceCite 搜索一定比 rg 快/小”的结论，也不能把某一个 case 的 token 比例宣传成固定节省率。

## Scale 验证边界

**当前项目决定把 50MB 作为本阶段最大必测规模。**

100MB、500MB 或更大的模型级 benchmark 不再是当前验收项。已经存在的更大 workflow 可以保留为可选 stress tooling，但不需要继续运行，也不应阻塞产品化或 merge 决策。

后续优先级从“继续放大文件”切换为：

1. 把 benchmark 已验证的 Evidence Progress / coverage / novelty hard-stop 下沉到 canonical runtime；
2. 统一 `NO_NEW_EVIDENCE`、`SOURCE_EXHAUSTED`、`FRONTIER_EXHAUSTED` 的正式 API 语义；
3. 完善 scanned bytes、unique evidence growth、repeated evidence ratio、source coverage、wall time、peak memory、attempted context load 等指标；
4. 扩大真实 root-cause case 的领域覆盖，并用 maintainer diagnosis / merged fix 作为独立 truth。

## Token 指标解释

模型级 benchmark 同时记录两类不同指标：

- `reported_input_tokens` / `reported_output_tokens` / cached-token 字段：模型 provider 对每次成功请求真实返回的 usage，跨 Agent 轮次累加；
- `tool_output_chars` 与 `chars / 4`：模型可见工具证据大小及其粗略 token 估计，后者不是 tokenizer 精确值。

多轮 Agent 的 cumulative input 会重复包含历史上下文，因此不能把 cumulative input tokens 直接理解为“原始文件被压缩后的唯一 evidence token 数”。

同样，如果一个 baseline 在把超大 tool output 放入下一轮时直接 context overflow，该失败请求可能没有 provider usage；因此不能只看成功请求的 `reported_input_tokens` 判断它更省。

## 合并验收

规模层面的 25KB / 5MB / 50MB 已经给出正向证据，但**目前还不应仅凭 scale benchmark 直接合并全部实验 API**。

合并回 `refactor/agent-v2` 前仍应完成或明确收敛：

- canonical runtime 获得 progress / coverage / novelty hard-stop，而不是只存在于 benchmark host；
- evidence recall 与 citation recovery 保持不下降；
- real root-cause suite 扩展到多个独立项目/领域；
- evaluator 能检查 unsupported claims、citation 与 fix alignment；
- wall time、扫描量、重复 evidence、内存等资源成本不会抵消上下文收益；
- 对外 Runtime/Integration contract 收敛，避免 benchmark-only 行为与产品行为长期分叉。

如果这些条件成立，再把实验 API 收敛为正式 Runtime/Integration contract，并开始合并新旧 Ledger/Context 路径。
