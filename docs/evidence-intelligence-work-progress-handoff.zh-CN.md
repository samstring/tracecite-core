# Evidence Intelligence 工作进度与交接

> 本文档用于记录 `experiment/evidence-intelligence` 分支当前工作状态、已验证事实、未完成事项、风险点与后续执行顺序，便于中断后继续开发，或交接给新的 Agent / 开发者继续执行。

更新时间：2026-08-28

## 1. 当前工作基线

- 仓库：`samstring/tracecite-core`
- 当前工作分支：`experiment/evidence-intelligence`
- 基础分支：`refactor/agent-v2`
- 本阶段只在实验分支继续，不直接修改 `main` / `refactor/agent-v2`。
- 本次文档刷新前最后一个代码/CI 基线 HEAD：`77dbbdf0426393e5990fde3d7c07807c9429cdc6`（`ci(bench): add candidate-first 100mb evidence gate`）。
- 该 100MB workflow 已经不再属于当前验收计划；项目决策从 2026-08-28 起把 **50MB 作为本阶段最大必测规模**。

实验最终是否合并回稳定分支，不再取决于继续放大到 100MB / 500MB，而取决于：

1. benchmark 已证明有效的 progress/coverage/novelty 语义能否进入 canonical runtime；
2. token/context 优势是否在不牺牲 evidence recall、correctness、citation 的前提下成立；
3. 多领域真实 root-cause case 是否能验证产品价值；
4. runtime API 是否能够长期稳定，避免 benchmark adapter 与正式产品逻辑分叉。

## 2. 当前目标

TraceCite 的实验方向仍然是：

```text
Collect
→ Normalize
→ Correlate
→ Explore / Inspect
→ Group / Reduce
→ Evidence Progress / Coverage
→ Cite / Recover
→ Agent Reasoning
```

重点不是做通用代码搜索，也不是证明单次搜索一定比 `rg` 更快或更小，而是：

> 把真实运行时信号整理成紧凑、相关联、可追溯、可引用、可确定性停止的 Agent Evidence，降低完整 investigation 中的重复工具调用与上下文浪费。

TraceCite Runtime 负责机械证据状态、identity、coverage、novelty、关联、压缩与 retrieval progress；Agent 负责因果推理与最终诊断。

## 3. 已完成工作

### 3.1 Evidence Intelligence 主体实验能力

实验分支已经具备：

- `EvidenceProvider`；
- Evidence Graph / correlation；
- Grouping / Reducer；
- token-aware `EvidencePackage`；
- Context Delta；
- deterministic Entity exploration；
- bounded `ExplorationPolicy`；
- canonical Evidence URI / recovery；
- namespace 隔离；
- Evidence Progress state / tracker。

组件级测试已经覆盖 boundedness、evidence retention、URI recovery、namespace 隔离、结构性 Agent-loop 下沉等能力。

### 3.2 Evidence Progress benchmark 接线

`benchmarks/agent-investigation/gmi_scale_host.py` 已经把 per-file `EvidenceProgressTracker` 接入 scale benchmark 的 `inspect/get/search` 路径，并验证：

- duplicate inspect 返回 bounded `NO_NEW_EVIDENCE`；
- `get` 按历史 coverage union 判断，而不是只判断 exact tuple；
- 请求范围被多个历史 range 联合完整覆盖时可 hard-stop；
- `search` exact duplicate 可 hard-stop；
- 不同 query 如果 canonical Evidence URI 全部已见，也可返回 `NO_NEW_EVIDENCE`；
- canonical search result 进入 Evidence Ledger；
- severity-aware retention 保持容量 bounded，并允许高严重度新信号替换低严重度旧信号；
- progress line 暴露 evidence growth / coverage / readiness。

### 3.3 failure taxonomy / candidate-first benchmark

scale host / workflow 已开始区分：

- `context_window_exceeded`；
- `tool_timeout`；
- provider quota / insufficient balance；
- provider rate limit；
- provider unavailable；
- generic host error。

paired benchmark 已改为 **TraceCite candidate first，baseline 后跑**，避免 free-shell 先消耗 provider quota / rate limit 后污染候选结果。

判定原则：

- TraceCite quality/context/timeout failure：candidate failure；
- TraceCite provider infra failure：inconclusive；
- free-shell context/tool/provider failure：保留为 baseline comparison evidence，不阻断已经通过的 TraceCite candidate。

### 3.4 50MB workflow streaming

50MB fixture validation / checksum 已改为 streaming 处理，避免不必要的 whole-file `read_text()` / `read_bytes()`。

当前 50MB workflow 已能明确记录 host failure reason，而不是只留下 generic stage。

### 3.5 Core / Evidence CI

本轮主要修改后的 Core CI 与 Evidence Intelligence Benchmark 均已重新跑过并保持 green。

50MB candidate-first workflow 对应 commit `535b942b88bbb5e5cbb781b71620d7892d0634f4` 也已成功完成。

## 4. 当前真实模型 / scale benchmark 结果

当前真实模型配置：

```text
provider: GMI OpenAI-compatible endpoint
model: MiniMaxAI/MiniMax-M3
```

MiniMax M3 smoke 已真实完成多轮模型调用并通过，不再出现旧 provider 的 immediate 402 状态。

### 4.1 25KB

TraceCite candidate：PASS。

- required concepts：6/6；
- evidence markers：3/3；
- 本轮 M3 candidate-first 结果中，TraceCite reported input / model loops / tool output 均处于可控范围；
- 小文件结论不能泛化成固定 token 节省率。

### 4.2 5MB

TraceCite candidate：PASS。

- required concepts：6/6；
- evidence markers：3/3；
- progress/no-growth 已开始抑制重复 Evidence 回放；
- 仍观察到模型主动换 query / get 方式继续探索，说明“证据传输去重”已经改善，但“Agent 自己何时停止”仍有优化空间。

### 4.3 50MB

TraceCite candidate：PASS。

- required concepts：6/6；
- evidence markers：3/3；
- model-visible tool output：约 `88,545` chars；
- provider-reported cumulative input tokens：`375,211`；
- cached input tokens：`335,852`；
- output tokens：`4,908`；
- model calls：`17`；
- tool calls：`34`。

同一 50MB evidence 下，free-shell baseline 在一次约 `5.2M chars` 的工具输出之后，下一轮 provider 请求触发：

```text
context_window_exceeded
```

这次失败不是 shell 命令本身超时，而是低选择性的原始证据输出把下一轮模型上下文打爆。

### 4.4 当前可支持的产品价值结论

现有证据支持：

> TraceCite 的主要价值不是“搜索比 rg 快”，而是把大规模 runtime evidence 变成 bounded、provenance-aware、可恢复、可逐步扩展的 Evidence flow，降低 Agent 因重复搜索或一次性倾倒大量原始日志而浪费 context 的风险。

不能宣称：

- TraceCite 每次 search 都比 `rg` 小；
- TraceCite 固定节省某个百分比 token；
- free-shell 在所有 case 都会 context overflow；
- 50MB 单一 HDFS case 已经证明所有真实 debugging 领域都有效。

## 5. Token / context 统计口径

必须区分：

### Provider-reported usage

每次成功模型请求返回的：

- input tokens；
- output tokens；
- cached input tokens（如 provider 支持）；

会跨 Agent 轮次累加。

多轮累计 input 会重复包含历史 conversation context，因此它表示“整个 investigation 生命周期累计被模型处理的 input”，不是“原始文件唯一 evidence 的压缩后 token 数”。

### Tool evidence size

另外记录：

- `tool_output_chars`；
- `unique_tool_output_chars`；
- `chars / 4` 的 clearly-labelled rough token estimate。

`chars / 4` 不是精确 tokenizer 结果。

如果一个 baseline 在把巨大 tool output 放入下一轮时直接 context overflow，该失败请求可能没有 provider usage，因此不能只比较成功请求的 `reported_input_tokens`。

## 6. Scale 测试范围决策

**从现在开始，本阶段正式 scale gate 截止 50MB。**

不再要求：

```text
100MB
500MB
1GB+
```

作为 merge / 产品价值判断条件。

原因：

1. 25KB / 5MB / 50MB 已经覆盖从小文件 overhead 到明显大上下文压力的三个不同区间；
2. 50MB 已经出现 free-shell context overflow、TraceCite 保持 bounded 且质量通过的直接对照；
3. 继续把同一种 HDFS evidence 放大到更大尺寸，新增产品决策信息有限；
4. 当前更有价值的工作是 canonical runtime 下沉和多领域真实 root-cause 验证。

已有 100MB workflow 可以保留为可选 stress 工具，但不需要继续运行，其结果也不属于当前验收依据。

## 7. 当前未完成事项

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| EvidenceProgress 数据结构 / tracker | ✅ 完成 | runtime 已有 |
| benchmark `inspect/get/search` Progress 接线 | ✅ 基本完成 | scale host 已验证 |
| coverage-aware duplicate `get` | ✅ benchmark 完成 | 需下沉 canonical runtime |
| novelty-aware duplicate `search` | ✅ benchmark 完成 | 需下沉 canonical runtime |
| severity-aware signal retention | ✅ benchmark 完成 | 仍需产品 reducer/sample 路径回归 |
| failure taxonomy / candidate-first | ✅ 基本完成 | 已在 scale workflow 使用 |
| 25KB / 5MB / 50MB scale gates | ✅ 完成 | 当前 scale 验收闭环结束 |
| 100MB / 500MB scale gate | ⛔ 不再要求 | 已从当前计划移除 |
| canonical runtime Progress wiring | 🟡 未完整完成 | **当前最高优先级** |
| canonical `NO_NEW_EVIDENCE` 语义 | 🟡 未完整完成 | benchmark 已证明，core 需统一 |
| `SOURCE_EXHAUSTED` / `FRONTIER_EXHAUSTED` | 🟡 未完整统一 | 需 API contract 收敛 |
| `investigate()` 用 progress 驱动 exploration stop | 🟡 部分完成 | no-growth/frontier 有基础，但未统一 |
| `get(radius > 8)` bounded clamp | ❌ 未落地 | 避免模型轻微越界浪费一轮 |
| benchmark-specific cap audit | ❌ 未完成 | 区分 benchmark cap 与产品 transport bound |
| baseline whole-file helper 审计 | 🟡 未完整 | 保证公平性，不再以 500MB 为目标 |
| scanned bytes | 🟡 | runtime 有部分预算概念，报告未统一 |
| unique evidence growth | 🟡 | tracker 有数据，最终 report 未完整 |
| repeated evidence ratio | ❌/🟡 | 需要正式指标 |
| source coverage | 🟡 | tracker 有数据，report 未完整 |
| wall time comparison | 🟡 | 有执行时间，未统一形成 publishable metric |
| peak RSS memory | ❌ | 未正式采集 |
| attempted context load | ❌ | 新增建议指标，解决 overflow 前 usage 缺失问题 |
| 多领域真实 root-cause suite | ❌ | **产品价值证明的下一主线** |
| unsupported claim / citation / fix-alignment evaluator | 🟡 | 需要加强 |
| 实验 API 合并决策 | ❌ | 等 canonical runtime + root-cause evidence |

## 8. 当前最高优先级：把验证过的机制下沉到 canonical runtime

benchmark adapter 不是最终产品实现。

重点文件：

```text
src/tracecite/runtime/evidence_progress.py
src/tracecite/runtime/tools.py
src/tracecite/runtime/investigation.py
```

目标：

```text
canonical search
  -> reconstruct / consult seen Evidence identity
  -> exact duplicate can stop before repeated work when safe
  -> result contains only old Evidence
  -> NO_NEW_EVIDENCE

canonical expand/get-like path
  -> coverage-aware
  -> immutable source / expected sha rules respected
  -> fully covered request
  -> NO_NEW_EVIDENCE

canonical investigate
  -> progress + coverage + no-growth + frontier
  -> explainable stop reason
```

### 8.1 不新增第二套持久化 Progress schema

优先利用 linked investigation state 已有的 `executions`：

- operation；
- parameters；
- evidence URI；
- source / source_path；
- SHA256；
- line range；
- coverage 等。

可以从 execution history 机械重建 `EvidenceProgressTracker`，避免再维护一份互相漂移的 progress state 文件。

### 8.2 mutable path 安全边界

对于 expand/get-like hard stop：

- 只有能证明 source identity 没变时，才能在零文件读取情况下依赖历史 coverage；
- `expected_sha256` 等 immutable identity 是安全 hard-stop 的重要条件；
- 对可能变化的普通 path，不能因为历史读取过就武断声明 range 仍然 covered。

## 9. 后续执行顺序

从当前状态继续，建议按以下顺序：

### Step 1：canonical runtime progress / coverage / novelty

先让正式产品 API 获得 benchmark 已验证的行为。

### Step 2：单元测试 + Core CI + Evidence Intelligence Benchmark

每个独立语义都补 deterministic test。

### Step 3：只在行为可能影响 scale 时回归 25KB / 5MB / 50MB

不再继续 100MB+。

### Step 4：完善 investigation-cost metrics

优先加入：

- scanned bytes；
- unique evidence growth；
- repeated evidence ratio；
- source coverage；
- wall time；
- peak memory；
- attempted context load。

### Step 5：扩大真实 root-cause case

优先选择具备：

```text
real incident
+
runtime evidence
+
maintainer diagnosis
+
merged PR / fix commit
```

的公开 case。

Agent 看不到答案，Evaluator 单独持有 root cause / fix mechanism。

评分至少覆盖：

1. failure localization；
2. immediate failure mechanism；
3. upstream contributor；
4. evidence support；
5. contradiction / unsupported claims；
6. citation accuracy；
7. fix alignment。

目标是增加 Kubernetes / Flutter / Prometheus / Pulumi / Mobile crash / backend runtime 等独立领域，而不是继续重复放大同一 HDFS case。

### Step 6：评估是否合并回 `refactor/agent-v2`

只有产品 core 语义、真实 root-cause breadth、资源指标都足够后再做 merge decision。

## 10. 关键文件

```text
src/tracecite/runtime/evidence_progress.py
src/tracecite/runtime/tools.py
src/tracecite/runtime/investigation.py
benchmarks/agent-investigation/gmi_scale_host.py
benchmarks/agent-investigation/SCALE_BENCHMARK.md
benchmarks/agent-investigation/README.md
.github/workflows/evidence-tracebench-first3-real.yml
.github/workflows/evidence-tracebench-50mb-real.yml
tests/test_gmi_scale_evidence_progress.py
tests/test_agent_benchmark_evidence_modes.py
```

相关设计文档：

```text
docs/evidence-intelligence-experiment.zh-CN.md
docs/evidence-intelligence-work-progress-handoff.zh-CN.md
```

## 11. 设计约束

1. **Runtime 做机械事实状态，不做根因推理。**
2. **Evidence identity / coverage / novelty 判断必须确定性。**
3. **`NO_NEW_EVIDENCE` 必须基于可证明的“没有新增证据”，而不是启发式猜测。**
4. **所有 bounded 结构在输入规模增长时仍必须 bounded。**
5. **省 token 不能破坏 provenance、coverage disclosure 与 evidence recovery。**
6. **优先修 core/runtime 语义，再让 benchmark host 变薄，避免逻辑长期分叉。**
7. **baseline 必须真实且足够强，不人为限制到只能输。**
8. **provider infra failure 与产品 failure 分开。**
9. **provider cumulative tokens、tool evidence size、quality、context failure 必须一起解释。**
10. **不再用更大 MB 数量本身作为产品进度。**

## 12. 交接给下一位执行者时的最短启动路径

1. 确认分支仍为 `experiment/evidence-intelligence`；
2. 不要重新从 100MB / 500MB scale 计划开始；正式 scale gate 已在 50MB 结束；
3. 阅读 `src/tracecite/runtime/evidence_progress.py` 与 `src/tracecite/runtime/tools.py`；
4. 检查 benchmark ScaleRuntime 与 canonical runtime 的语义差异；
5. 优先把 coverage-aware get/expand、novelty-aware search、unified stop reason 下沉 core；
6. 补 deterministic tests；
7. 跑 Core CI / Evidence Intelligence；
8. 若行为影响 Agent evidence transport，再回归 25KB / 5MB / 50MB；
9. 然后转向多领域真实 root-cause benchmark。

## 13. 当前一句话状态

**Evidence Intelligence 已经通过 25KB / 5MB / 50MB 的真实模型规模验证，并在 50MB 上观察到 TraceCite 保持 bounded/正确而 free-shell context overflow；规模扩张到此结束，当前真正的工作断点是把已验证的 Evidence Progress / coverage / novelty / stop semantics 下沉到 canonical runtime，并用更多独立真实 root-cause case 验证产品价值。**
