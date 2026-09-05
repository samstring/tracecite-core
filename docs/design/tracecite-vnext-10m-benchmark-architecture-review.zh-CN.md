# TraceCite vNext：10 分钟真实 A/B 后的架构复审

状态：**架构复审完成；当前第一阶段实现 NO-GO，核心方向有条件保留**  
日期：2026-09-05

## 1. 为什么必须在这里停下来复审

本轮真实 blind RCA A/B 使用相同 Evidence、相同问题边界和 600 秒 Agent 上限：

- Native：正常完成最终答案。
- TraceCite：600 秒超时，退出码 124，最终答案为空。
- Native 调查会话约 214 秒；其中模型等待约 206 秒、工具执行约 8 秒。
- TraceCite 调查会话约 594 秒；其中模型等待约 125 秒、工具执行约 469 秒。
- Native 遭遇 12 次 provider rate limit，仍然完成。
- TraceCite 没有记录 provider incident，仍然超时。

因此这次失败不能归因于“GMI2 更慢”或 429。主要失败面在 TraceCite Runtime / MCP / Agent surface。

同时，TraceCite 在模型输入上出现了明确正向信号：

| 指标 | Native | TraceCite | TraceCite 相对变化 |
|---|---:|---:|---:|
| fresh input tokens | 153,069 | 64,873 | -57.6% |
| cached input tokens | 2,354,810 | 1,254,609 | -46.7% |
| output tokens | 11,105 | 5,892 | -46.9% |
| model calls | 44 | 40 | -9.1% |
| tool calls | 31 | 40 | +29.0% |
| final answer | 有 | 无 | 失败 |

这说明：**Transport Gate / bounded result 的方向得到部分验证；Compute 执行和 Agent 交互路径没有通过验收。**

## 2. 本轮暴露出的通用问题

### 2.1 Agent surface 仍然有 MCP discovery tax

TraceCite Agent 在开始有效分析前做了多轮：

- 尝试 native evidence access，被 benchmark boundary 拒绝；
- 尝试 `mcpScript` 的动态 import；
- 检查 `mcpScript` 环境；
- 搜索 TraceCite MCP tools；
- 再通过脚本包装调用真正的 TraceCite tools。

`tracecite_analyze` 已经存在，但没有成为“拿到问题后直接可用的低摩擦主入口”。

这是通用集成缺陷，不是 RCA case 缺陷。一个用户已经显式选择 TraceCite 的 Agent，不应该先花模型轮次学习如何访问 TraceCite。

### 2.2 同一个机械意图可能落入完全不同的执行成本

本轮可观察到：

- shared JSONL `count/group/distinct` 可以在几秒内完成；
- `sort FIELD | head 1 | project FIELD` 因不能进入 shared-scan IR，回退 canonical pipeline；
- 对 242k trace records 的 min/max 时间查询触发约 30 秒 MCP script timeout；
- 随后的 `tail 1` / `lines ...` 又出现 60 秒 request timeout；
- timeout 后底层同步工作没有及时停止，后续请求出现排队/级联，导致本来可快速完成的 log aggregate 也出现 53–60 秒延迟。

这说明目前“一个 Agent tool boundary”不等于“一个高效 Compute Plan”。

### 2.3 Batch API 只能减少理论边界，不能保证 Agent 真正 batch

当前 `tracecite_analyze` 要求 Agent 先知道同一 source 上需要哪些分析，再一次提交。

这能优化：

> 已知多个 aggregate → shared scan

但不能解决：

> 看一次结果 → 模型想下一步 → 再看一次 → 再想下一步

更不能解决多 source 的机械比较。Native 可以在一个 Python/bash 进程里同时读 logs/traces/metrics 并做窗口统计；当前 Analyze 的执行边界仍然是单 source。

因此仅仅“API 支持 list[analysis]”并不能自动把 40 个 model/tool round 变成 3–8 个 meaningful rounds。

### 2.4 timeout 没有形成真正的 Compute Budget

现在 request timeout 更像 transport timeout：调用方停止等，但底层同步 compute 可能继续占用 MCP server。

真正需要的是 Host-owned Compute Budget：

- deadline / CPU / scan bytes / memory；
- Runtime 在预算内可被中止；
- timeout 后不能留下继续阻塞同 session/server 的后台工作；
- 后续请求不能因为前一次超时形成隐式队列。

这是架构中原本提出但第一阶段尚未真正落地的部分。

### 2.5 Benchmark observability 也存在缺口

benchmark host 当前能直接识别 `tracecite_run/materialize/...`，但 `mcpScript` 内部真实 TraceCite 调用不可见，而且 host tool set 没有把 `tracecite_analyze` 纳入 TraceCite evidence category。

这会让 tool trajectory 和 channel verification 低估真实 Evidence calls。后续 benchmark 应优先使用直接 TraceCite tools，并把 analyze 纳入统一观测。

## 3. 反方：如果没有 TraceCite，Native 会不会更好？

本轮答案是：**在当前实现上，是。**

Native 的优势不是“模型更聪明”，而是机械计算路径非常直接：

```text
Agent
  ↓
one bash/python program
  ↓
scan / filter / window / join / aggregate
  ↓
small stdout
  ↓
Agent
```

它可以现场写 Python：

- 一次加载/扫描多 source；
- 自己定义窗口；
- 用 dict/list/loop 做任意纯计算；
- 不需要学习另一套查询语法；
- shell/head/tail/grep 的实现高度优化；
- tool transport 很薄。

本轮 Native 31 个工具调用虽然不少，但工具总时间只有约 8 秒。TraceCite 40 个工具调用里，工具时间约 469 秒。

因此 TraceCite 不能靠“更安全、更可验证”来合理化任意性能损失。若最终无法把机械执行成本压到 Native 同量级，Native-only 应继续作为可接受甚至更优的架构选择。

## 4. TraceCite 自身带来的弊端

即使最终优化成功，也必须承认这些结构性成本：

1. **抽象学习成本**：Agent 要理解 Evidence Runtime、program、pointer、materialize。
2. **tool schema 成本**：每个直接工具都会进入 system/tool context。
3. **transport 成本**：Native 进程内变量变成 MCP request/response。
4. **表达能力上限**：固定 DSL 永远追不上 Python。
5. **optimizer 语义风险**：fast path 必须与 canonical Segmenter/Record semantics 等价。
6. **provenance 成本**：SourceVersion、lineage、session ledger 都不是免费的。
7. **timeout/cancellation 更复杂**：跨 MCP 边界后必须显式处理取消和预算。
8. **过度压缩风险**：如果 Runtime 只给 aggregate，可能隐藏 Agent 真正需要的原始异常形态。
9. **代表 Evidence 偏差**：representative sample 不能冒充完整分布。
10. **平台集成差异**：不同 Agent Host 对 MCP direct/proxy/script 的处理不同。

TraceCite 必须用实际收益抵消这些成本，而不是把这些成本视为理所当然。

## 5. 哪些东西应该交给大模型

### 5.1 应该交给模型

模型负责真正需要语义判断的内容：

- 用户问题；
- 当前 Agent 自己的 hypothesis / reasoning state；
- 小型 aggregate / contrast / top-K；
- 有明确覆盖语义的 count/delta/rate；
- 少量 representative Evidence handles；
- Agent 主动选择后 materialize 的 exact raw Evidence；
- 机械执行错误中真正能帮助改写 program 的最小反馈；
- 必要的 SourceVersion / coverage identity。

### 5.2 不应该默认交给模型

- 完整 RecordSet；
- 中间 table；
- 全部 matched pointers；
- full lineage graph；
- 已经发送过的 Evidence body；
- Runtime 内部 execution plan 细节；
- MCP discovery / schema 探索结果（用户已选择 TraceCite 时）；
- 可以由 Runtime 确定的字段统计、排序、窗口聚合的原始输入。

原则仍然是：

> 大数据进入 Runtime；只有 bounded working set 穿过 Transport Gate。

本轮 token 结果说明这个原则值得继续保留。

## 6. 怎样真正减少模型次数

只减少 response bytes 不够。需要减少“模型必须回来决定一次”的边界。

### 6.1 立即做：直接、窄的 Agent tool surface

用户显式选择 TraceCite 时，Host 应直接暴露少量主工具：

- `tracecite_analyze`
- `tracecite_run`
- `tracecite_materialize`
- `tracecite_replay`

默认隐藏 MCP scripting/proxy compatibility surface，避免 Agent 先搜索工具、描述 schema、再包装调用。

Compatibility tools 可以保留产品能力，但不应进入默认 hot path。

### 6.2 立即做：让已识别的 bounded pattern 真正进入 fast IR

当前 JSONL shared scan 已证明有效，因此下一步不是增加 RCA 专用 operator，而是扩充**通用、可证明等价**的 bounded plan pattern，例如：

- `sort FIELD asc|desc [numeric] | head N | project FIELD`
- JSONL `head/tail/lines` 的 bounded selection fast path
- 已有 predicate + group/count/distinct + bounded post-process

这些都是通用数据流优化，不包含任何 service、error、OTel、JVM、memory 或本 case 语义。

### 6.3 立即做：Compute timeout 必须可取消

Transport timeout 不能留下继续执行的工作。Host/Runtime 应有显式 compute deadline，并保证 timeout 后释放 server/session 执行能力。

### 6.4 先验证，再决定是否提前进入 Program API

如果完成以上三项后，Agent 仍然因为“多 source / 自定义窗口 / 自定义纯逻辑”产生大量 round trip，则证明第一阶段 Analysis API 的表达边界本身是瓶颈。

届时才把 Program API 提前：

```text
Evidence Program
  ├─ declarative data flow
  └─ bounded pure UDF escape hatch
          ↓
Evidence IR
```

但现在还没有证据支持直接建设完整 UDF VM/WASM。先把已经存在的机械能力做到 Native 级执行效率。

## 7. 对总体架构的重新判定

### 保留

- Source / SourceVersion
- SessionSourceView
- Segmenter / Record
- Evidence identity / provenance
- materialize / replay
- Runtime-side intermediate sets
- Transport Gate
- Host-owned Evidence budget
- Agent owns reasoning
- Analysis / Program / Shell frontend → unified IR → Compute Engine 的长期方向

### 调整

1. **Agent surface 从“所有 MCP 能力可发现”改成“显式选择后直接暴露 4 个 hot-path tools”。**
2. **Compute Budget / cancellation 从未来能力提升为第一阶段必需项。**
3. **IR 第一阶段不应只覆盖 count/group/distinct；应覆盖常见 bounded selection/projection pattern。**
4. **shared scan 的验收不是“代码里存在”，而是 benchmark trajectory 中不能频繁掉回昂贵 canonical path。**
5. **如果 single-source Analyze 仍导致 model rounds 高，则下一阶段优先做 multi-source Evidence Program，而不是继续加 Shell compatibility。**

### 仍然 NO-GO

- RCA planner；
- root-cause scoring；
- stop rule；
- 针对当前 case 的健康期/故障期规则；
- route-service / OTel / JVM / memory 专用规则；
- 预置故障签名；
- 为 benchmark hidden answer 加任何 shortcut。

## 8. 当前 Go / No-Go 决策

### 对“当前第一阶段实现”：NO-GO

原因：

- token gate：通过；
- time gate：严重失败；
- answer gate：失败；
- tool/model round gate：没有显著改善。

### 对“Evidence Compute + Transport Gate 总体方向”：条件 GO

理由：

- token 明显下降，证明 Runtime-side compute / bounded transport 有真实价值；
- 失败时间几乎全部落在工具执行层，不是 reasoning/provider；
- 已有 shared JSONL fast path 在能命中时确实能把大扫描压到几秒；
- 因此当前证据更像“第一阶段执行器/入口没有覆盖关键通用 pattern”，还不足以证明整个 Compute 架构错误。

## 9. 下一轮实施计划

按以下顺序推进，任何一步都不能引入 case-specific logic：

### P0 — Agent surface / benchmark truth

- 默认隐藏 `mcpScript`；
- 只直接暴露 4 个 hot-path TraceCite tools；
- `tracecite_analyze` 纳入 benchmark host TraceCite category/access accounting；
- 验证首轮无需工具发现即可调用 Analyze/Run。

### P0 — Runtime performance

- 为 JSONL bounded extrema/projection 增加 shared-scan fast plan；
- 为 JSONL `head/tail/lines` 增加语义等价 fast selection；
- 对 fast path 增加 canonical parity regression；
- 对大 JSONL 增加性能回归门槛（重点防止意外 O(N log N) / full materialization，不绑定当前数据集具体时间）。

### P0 — timeout / cancellation

- 先消除本轮可重现的 >30s generic canonical hot paths；
- 再增加 Host-owned compute deadline/cancellation，确保请求超时不会继续占住 MCP server；
- 增加 timeout 后下一请求可以立即执行的回归。

### P1 — 重新跑 blind A/B

同样 Evidence、同样问题、同样 Host policy，再跑：

```text
TraceCite fresh/cached token < Native
TraceCite agent elapsed <= Native
TraceCite answer quality >= Native
```

429 单独标记；若一侧被 provider rate limit 主导，做复测或 crossover，不把 provider noise 算成产品收益/回归。

### P2 — 只有仍然失败才决定 Program API 是否提前

如果 Runtime 已经快，但 trajectory 仍有大量“看一点 → 想一次 → 再算一点”，再确认是不是 Analysis API 表达上限。

如果是，进入 multi-source Evidence Program / IR；如果不是，继续修具体的通用 orchestration defect。

## 10. 重新审视循环

每次失败必须先回答：

1. 没有 TraceCite，Native 是怎么更简单地完成这一步的？
2. TraceCite 多出来的 boundary 是否提供了 provenance / safety / bounded transport 的等价收益？
3. 当前缺陷在别的日志、trace、metric、代码 Evidence 上是否同样成立？
4. 修复是否只优化一个通用数据流 pattern，而不是当前事故语义？
5. 这个工作真的需要模型看吗，还是 Runtime 可以机械完成？
6. 能否把两个连续 tool/model round 合并成一个不改变 reasoning ownership 的 Runtime operation？
7. 如果做不到 time/token/quality 三门同时通过，是否应该回到 Native-only，而不是继续扩大 TraceCite？

只有这些问题都能给出通用答案，才继续编码。
