# Evidence Intelligence 工作进度与交接

> 本文档是 `experiment/evidence-intelligence` 分支当前工作的权威交接记录。目标是记录已经确认的产品价值、长期 API 决策、已经实现的代码、测试事实、仍未完成的验收工作。旧聊天和旧进度文件仅作为历史，不应覆盖本文档中的较新决策。

更新时间：2026-08-28

## 1. 当前工作基线

- 仓库：`samstring/tracecite-core`
- 当前工作分支：`experiment/evidence-intelligence`
- 基础分支：`refactor/agent-v2`
- Evidence Intelligence 的实验继续只在实验分支开发；在 API/真实案例验收前不直接合并到基础分支。
- 规模模型级验收正式截止 **50MB**；100MB / 500MB / 1GB+ 不再属于本阶段必测范围。

当前工作的判断标准已经从“继续放大日志”转为：

1. benchmark 中验证有效的 Evidence Progress / coverage / novelty / stop 机制能否进入 canonical Runtime；
2. 上层是否可以用很少代码接入自己的 Provider / projection / capability；
3. public contract 是否足够小，使 Mobile / MCP / 第三方以后不需要随着 Core 内部实现变化频繁修改；
4. 多领域真实 root-cause case 是否继续支持 TraceCite 的产品价值。

---

## 2. TraceCite 当前价值结论

TraceCite **不是**：

- 通用代码搜索器；
- `rg` / grep 替代品；
- Elasticsearch / Splunk / Observability 存储平台；
- 自治 Agent / LLM planner；
- 自动 root-cause 推理器。

当前实验能够支持的定位是：

> **TraceCite 是面向 AI Agent 的 Evidence Runtime / Evidence Control Plane。**

它负责把 runtime evidence 变成：

```text
bounded
+ provenance-aware
+ versioned identity
+ correlated
+ recoverable
+ coverage-aware
+ novelty-aware
+ explainable progress
+ deterministic stop
```

Agent 继续负责：

```text
hypothesis
causal reasoning
root-cause conclusion
```

因此 TraceCite 的核心价值不是“单次 search 一定比 rg 小”，而是降低完整 investigation 中：

- 重复搜索；
- 重复 range 读取；
- 相同 Evidence 重复进入上下文；
- 机械 entity expansion 消耗模型轮次；
- 一次性把巨量低选择性原始 evidence 倾倒进 context 的风险。

### 已有真实模型证据

MiniMax M3 / GMI 上：

```text
25KB -> PASS
5MB  -> PASS
50MB -> PASS
```

50MB TraceCite：

- required concepts：6/6；
- evidence markers：3/3；
- model-visible tool output：约 88,545 chars；
- provider cumulative input tokens：375,211；
- cached input tokens：335,852；
- output tokens：4,908；
- model calls：17；
- tool calls：34。

相同 50MB evidence 的 free-shell baseline 在一次约 5.2M chars 的低选择性工具输出之后，下一轮发生：

```text
context_window_exceeded
```

这个结果证明的是 **bounded evidence flow / context economy 的价值**，不能泛化成固定 token 节省百分比，也不能宣称 free-shell 在所有 case 都失败。

---

## 3. 长期 Public API 决策

设计目标：

> **Public API 尽量少；Extension 能力尽量强；internal implementation 可以细分。**

### 3.1 Runtime 主入口

实验分支开始收敛到：

```text
retrieve(request)
investigate(...)
verify(...)
list_capabilities()
```

Integration transport 层提供：

```text
project(result, profile=...)
```

原有：

```text
probe
search
expand
sample
survey
...
```

继续保留兼容和便利使用，但不要求 Mobile / MCP / 第三方把每一个内部操作映射成一个长期稳定的顶层协议。

### 3.2 retrieve() 的扩展方式

`retrieve()` 使用 typed target：

```text
SourceTarget
QueryTarget
RangeTarget
ProviderTarget
```

内部仍可分别调用现有 `probe/search/expand/...`，但上层只需要理解统一 EvidenceRequest / RetrievalResult。

新增数据源时，不增加：

```text
get_bugly_crash()
get_sentry_event()
get_datadog_trace()
get_ci_job()
```

而是实现已有 `EvidenceProvider`：

```text
can_handle(request)
retrieve(request) -> RetrieveResult
```

Provider 只负责取事实；Runtime 负责 evidence management；Agent 负责 reasoning。

### 3.3 investigate() 的严格边界

`investigate()` 可以做所有确定性的机械工作：

```text
seed
-> retrieve
-> discover EntityRef
-> retrieve related evidence
-> correlate
-> group
-> reduce
-> coverage/progress
-> stop
```

它不能做：

```text
LLM hypothesis
root-cause ranking
causal conclusion
```

### 3.4 project() 属于 Integration，不反向污染 Runtime

Canonical result 必须保留完整 Evidence / provenance / recovery。

Integration 现在提供统一 `project()`：

- `profile="full"`：detached canonical view；
- `profile="agent"`：保守 compact Agent view；
- callable profile：Mobile / MCP / 第三方可以自由定义自己的 projection，而不用新增 Core API。

这避免 Runtime 依赖上层，同时减少每个平台重复写压缩/投影逻辑。

### 3.5 Capability Registry 复用现有实现

仓库已经有：

```text
CapabilitySpec
register_capability
list_capabilities
execute_capability
```

因此不再创建第二套 capability 系统。

长期目标是让 MCP / Mobile 根据 Capability Registry 动态发现可用能力，而不是 Core 每增加一项能力，上层就增加一个硬编码 tool / enum / RPC。

---

## 4. Evidence Progress 是 Runtime 一等机械概念

Progress 描述：

> “Evidence acquisition 已经进行到哪里”，而不是“root cause 是否已经找到”。

正式结构继续基于：

- `EvidenceRequirement`；
- `EvidenceGap`；
- `EvidenceDelta`；
- `EvidenceReadiness`；
- `EvidenceProgressTracker`。

新增正式维度：

```text
CoverageStatus:
  unknown | partial | complete | stale

ReadinessStatus:
  unknown | insufficient | partial | ready
```

`ready` 只表示 caller-supplied evidence requirements 在机械 evidence 层已经满足，不表示 Agent 的 root-cause conclusion 为真。

### 4.1 不增加第二套持久化 Progress DB

Progress 优先从 `InvestigationState.executions` 重建：

- operation；
- parameters；
- evidence URI；
- source_path；
- sha256；
- line range；
- coverage。

`EvidenceProgressTracker.restore()` 用于重建历史，而不会因为“恢复旧状态”虚假增加当前 no-growth round。

这样避免：

```text
investigation state
+ progress state
+ ledger state
```

出现第二套互相漂移的持久化 truth。

---

## 5. Stop 状态正式语义

Stop 只描述 **Evidence acquisition**，不能描述诊断结论。

### 5.1 NO_NEW_EVIDENCE

Operation-level：

> 本次 retrieval 没有产生此前未见的 canonical Evidence。

不等于整个 investigation 已结束。

### 5.2 SOURCE_EXHAUSTED

Source/scope-level：

> 在当前 investigation scope / requirement 下，该 source 已没有 Runtime 可机械发现的新增 Evidence。

不等于“物理文件每一行都返回给 Agent”。

必须保留 scope/basis，避免把当前问题的 exhaustion 误解为该 source 对任何未来问题都 exhausted。

### 5.3 FRONTIER_EXHAUSTED

Investigation mechanical-frontier level：

> 所有当前已知、允许确定性展开的 Entity / Evidence relation frontier 已处理完成。

不等于 root cause found。Agent 仍然可以形成新的 semantic hypothesis，再调用 `retrieve(QueryTarget(...))`。

### 5.4 其他机械 Stop

当前 formal StopKind 还包括：

```text
budget_exhausted
provider_unavailable
source_changed
```

所有 StopReason 支持：

```text
kind
scope
basis
```

从而让 stop 可解释、可测试，而不是裸 `done=true`。

---

## 6. Mutable Source / Versioned Identity 决策

不能因为：

```text
昨天读过 app.log:L100-L200
```

就假定今天相同 path 的 L100-L200 仍然 covered。

新增 `SourceVersion`：

```text
sha256      -> immutable file/snapshot
cursor      -> bounded live/remote cursor
 generation -> provider generation/version
mutable     -> explicitly mutable source
```

只有可以证明 version identity 没变时，历史 range coverage 才能用于零内容读取 hard stop。

对于文件路径：

```text
source path + SHA256
```

构成 versioned source identity。

`RangeTarget(expected_sha256=...)` 会先验证 immutable identity；相同版本且 context range 已被历史 execution 完整覆盖时，才允许直接返回 `NO_NEW_EVIDENCE`。

没有 immutable identity 时，必须保守重新读取/验证，不能凭 path 历史直接 hard-stop。

---

## 7. Evidence Identity 分层

正式区分：

```text
record identity
!= event identity
!= group identity
```

### Record identity

表示一个 Provider/source 中可追溯的具体 evidence record，拥有 provenance。

### Event identity

允许多个 record 表达同一个真实世界事件，用于 correlation；它不能替换各自 provenance。

### Group identity

Reducer/grouping 的投影 identity，只用于压缩/代表集合，不能替代 record identity 或 source identity。

新增 `EvidenceIdentity` / `SourceVersion` 就是为了把这三个概念从字符串 fingerprint 中拆开。

---

## 8. 已落地代码

本轮 canonical runtime 实现新增/修改：

### `src/tracecite/runtime/evidence_progress.py`

- formal `StopReason`；
- `CoverageStatus`；
- `ReadinessStatus`；
- `StopKind`；
- tracker history restore；
- seen Evidence identity 查询；
- formal progress projection。

### `src/tracecite/runtime/evidence_identity.py`

新增：

- `SourceVersion`；
- `EvidenceIdentity`；
- immutable/mutable source semantics；
- versioned file source key；
- persisted EvidencePointer -> source version key。

### `src/tracecite/runtime/agent_api.py`

新增 canonical Agent-facing Runtime surface：

- `EvidenceRequest`；
- `RetrievalResult`；
- `SourceTarget`；
- `QueryTarget`；
- `RangeTarget`；
- `ProviderTarget`；
- `retrieve()`；
- Runtime-level deterministic `investigate()`；
- `CanonicalInvestigationResult`。

关键行为：

- 从 InvestigationState executions 重建 seen Evidence；
- QueryTarget 返回全部旧 Evidence 时，Agent projection 返回 `NO_NEW_EVIDENCE`；
- canonical result 仍保留完整结果，不因 projection 去重而破坏 recovery；
- RangeTarget 只有在 immutable SHA identity 被证明相同且 range 已覆盖时才 hard-stop；
- ProviderTarget 允许上层增加自己的 EvidenceProvider，而不增加新的顶层 API。

### `src/tracecite/integrations/agent_projection.py`

新增统一 `project()`：

- built-in agent/full projection；
- custom callable projection；
- canonical Runtime 与 upper-layer transport 分层。

### 兼容性

旧工具 API 没有删除：

```text
probe/search/expand/sample/survey/verify/...
```

所以当前改动是 additive canonical layer，不是一次性破坏已有 CLI/Mobile/MCP 的强制迁移。

---

## 9. 当前测试状态

新增 `tests/test_runtime_agent_api.py`，覆盖：

- record/event/group identity 分层；
- mutable SourceVersion；
- progress history restore 不制造假 no-growth；
- formal `NO_NEW_EVIDENCE`；
- linked investigation 下重复 QueryTarget 的 Agent projection 去重；
- canonical result 仍保留完整 repeated Evidence；
- immutable range coverage hard-stop；
- source 内容改变后旧 SHA 不能误 hard-stop；
- custom Provider 可以通过 ProviderTarget 接入，而无需增加顶层 API；
- deterministic investigate 暴露 frontier stop。

`tests/test_agent_projection.py` 也新增：

- `project(profile="full")` detached canonical view；
- custom callable projection。

第一轮 Core CI 共收集 412 tests，出现 2 个新增测试失败，根因是测试 fixture 把已有 `EntityRef.value` 错写成 `id`；不是产品 contract 回归。该 fixture 已修正。

Evidence Intelligence Benchmark 在这轮改动期间持续保持 green。

> 最终 Core CI 是否 green，以本文档之后最新 Actions 结果为准；交接时必须确认，不得只根据这一段文字假定成功。

---

## 10. 产品边界正式决定

允许 EvidenceProvider 接入：

- File/log；
- Bugly / Sentry / crash platform；
- OpenTelemetry / trace；
- metrics；
- CI / build evidence；
- GitHub issue/PR/commit 中与 incident 相关的 evidence；
- 自研平台。

但 TraceCite 不承担：

- 通用 repo navigation；
- 通用代码搜索体验；
- issue tracker / CI 存储；
- observability backend；
- Agent hypothesis / root-cause reasoning。

原则是：

> **可以摄取某个领域的证据，但不成为那个领域的通用搜索/存储产品。**

---

## 11. Mobile / MCP 长期方向

上层尽量依赖：

```text
retrieve
investigate
verify
project
list_capabilities / execute_capability
```

而不是把所有 Runtime internal operation 一对一变成永久 RPC/tool。

目标：

```text
Core 新增 Provider / capability
        ↓
Capability Registry 动态发现
        ↓
Mobile / MCP 尽量无需新增专用代码
```

具体 Mobile/MCP 迁移应在 canonical Runtime API 通过当前分支验收后执行，避免上层过早绑定仍在实验中的实现。

---

## 12. 合并回 `refactor/agent-v2` 的建议门槛

不再要求 100MB / 500MB。

建议至少满足：

1. canonical Runtime API / progress / stop / identity tests 全绿；
2. Core CI 全矩阵 green；
3. Evidence Intelligence Benchmark green；
4. 如 evidence transport 行为有变化，回归 25KB / 5MB / 50MB；
5. 至少覆盖 4–5 个不同领域的真实 root-cause case，而不是大量同类 case；
6. 真实 case 必须有独立 truth，例如 maintainer diagnosis + merged PR/fix commit；
7. correctness / evidence recall / citation 不因 token/context 优化下降；
8. API contract 能让 Mobile/MCP 通过 Provider/Capability/Projection 扩展，不依赖 benchmark-only 逻辑。

建议真实领域至少包含：

- Kubernetes；
- Flutter / iOS / Mobile crash；
- Prometheus；
- Pulumi 或其他 backend/runtime incident；
- 另一个独立项目。

---

## 13. 仍未完成的工作

### P0：完成 canonical Runtime 验证

- 等待/检查最新 Core CI；
- 修复任何真实 regression；
- 确保 Python 3.10–3.14 + macOS/Linux matrix 全绿；
- 确认 Evidence Intelligence Benchmark 持续 green。

### P0：多领域真实 root-cause suite

每个 case 尽量满足：

```text
real incident
+ runtime evidence
+ maintainer diagnosis
+ merged PR / fix commit
```

Evaluator 独立持有 truth；Agent 不看到答案。

评分至少包含：

- failure localization；
- immediate failure mechanism；
- upstream contributor；
- evidence support；
- unsupported / contradiction；
- citation accuracy；
- fix alignment。

### P1：Benchmark 指标补全

还建议正式报告：

- scanned bytes；
- unique evidence growth；
- repeated evidence ratio；
- source coverage；
- wall time；
- peak RSS；
- attempted context load。

### P1：benchmark/product 边界继续变薄

- benchmark-specific cap audit；
- baseline helper whole-file read audit；
- 尽量让 benchmark host 只调用正式 Runtime API；
- benchmark adapter 不长期持有一套比产品更聪明的 Evidence Progress 逻辑。

### P1：小型 harness 鲁棒性

- 对模型轻微超出 bounded radius 的请求做 clamp/明确 normalization，避免浪费模型轮次；
- provider failure taxonomy 保持统一。

---

## 14. 后续执行顺序

```text
1. 当前 canonical Runtime CI 收敛
        ↓
2. 补必要的 API/文档回归
        ↓
3. 如 transport 语义变化，回归 25KB / 5MB / 50MB
        ↓
4. 补 benchmark metrics
        ↓
5. 多领域 real root-cause suite
        ↓
6. merge decision
        ↓
7. 再同步 Mobile / MCP 到稳定 contract
```

明确不要再回到：

```text
100MB -> 500MB -> 1GB
```

作为当前主线。

---

## 15. 当前关键文件

```text
src/tracecite/runtime/agent_api.py
src/tracecite/runtime/evidence_progress.py
src/tracecite/runtime/evidence_identity.py
src/tracecite/runtime/investigation.py
src/tracecite/runtime/tools.py
src/tracecite/runtime/capabilities.py
src/tracecite/extension/retrieval.py
src/tracecite/integrations/agent_projection.py
src/tracecite/runtime/orchestrator.py

tests/test_runtime_agent_api.py
tests/test_agent_projection.py

benchmarks/agent-investigation/gmi_scale_host.py
benchmarks/agent-investigation/SCALE_BENCHMARK.md
benchmarks/agent-investigation/README.md
```

---

## 16. 当前一句话状态

**TraceCite 的 Evidence Intelligence 已从 benchmark-only 机制开始下沉到 canonical Runtime：public direction 收敛为小型 `retrieve / investigate / verify / project / capabilities` contract，Progress/Stop 和 versioned Evidence Identity 已成为显式机械概念，Provider/Projection 允许上层自由扩展而无需不断增加 Core API；规模验证已在 50MB 闭环，当前剩余主线是把新 Runtime API 的 CI 完全收绿，然后进入多领域真实 root-cause 验证与最终 merge 决策。**
