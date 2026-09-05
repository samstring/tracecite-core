# TraceCite vNext — Run10 Shared JSONL Physical Execution

状态：**Open — P0，等待下一轮真实 A/B 验证**

适用范围：TraceCite Agent / MCP / Runtime 的通用 Evidence execution，不针对任何 benchmark case、服务、故障类型、字段名、时间值或隐藏答案。

## 验收门槛

只有真实 A/B 同时满足以下条件后才能关闭：

1. TraceCite model token < Native；
2. TraceCite real elapsed <= Native；
3. TraceCite answer quality >= Native。

不得通过增加 timeout、降低答案质量、预置调查顺序、特殊字段/服务/故障规则或使用 gold answer 达标。

## 1. 问题现象 — A/B run 33967988159

### Native

- Agent elapsed：`274475 ms`；
- exit：`1`；
- final answer：空；
- provider 429：`27`。

该 arm 因连续 provider 429 提前失败，不能将 274.475 秒当成成功 Native 性能基线。当前仍使用此前成功 Native run `33963380099` 的约 `455.3s` 作为有效完成参照之一。

### TraceCite

- Agent elapsed：`600076 ms`；
- exit：`124`；
- final answer：空；
- provider 429：`4`；
- Evidence calls：`93`；
- low-novelty calls：`24`；
- low-novelty ratio：`38.7%`；
- Host 观测到的 TraceCite tool duration 合计约 `551.5s`。

与前一轮相比，旧 discovery / projection / semantic-enrichment 问题已经部分移除，但 Runtime + orchestration 仍未达到目标。

## 2. 根因 A — Run 与 Analyze 使用不同 JSONL physical execution

run10 有四个约 60 秒 `tracecite_run`，其 program 都属于同一通用形态：

```text
where FIELD == VALUE | head N
```

或：

```text
where FIELD == VALUE | sort OTHER_FIELD asc|desc [numeric] | head N
```

它们不是字段或 case 特例。根因是：

```text
tracecite_analyze
  -> raw JSONL shared scan
  -> shared JSON decode
  -> bounded aggregate / Top-K

tracecite_run
  -> _initial_rows
  -> iter_matching_records
  -> JsonLineSegmenter
  -> Record construction
  -> predicate / sort / selection
```

因此同一种机械 predicate / bounded selection 在 Analyze 中可 streaming，在 Run 中仍可能撞 MCP 默认约 60 秒 request timeout。

### 方案比较

1. **只为 run10 的四种 program 增加 fast pattern**：改动小但继续扩大 fast/canonical 分裂，拒绝。
2. **提高 MCP timeout**：掩盖 Runtime cliff，并增加 zombie compute 风险，拒绝。
3. **抽取可由 Run / Analyze 共享的 JSONL physical primitive，并把 bounded selection 下推到 raw-line scan**：正确性可由 canonical parity / no-Record-scan 测试约束，长期可收敛为统一 physical planner。选择该方案。

### 已实施

commit `6c439b393eeb0ba99e2d656dc5cfc08a95bcdd83`：

- 新增 `src/tracecite/runtime/jsonl_physical.py`；
- 新增 `src/tracecite/runtime/evidence_shell_jsonl_selection.py`；
- `tracecite_run` JSONL 支持：
  - `predicates* | head/take/first N`；
  - `predicates* | sort FIELD ... | head/take/first N`；
- unsorted head 命中 N 条立即停止 source scan；
- sorted head 使用固定容量 Top-K；
- 不构造 canonical `Record`；
- SourceVersion、Evidence budget、pointer/session output 仍沿用原契约。

第一次 CI 暴露两项兼容问题而非算法错误：

- 旧测试依赖 `execution_engine=bounded_terminal_topn`；
- 新测试错误地 monkeypatch 全局 `json.loads`，把 SourceVersion/session state JSON 也计入 source decode。

修复：

- `1e43d692391e5ef258362048b36476e03f0fea6a`：保留旧 engine label，新增物理信息放 `physical_plan`；source decoder 使用局部 alias；
- `c641b95416429e86ee17f6c7225e6068ad8d4ebf`：测试只统计 source-line decoder。

Core CI `33969690414`：全矩阵 SUCCESS。

## 3. 根因 B — Analyze Top-K 不是固定容量 heap

旧 Evidence Compute Top-K 的核心行为：

```text
append(candidate)
if candidates > K:
    nsmallest/nlargest(K, candidates)
```

这会在大量匹配行上反复重选 K 个候选，复杂度接近：

```text
O(N * K log K)
```

而正确 bounded Top-K 应为：

```text
O(N log K)
retained candidates <= K
```

run10 中多个已经进入 shared scan 的 Top-K batch 仍耗时约 9–20 秒，两个 mixed aggregate + extrema batch 约 37 秒，这与该算法缺陷一致。

### 方案比较

1. 调小 K：会改变调用者要求/答案质量，拒绝。
2. 针对某些 K 或字段做 shortcut：不通用，拒绝。
3. 提供通用 `FixedCapacityTopK` physical primitive，让 Run / Analyze 共用稳定 bounded accumulator。选择该方案。

### 已实施

`jsonl_physical.FixedCapacityTopK`：

- 最多保留 K 个候选；
- 每行更新 O(log K)；
- equal key 保持 source-order stable semantics；
- asc / desc 使用同一 accumulator；
- 回归在 10,000 次插入过程中每一步都断言 `retained <= K`。

公共 Evidence Compute 增加 transitional physical planner：

- `src/tracecite/runtime/evidence_compute_jsonl_physical.py`；
- `src/tracecite/runtime/evidence_compute_public.py`；
- public `tracecite.runtime.run_evidence_compute` 对全部可编译且包含 Top-K 的 JSONL batch 先使用 fixed-TopK shared scan；
- unsupported shape 仍回现有 planner；
- 这是迁移步骤，长期目标仍是删除重复 planner 并统一到 common IR / physical planner。

主要 commits：

- `fd209fbd016e1b2e6d1834e7b80f9ca5e46dc253`：public fixed-TopK planner；
- `f29cd4bbec9ea0a4e70814e87e692360d24d6cb0`：保留 existing JSON decoder instrumentation seam 和 physical-plan projection；
- `5ffa9e8a0176c8e6723b67b3b59b03d5b6ef87d6`：新回归强制禁止 legacy `_trim_topn`，同时保持旧 output projection。

Core CI `33970021489`：Ubuntu Python 3.10–3.14 + macOS 3.14 全部 SUCCESS。

## 4. 根因 C — Agent 对 Evidence boundary / DSL literal 语义理解不足

run10 暴露两类通用无效 round-trip：

1. task/environment 已明确给出小 Evidence source，但 Agent 尝试 native `cat/read`，被 TraceCite-only boundary 正确阻止后，没有自然转成 TraceCite exact bounded read；
2. Agent 使用类似 `search 'A|B|C'` 的 program，误以为 `search` 支持 regex alternation。TraceCite 的 `search` 是 literal，因此产生 false orientation / additional probes。

不能在 Runtime 中根据 `|` 猜测用户想要 regex，因为会改变 literal search 语义。

### 最终方案

只改通用 Skill 使用契约：

- 显式命名的小 Evidence source，若内容确实需要，通过 `tracecite_run` + bounded selection 读取；
- `search TEXT` 明确为 literal；需要 alternation / character class / anchors / repetition 时使用 `regex PATTERN`；
- 不规定任何具体文件、字段、服务、时间窗口、故障或调查顺序。

TraceCite MCP commits：

- `ca49b1ab653336572186751f22bc5110dc0b21be`：Skill contract；
- `913a3c16cd6ca0de1d7e9c0419011c603de3e0ab`：Skill regression。

反过拟合测试显式禁止以下词进入 Skill：benchmark fixture 文件名、服务名、OTel、CrashLoop、RCAEval 等。

MCP CI：`33970150633`，当前等待全矩阵收尾。

## 5. CI / repository topology 分类

Core code CI 已通过。

Branch topology guard `33969690366` 失败不是本轮代码架构失败：仓库中另一个 `experiment/tracecite-adaptive-stopping` 分支也携带 active ahead commits，repository policy 因同时看到两个 active branch 报错。

这是 repository topology / CI governance 外部状态。不得为了让本轮 CI 变绿而擅自删除、重写或合并其他人的分支。

## 6. 新风险

1. Run JSONL selection 与 Analyze public physical planner 当前仍是 transitional modules，尚未完全收敛为统一 Plan IR；如果长期保留，会再次形成 planner duplication。
2. old `evidence_compute.py` 内部仍保留 repeated `_trim_topn` fallback；公共路径已经绕开主要可编译 JSONL Top-K，但长期应移除重复实现。
3. MCP transport timeout 与 Core compute cancellation 仍未绑定；transport 超时后存在后台工作继续执行的潜在风险。
4. pipeline `tail N` 仍缺少 SourceView reverse bounded-reader pushdown。

## 7. 下一步验证

在 Core + MCP CI 全绿后，只触发一次昂贵完整 A/B：

- timeout 继续保持 600 秒；
- same RCAEval case / same question / same shared telemetry；
- benchmark preflight 增加本轮结构性 tests；
- MCP pin 更新到包含 generic Skill contract 的 commit；
- 重点观测：
  1. run10 的四个约 60 秒 `tracecite_run` 是否消失；
  2. 37/20/9 秒 Analyze Top-K calls 是否显著下降；
  3. Evidence calls 是否从 93 降低；
  4. low-novelty ratio 是否从 38.7% 降低；
  5. Agent 是否能在 TraceCite boundary 内读取 task 明确提供的小 source；
  6. literal-vs-regex misuse 是否消失；
  7. final answer 是否恢复，并保持 evidence-boundary honesty。

若仍失败，再按真实 trajectory 决定下一优先级：compute cancellation、tail/reverse reader、exact-source API，或进一步收敛 common IR planner；不根据当前 case 预置顺序。