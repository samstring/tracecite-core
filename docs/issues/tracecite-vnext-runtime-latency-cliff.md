# TraceCite vNext 问题跟踪：Runtime Latency Cliff

状态：**Open — 按 benchmark 闭环持续更新**  
首次记录：2026-09-05

## 1. 验收目标

TraceCite vNext 的真实 Agent A/B 只有同时满足以下条件才算通过：

- `TraceCite model token < Native`
- `TraceCite real elapsed <= Native`
- `TraceCite answer quality >= Native`

任何一项失败都继续归因、修复、回归、重跑。修复必须是通用产品行为，禁止针对某个 benchmark case、服务名、日志字段、故障类型或隐藏答案增加规则。

## 2. 当前现象

最近一次有效 A/B（run `33963380099`）中：

- TraceCite 的 fresh/cached model input 和 model calls 均明显低于 Native；
- TraceCite Agent 仍在 600 秒上限退出，未形成最终答案；
- Native 虽然遭遇更多 provider 429，仍能完成；
- TraceCite 的主要时间消耗在 Evidence Runtime / MCP tool 执行而不是模型等待；
- 多个 `tracecite_run` / `tracecite_analyze` 调用呈现约 60 秒的 latency cliff。

因此当前失败分类是：**Runtime performance + orchestration**，不是 provider incident，也不是答案推理规则不足。

## 3. 已确认的通用根因

### P0-1：time scope 使常用 JSONL aggregate 失去 fast path

当前 `try_run_fast_jsonl_aggregate()` 在请求含 `last/since/until` 时直接返回 `None`，导致本来可以单次流式完成的 `count/group/distinct + bounded postprocess` 回退到 canonical Record pipeline。

事故/时间窗口查询是日志、trace、metric 调查中的通用操作，不是任何 RCA case 的特性。因此 time scope 必须成为 Compute IR 的一等 mechanical predicate，而不能是 fast-path exclusion。

期望：

```text
SourceVersion
  -> time scope predicate
  -> raw/field predicates
  -> count/group/distinct/top-K
  -> bounded result
```

其中绝对 `since/until` 应在一次 streaming scan 中完成，不能为了建立 reference time 预先全量扫描一次。

### P0-2：fast/canonical 之间存在性能悬崖

当前执行更接近：

```text
program shape recognized -> specialized fast path
otherwise                -> full canonical fallback
```

而不是统一 IR + physical planner。一个普通 operator 或 scope 不被识别时，执行成本可从毫秒/秒级突然上升到几十秒。

长期修正：Shell / Analysis / Program 都应先 lowering 到统一 Evidence IR，physical planner 决定 shared scan、streaming aggregate、bounded top-K 或 canonical Record execution。`fast_xxx.py` 只能作为阶段性 physical operator，不能继续演化成 case-by-case pattern 集合。

### P0-3：Analysis API 还不能表达常用 time-scoped batch compute

`tracecite_analyze` 当前只能表达同一 source 上的 `name + program`，不能把已经决定好的多个时间窗口计算一起交给 Runtime。Agent 因此仍会回到多次 `tracecite_run`。

设计方向：time scope 应属于 AnalysisSpec/IR，而不是调查策略。未来应允许同一次 shared scan 对多个 caller-selected window/aggregate 同时更新 accumulator；Runtime 不选择窗口，也不解释因果意义。

### P0-4：transport timeout 不是 Compute cancellation

约 60 秒超时后若底层同步计算继续占用 server/session，后续请求会形成 queue cascade。需要 Host-owned Compute Budget 和真正的 cancellation/deadline 语义；transport timeout 不能留下 zombie compute。

## 4. Agent 使用模型问题

Agent 已经会调用 TraceCite；最近一轮 `mcpScript` discovery 已被消除。但当前 Skill 仍带有较强的 Evidence Shell manual 形态，容易强化“小查询 -> 模型 -> 小查询”的交互方式。

Skill 应逐步收敛为 Evidence Compute usage contract：

- Agent owns reasoning；
- 已决定的 mechanical computations 尽量 batch；
- intermediate RecordSets 保持 Runtime-side；
- 默认返回 bounded derived result；
- 只有推理/引用需要时 materialize exact Evidence；
- 不重复相同 computation；
- Host owns source lifecycle / compute / transport budgets。

具体 DSL 语法应由 tool schema / Program API 表达，而不是靠长篇 prompt 教学。

## 5. 实施顺序

### P0

1. 为 JSONL aggregate 增加语义等价的 absolute `since/until` streaming fast path。
2. 加 parity regression：fast result 必须与 canonical time-scope result 一致。
3. 加性能回归约束：time-scoped aggregate 不允许走 `canonical` execution engine。
4. 重跑同一 A/B。

### P1（若 P0 后仍慢）

1. 将 time scope 纳入 `EvidenceAnalysisSpec`，允许一批 caller-selected time-scoped aggregates shared scan。
2. 对 bounded top-K / projection 使用同一 time predicate physical operator。
3. 实现 Compute deadline/cancellation，避免 timeout queue cascade。
4. 重跑 A/B。

### P2（只有 benchmark trajectory 继续证明需要）

把 Shell/Analyze lowering 到统一 IR + physical planner，并优先支持 multi-source mechanical program；不继续堆独立 `fast_xxx` 特判。

## 6. 不允许的修复

以下内容即使能让当前 benchmark 变快也禁止：

- 预置某个服务、组件、日志字段或故障签名；
- 预设 RCA 调查顺序；
- Runtime 自动判断 root cause / stop；
- 为某一份 telemetry 的时间值或 schema 写专用 shortcut；
- 根据 hidden answer 做 query rewrite；
- 用更大 timeout 掩盖 Compute 问题。

## 7. 每轮记录

每轮修改后在这里追加：commit/run、Core/MCP regression、Native/TraceCite token、elapsed、answer quality、provider incidents、剩余失败分类，以及下一步是否仍满足通用性约束。
