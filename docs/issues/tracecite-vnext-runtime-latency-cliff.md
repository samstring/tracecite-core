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

原实现的 `try_run_fast_jsonl_aggregate()` 在请求含 `last/since/until` 时直接返回 `None`，导致本来可以单次流式完成的 `count/group/distinct + bounded postprocess` 回退到 canonical Record pipeline。

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

当前修复策略：只对能证明与 reference date 无关的完整日期 `since/until` 走 streaming fast path；`HH:MM` 和 `last` 在有等价 physical plan 之前继续 canonical，避免为了性能修改时间语义。

### P0-2：fast/canonical 之间存在性能悬崖

当前执行更接近：

```text
program shape recognized -> specialized fast path
otherwise                -> full canonical fallback
```

而不是统一 IR + physical planner。一个普通 operator 或 scope 不被识别时，执行成本可从毫秒/秒级突然上升到几十秒。

长期修正：Shell / Analysis / Program 都应先 lowering 到统一 Evidence IR，physical planner 决定 shared scan、streaming aggregate、bounded top-K 或 canonical Record execution。`fast_xxx.py` 只能作为阶段性 physical operator，不能继续演化成 case-by-case pattern 集合。

### P0-3：Analysis API 还不能表达常用 time-scoped batch compute

`tracecite_analyze` 当前主要表达同一 source 上的 `name + program`。真实 Agent 轨迹已经出现向 `tracecite_analyze` 传 `since/until` 的行为，但当前 pinned MCP tool schema 没有正式声明这两个参数。

更严重的是：该调用在一次真实 run 中成功返回，而 scope 没进入 Compute Request / result identity。这意味着 transport/adapter 可能静默丢弃未知参数，Agent 会误以为统计结果已经应用时间窗口。

这是**正确性缺陷**，不是单纯性能缺陷。

设计要求：

- MCP schema 必须显式表达支持的 scope；
- 不支持的字段必须报错，禁止 silent drop；
- time scope 应进入 `EvidenceAnalysisSpec` / Compute IR / request fingerprint；
- Runtime 不选择窗口，只执行 caller-selected mechanical scope；
- 最终应允许同一次 source scan 对多个 caller-selected window/aggregate 同时更新 accumulator。

### P0-4：transport timeout 不是 Compute cancellation

约 60 秒超时后若底层同步计算继续占用 server/session，后续请求会形成 queue cascade。需要 Host-owned Compute Budget 和真正的 cancellation/deadline 语义；transport timeout 不能留下 zombie compute。

### P0-5：一个 unsupported analysis 会毒化整个 batch

当前 `run_evidence_compute()` 的 JSONL shared-scan planner 是 all-or-nothing：只要 `analyses` 中有一个 program 不能被 `_compile_jsonl()` 编译，整个 batch 就进入 `canonical_batch_fallback`，然后逐个执行。

真实 Agent 轨迹中，`count/distinct` 与以下通用 bounded selection 混在同一批：

```text
sort FIELD asc|desc numeric | head 1 | project FIELD
```

结果本来可以 shared scan 的 count/distinct 也被一起拖进 sequential canonical path，多次触发 60 秒 timeout。

正确 planner 不应采用“一个 operator 不支持 -> 整批退化”。至少应做到：

```text
compile each analysis independently
        ↓
partition by compatible physical plan
        ↓
shared-scan compatible group
        +
bounded top-K group
        +
canonical-only remainder
```

进一步目标是统一 IR 后让这些 operator 在同一个 scan 中共享 JSON decode / time predicate。

### P0-6：常见 extrema / bounded projection 还未进入 batch physical plan

`sort FIELD asc|desc numeric | head 1 | project FIELD` 本质是 bounded min/max，不需要全量排序。它对任意 JSONL 数值/时间字段都通用，应被 lowering 成 `TopK(field, direction, k=1) + Project(field)`，而不是 canonical full sort。

该能力不是“为 timestamp 做优化”；timestamp 只是这个通用 bounded relational pattern 的一个实例。

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
4. 修复 mixed batch all-or-nothing fallback；让可编译分析不被一个 unsupported sibling 拖慢。
5. 将通用 `sort FIELD | head N | project FIELD` lowering 为 bounded top-K/project physical plan。
6. 让 `tracecite_analyze` 的 scope 成为显式 schema + Compute identity；未知参数禁止 silent drop。
7. 重跑同一 A/B。

### P1（若 P0 后仍慢）

1. 允许同一 batch 中每个 caller-selected analysis 携带独立 absolute time scope，并在一次 scan 内共享 decode。
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

### Iteration 1 — absolute time-scoped aggregate fast path

- issue doc: `c8bffcdb352ac2b7cf6bc1a145d4bc858f662ad7`
- runtime implementation: `ed4e9e2bef83963b7d06d71ddf8ebc6c0178244a`
- parity regression: `a6504504ccee3449bc18c311ccff2058b46b61eb`
- 第一版 parity test 曾因直接拿 Agent compound syntax 调 canonical executor 而失败；产品实现未因此放宽语义，测试已改成双方共同支持的 terminal aggregate shape。
- benchmark 尚未重跑；在进入 A/B 前继续处理已由同一失败轨迹确认的 P0-5/P0-6/P0-3，以避免已知的 4×60s mixed-batch cliff 污染下一轮。

### Iteration 2 — partitioned planner + bounded top-K + explicit Analyze scope

Core：

- batch planner refactor: `fbfaaa522f5fa73a483256c2c224b8e1f398f5a2`
- planner/time-scope regressions: `4b0d73e1b46802052333e280d6dd9c8336e66e95`
- semantic parity test adjustment: `3358134c77208ebe1f51f4149c4ca5957f69b003`
- Core CI `33965579147`: Ubuntu Python 3.10–3.14 + macOS 3.14 全部通过。

MCP：

- explicit `tracecite_analyze(last/since/until)` schema + forwarding: `42f0e98127050801753b95b1417bf6bc307c0143`
- scope regression: `5b6e50e4413df30e694249183568f42ebc7198bf`
- Skill 从 Shell manual 收敛为 Evidence Compute usage contract: `f918fc9e85ecf2f18d6aa078c39cb9562aacbaad`
- compact response 保留实际 applied `time_scope`: `a79413cb5cbfd60722fb5a24c1d36c8d45422db3`
- MCP CI `33965783388`: Ubuntu Python 3.10–3.14 + macOS 3.14 全部通过。

Planner 行为：

- supported aggregate 不再被 unsupported sibling 拖入整批 canonical fallback；
- `sort FIELD asc|desc [numeric] | head/take/first N | project FIELD` 进入通用 bounded top-K physical plan；
- aggregate + bounded top-K 可共享 JSONL scan；
- absolute `since/until` 成为显式 Compute scope，并进入 request fingerprint / MCP schema / compact response；
- reference-relative clock scope 和 `last` 在有严格等价 plan 前仍保留 canonical fallback。

下一轮公平 A/B：

- workflow update/pin commit: `4c32ccc078df18de6f3b7c8502985765b3cc5a7b`
- benchmark run: `33965883856`
- MCP pin: `a79413cb5cbfd60722fb5a24c1d36c8d45422db3`
- Agent timeout 保持 600 秒，没有用放宽 timeout 掩盖 Runtime 问题。
- 当前状态：运行中；结果出来后继续按 token / real elapsed / answer quality 三门验收。

### Iteration 3 — local Run #11 trace profiling: semantic parse cache + bounded derived values

- implementation commit: `9baec95`
- local input: `/private/tmp/tracecite-run11/shared/traces.jsonl` (79,563,985 bytes) and `logs.jsonl` (41,264,282 bytes)
- root cause confirmed by cProfile: `sort timestamp` called `extract_jsonline_semantics()` 242,715 times; the repeated clock-only `time` values triggered 1,941,720 `strptime` fallback attempts. This was semantic timestamp parsing overhead, not raw scan or heap selection.
- generic fix: bounded cache for pure scalar timestamp parse results; no telemetry value, service, issue, or benchmark-specific shortcut.
- local timing: traces initial four-analysis batch `13.442s -> 1.842s`; `first_time/last_time` each about `12.6s -> 1.3s`.
- generic aggregate fix: `group/distinct -> sort -> head` now lowers to fixed-capacity heap after the exact counts are collected; random parity checks across nine sort shapes matched canonical output.
- transport fix: oversized derived group/distinct keys use preview + length + value SHA + representative Evidence URI; the exact source line remains materializable. The Run #15 local reproduction reduced the initial logs batch from `54,494` to `7,674` JSON characters.
- validation: Core `741 passed, 1 skipped`; architecture governance passed; schema compatibility passed; focused MCP projection behavior was checked manually, but the temporary MCP checkout's current Python environment has no `pytest`, so that suite was not claimed as passed.
- Run #15 (`33976206687`) completed both jobs, but its TraceCite arm had 12 provider rate-limit incidents and no final answer, so it is an infrastructure-invalid quality comparison; a new paired run is required after this commit.

Remaining highest-priority issue: measure the next paired run's final answer quality and model-visible context under the same blind protocol. If the new trace still shows multi-predicate numeric Top-K CPU cost, profile that path separately before changing the planner.

### Iteration 4 — local large-log verification and scalar-cache type hardening

- follow-up implementation commit: `5eecfd5`
- local inputs rechecked before relying on CI: `traces.jsonl` 79,563,985 bytes (~76 MiB), `logs.jsonl` 41,264,282 bytes (~39 MiB), `metrics.jsonl` 22,447,829 bytes (~21 MiB)
- local real-log batch: five trace analyses completed in `2.557s`, three log analyses in `0.598s`; both used `jsonl_shared_scan_batch` with `canonical_remainder=0`
- local multi-predicate trace Top-5 returned five complete rows; the oversized `distinct message` values were transported as descriptors and remained recoverable through their representative Evidence URI
- validation: Core `742 passed, 1 skipped`; focused regression `11 passed`; `git diff --check` passed
- scalar timestamp cache now uses `typed=True`, with a regression proving boolean `True` and numeric `1` keep distinct parse semantics
- Run #16 (`33977661276`) is in progress against commit `35e2a6d`; it is the paired benchmark for the substantive Iteration 3 changes. The follow-up `5eecfd5` is correctness-only and has been pushed after the run was already dispatched.

Continuation state: wait for Run #16; then retrieve both arm results if available, classify provider incidents before judging quality, and inspect the TraceCite transcript/tool payload sizes. If the trace still identifies a generic multi-predicate Top-K bottleneck, reproduce that exact program locally against the downloaded telemetry and profile it before changing code.
