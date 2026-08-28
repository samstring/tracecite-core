# Evidence Intelligence 实验

状态：实验性；仅用于 `experiment/evidence-intelligence` 分支验证，不属于 Extension Protocol v2 稳定承诺。

更新时间：2026-08-28

## 目标

在不让 TraceCite 变成自治 Agent、代码搜索器或 Observability 存储平台的前提下，把 runtime evidence 转换成一个可关联、可探索、可压缩、可恢复、可确定性停止的 Evidence Space。

当前目标包括：

1. 通过稳定、版本化 identity 建立 Evidence provenance 与关系；
2. 对重复 evidence 做确定性 grouping / representative selection；
3. 基于 seed、graph distance、severity、entity expansion、citation 与 source diversity 做确定性排序；
4. 在 Agent token budget 下生成显式暴露 omission / Coverage / recovery 的 EvidencePackage；
5. 用跨轮 Evidence delta 避免重复上下文；
6. 把“发现稳定实体 -> 再取相关证据”的机械循环下沉到 TraceCite Runtime；
7. 对已覆盖 range、重复 Evidence、无新增 Evidence、source/frontier exhausted 等状态提供可解释的机械停止信号；
8. 让 Mobile / MCP / 第三方通过 Provider / Capability / Projection 扩展，而不是不断增加 Core 顶层 API。

核心路径：

```text
Provider / Source
  -> Normalize
  -> Versioned Evidence Identity
  -> Correlate
  -> Explore Entity Frontier
  -> Group / Reduce
  -> Evidence Progress / Coverage
  -> Token-aware Projection
  -> Agent reasoning
```

## 产品边界

TraceCite 负责：

- Evidence identity / version identity；
- provenance / citation / recovery；
- deterministic retrieval；
- correlation；
- grouping / reduction；
- coverage；
- novelty；
- progress；
- bounded frontier exploration；
- mechanical stop reason。

TraceCite 不负责：

- LLM hypothesis generation；
- root-cause ranking；
- causal conclusion；
- 通用代码搜索体验；
- 通用 Git/CI/issue navigation；
- observability backend 存储。

可以通过 EvidenceProvider 摄取 Git、CI、issue、crash、trace、metric 等与 incident 相关的事实；“可以摄取某领域 Evidence”不等于 TraceCite 成为该领域的通用产品。

## Canonical Agent API 方向

实验分支开始把长期 public surface 收敛到较少入口：

```text
Runtime:
  retrieve(request)
  investigate(...)
  verify(...)
  list_capabilities()

Integration transport:
  project(result, profile=...)
```

原有 `probe/search/expand/sample/survey/...` 继续作为兼容/便利 API 保留，不要求上层把每个内部操作长期映射成独立 RPC 或 MCP tool。

### retrieve()

`retrieve()` 使用统一 `EvidenceRequest`，当前 typed target 包括：

```text
SourceTarget
QueryTarget
RangeTarget
ProviderTarget
```

Runtime 内部仍可以调用不同执行器，但上层只需要处理统一的 retrieval result / progress / stop contract。

### Provider 扩展

新增 Bugly / Sentry / OTel / CI / 自研平台时，优先实现已有：

```text
EvidenceProvider.can_handle(request)
EvidenceProvider.retrieve(request)
```

而不是给 Core 增加 provider-specific 顶层函数。

Provider 只取事实，不进行 Agent reasoning。

### investigate()

Runtime-level `investigate()` 执行：

```text
seed
 -> retrieve
 -> discover EntityRef
 -> retrieve related evidence
 -> correlate
 -> group
 -> reduce
 -> progress / coverage
 -> stop
```

它不产生 root-cause conclusion。

### project()

Canonical Runtime result 保留完整 provenance / recovery。

Integration 提供统一 projection：

- `full`：完整 detached view；
- `agent`：保守的 Agent-facing compact view；
- custom callable：允许上层自由定义自己的 projection，而不用修改 Core。

## Evidence Identity

实验分支正式区分三层 identity：

```text
record identity
!= event identity
!= group identity
```

### Record identity

一个具体 provider/source record 的可追溯 identity，拥有 provenance。

### Event identity

多个 record 可关联到同一真实事件；event identity 用于 correlation，不能覆盖各 record 的 provenance。

### Group identity

Grouping/Reducer 的投影 identity，只用于压缩或 representative selection，不能代替 record/source identity。

## Source Version

新增 domain-neutral `SourceVersion`：

```text
sha256
cursor
generation
mutable
```

对 immutable file/snapshot：

```text
source path + sha256
```

形成版本化 source identity。

对 live/remote provider，可使用 cursor / generation 表达其稳定版本边界。

`mutable` 明确表示不能仅靠历史 path coverage 做 zero-read hard stop。

## Evidence Progress

Evidence Progress 是 Runtime 的一等机械概念，但不是第二套持久化数据库。

现有：

- `EvidenceRequirement`；
- `EvidenceGap`；
- `EvidenceDelta`；
- `EvidenceReadiness`；
- `EvidenceProgressTracker`。

当前还增加：

```text
CoverageStatus:
  unknown | partial | complete | stale

ReadinessStatus:
  unknown | insufficient | partial | ready
```

Progress 可以从 `InvestigationState.executions` 中的 Evidence URI、source SHA、line range、coverage 等机械历史重建。

`restore()` 重建历史时不会把旧 evidence 误算成本轮 no-growth。

## Stop 语义

StopReason 只描述 Evidence acquisition，不描述诊断结论。

### no_new_evidence

本次 retrieval 没有产生此前未见的 canonical Evidence。

不等于 investigation complete。

### source_exhausted

当前 source 在当前 investigation scope / requirement 下没有 Runtime 可机械发现的新增 Evidence。

不等于物理文件全部返回给 Agent。

### frontier_exhausted

当前所有已知、允许确定性展开的 Entity / relation frontier 已处理完成。

不等于 root cause found。

### 其他机械状态

```text
budget_exhausted
provider_unavailable
source_changed
```

StopReason 带 `kind / scope / basis`，用于解释和测试 stop 的机械依据。

## Canonical Runtime 已验证行为

当前 `retrieve()` 已覆盖：

- linked investigation history 重建；
- repeated QueryTarget Evidence 的 novelty projection；
- canonical result 继续保留完整 repeated Evidence，Agent-facing projection 可以不重复发送；
- immutable RangeTarget 在 source version 相同且 context range 已覆盖时 deterministic hard-stop；
- source 内容变化时旧 SHA 不能触发错误 hard-stop；
- ProviderTarget 允许自定义 EvidenceProvider 进入统一 retrieve surface。

Runtime-level `investigate()` 已能把 deterministic frontier stop 映射到 formal progress / stop projection。

## Capability Registry

复用已有：

```text
CapabilitySpec
register_capability
list_capabilities
execute_capability
```

不增加第二套 capability registry。

长期目标是让 Mobile / MCP 动态发现能力，并通过少量稳定入口执行，而不是每增加一个 Core feature 就新增上层专用 API。

## 规模验证结论

正式 scale gate 截止 50MB：

```text
25KB -> PASS
5MB  -> PASS
50MB -> PASS
```

50MB TraceCite 保持 required concept / evidence marker 全通过，且模型可见 tool output 保持 bounded；相同 Evidence 的 free-shell baseline 曾因约 5.2M chars 低选择性工具输出导致下一轮 `context_window_exceeded`。

100MB / 500MB / 1GB+ 不再作为当前 merge / 产品价值判断的必测条件。继续放大同一 HDFS case 的新增决策信息低于多领域真实 root-cause 验证。

## 合并验收

最终合并回 `refactor/agent-v2` 前，建议至少满足：

- canonical Runtime API / Progress / Stop / Identity tests green；
- Core Python 3.10–3.14 Linux/macOS matrix green；
- Evidence Intelligence Benchmark green；
- 如 transport 语义发生变化，回归 25KB / 5MB / 50MB；
- evidence recall 不下降；
- answer correctness 不下降；
- citation 可恢复且准确；
- 至少 4–5 个不同领域真实 root-cause case 提供独立 truth；
- Mobile/MCP 可以依赖 Provider/Capability/Projection contract，而不是 benchmark-only 逻辑。

真实 root-cause case 应尽量满足：

```text
real incident
+ runtime evidence
+ maintainer diagnosis
+ merged PR / fix commit
```

Agent 看不到 evaluator truth。

## 当前下一主线

Canonical Runtime contract 完全收绿之后：

```text
metrics 完善
-> 多领域 real root-cause suite
-> merge decision
-> Mobile / MCP 稳定 contract 迁移
```

不再以更大的单一日志规模作为主线。
