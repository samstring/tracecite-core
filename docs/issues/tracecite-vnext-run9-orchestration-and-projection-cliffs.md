# TraceCite vNext 问题：Run 33965883856 Orchestration / Projection Cliffs

状态：**Open — P0**  
发现于：RCAEval A/B run `33965883856`  
适用范围：通用 Agent + Evidence Compute Runtime，不针对任何具体服务、故障类型、字段名或隐藏答案。

## 验收门槛

本问题只有在真实 A/B 同时满足以下条件后才关闭：

- TraceCite model token < Native
- TraceCite real elapsed <= Native
- TraceCite answer quality >= Native

不能通过增加 timeout、预置调查顺序、服务名、时间值或故障签名来达标。

## 1. Run 33965883856 结果

TraceCite：

- `arm-exit = 124`
- Agent timeout = 600 秒
- final answer 为空
- provider rate limit = 3
- model calls = 48
- TraceCite Evidence calls = 59
- `tracecite_low_novelty_ratio = 0.0`

Native 同轮也因 provider 429 污染而在 600 秒超时，因此这一轮不能作为最终胜负样本；但 TraceCite 自身仍存在可独立归因的产品问题。

## 2. 真实 wall-time 分解

根据 session timestamp + Host tool activity，还原约 600 秒：

- 约 149 秒：错误的 MCP/tool discovery；
- 约 165 秒：4 个主要 planner/runtime cliff；
- 约 73 秒：其余 Evidence tool round；
- 约 205 秒：模型在 tool result 之间的生成/推理等待（含少量 provider 429）。

因此该 run 的长耗时不是单点问题，而是 Host 工具暴露、Physical Planner coverage、Agent/Runtime round-trip 三层叠加。

## 3. P0-1：Direct Tool 已存在，Agent 仍执行 MCP discovery

TraceCite Host 已直接暴露：

- `tracecite_analyze`
- `tracecite_run`
- `tracecite_materialize`
- `tracecite_replay`

但 Agent 开始调查后仍读取 `mcp-scripting` skill，并执行：

```text
find / -name "mcpScript" ...
```

单次调用耗时约 `148.657s`。直到约 2 分 29 秒后才真正开始 Evidence Compute。

### 根因分类

这是 Host/Skill capability-advertisement 冲突，不是 Evidence Runtime 计算成本。

`scriptMode=false` / `disableProxyTool=true` 已经表达“当前 Host 使用 direct tools”，但 Agent 的默认 skill universe 仍让它认为需要 MCP scripting/discovery。

### 通用修复

- 当 direct TraceCite tools 已注册时，Skill 明确禁止重新加载 MCP scripting/proxy/discovery；
- Host 应最终做到 capability advertisement 一致：禁用 scripting surface 时，不应再把 scripting discovery 当成首选路径；
- 不能通过 case prompt 写“不要查某个目录”解决。

已实施 Skill 修复：`tracecite-mcp` commit `6a253ec8f12541a418fec6b6a8faf40e6d1c9d4b`。

## 4. P0-2：multi-field bounded projection 仍掉入 canonical remainder

本轮多个通用 program：

```text
sort FIELD asc|desc | head N | project FIELD_A FIELD_B ...
```

仍未进入 shared bounded top-K physical plan。

旧 compiler 只接受 `project` 恰好一个字段。于是：

- `sort startTime ... | project startTime startTimeMillis ...`
- `sort duration ... | project startTime duration operationName ...`

被放进 canonical remainder。

### 直接后果

本轮主要 cliff：

- ~60.0s：一个 batch 中两个 multi-field extrema fallback；
- ~33.2s：shared aggregate + multi-field min fallback；
- ~35.0s：shared top-K + multi-field projection fallback；
- ~32.0s：两个都无法 compile 时退为 canonical batch。

这说明 Iteration 2 已修复“unsupported sibling 毒化 supported sibling”，但当时 physical plan 的 bounded projection 仍不完整。

### 通用修复要求

IR 应表达：

```text
TopK(
  sort_field,
  direction,
  limit,
  project_fields=[...]
)
```

Runtime 在 heap candidate 中只保留 bounded projected columns + provenance locator；不能因 `project` 多一个字段退回 full canonical sort/materialization。

### 已实施

- canonical `project` 已扩展为真正的多字段 bounded projection，单字段旧结果形状保持兼容：`cd2f4ae7c3b458bde1dde2811a12ed6ae10e970b`
- Evidence Compute Top-K compiler/heap 已改为 `project_fields`，多字段 projection 不再进入 canonical remainder：`f7c879c5d395c9e4fefa61ce0b8825f33cb37009`
- canonical/Compute parity + `canonical_remainder_analyses == 0` 回归：`265ebdd41685a6b5dde426757b192680a48b9b7a`
- Core CI `33967201272`：Ubuntu Python 3.10–3.14 + macOS 3.14 全部通过。

## 5. P0-3：特殊字段会把 shared JSONL scan 变成 Record construction scan

一次 traces batch：

```text
count
sort timestamp asc | head 1 | project timestamp
sort timestamp desc | head 1 | project timestamp
distinct *
```

执行引擎报告 `jsonl_shared_scan_batch`，但实际耗时约 `36.9s`。

原因是 `timestamp` 属于 Segmenter special field。Planner 只要发现任何 compiled analysis `needs_record=true`，就让整个 242k-row shared scan 走 `JsonLineSegmenter.segment_file()` + canonical Record 构造，即使源 JSON 根本没有可解析 `timestamp`。

同一个 traces 文件只做普通 JSON field aggregate 时约 3 秒级，说明 shared scan 名称本身不代表相同 physical cost。

### 通用修复要求

统一 planner 需要把“JSON decode”和“Record semantic enrichment”拆为可按 analysis/field 需要选择的 physical operators，而不是一个 analysis 请求特殊字段就让整批 Record 化。

至少应做到：

- 普通 JSON analyses 保持 raw JSON streaming；
- 需要 Segmenter semantic field 的 analyses 单独 enrichment，不能把无关 sibling 一起拖入；
- 对 JSONL 可证明的 aliases 使用轻量 field resolver；无法证明等价才使用 canonical enrichment。

状态：**待修复，当前下一优先级。**

## 6. P0-4：`where ... and ...` 被静默误解析，产生 false no-match

Agent 使用了自然写法：

```text
where A == X and B >= Y and B <= Z | ...
```

旧 parser 没有报 unsupported，而是把 `and B >= ...` 整串拼到第一个比较值中。

结果：真实数据存在时仍返回 `match_records=0`。

Agent 随后依据错误的 0 条结果形成错误中间判断，又执行多轮：

```text
head 300
head 3500 | tail 500
head 3800 | tail 30
head 3850 | tail 30
head 3860 | tail 10
head 3900 | tail 10
head 3950 | tail 10
head 4000 | tail 10
```

人工定位时间边界，浪费多个 tool/model round。

### 通用修复

已增加 compatibility lowering：

```text
where A OP X and B OP Y and C OP Z
```

在可以无歧义解析时转换为：

```text
where A OP X | where B OP Y | where C OP Z
```

quoted value 中的 `and` 不拆分。

实现：`c4950bc6f7cb58b8f4187f62acdf7ab1b5c8d673`。

第一版回归使用了 JSON `timestamp` 数值字段，意外混入了 TraceCite `timestamp` 特殊语义，因此测试预期不独立；随后改用普通 `seq` 字段，只验证 boolean lowering 本身：`8d24e22d58967dfffe7660266b0a1909bb02ee6a`。

该修复与多字段 projection 一起在 Core CI `33967201272` 全矩阵通过。

长期应把 predicate boolean expression lowering 放进统一 IR parser，而不是继续堆 Agent compatibility rewrite。

## 7. P0-5：Agent/Runtime 仍有过多 rank-probing round trip

即使单个 `head/tail/project` 调用只有约 1.5–3.3 秒，模型每轮读取结果再决定下一个 rank，会叠加 3–10 秒级 model gap。

这不是简单的“Agent 太笨”；API/IR 应让已经明确的机械问题一次下推。

例如“找某字段在某范围内的首次/末次记录、边界附近记录”应该由：

- explicit time scope；
- bounded min/max；
- seek/near；
- predicate + top-K；

一次 Runtime compute 完成，而不是让模型手工做 rank search。

Runtime 不应决定调查哪个时间/字段；只负责执行 Agent 已经选择的机械目标。

## 8. 当前修复顺序

P0：

1. ~~修 direct-tool discovery 冲突~~ — Skill 已修，待真实 A/B 验证；
2. ~~修 boolean where false no-match~~ — Core CI 已通过；
3. ~~扩展 bounded TopK IR 到 multi-field projection~~ — canonical/Compute parity 已通过；
4. 将 special-field enrichment 从整个 shared batch 中解耦；
5. 让 `tracecite_run` 的 JSONL search + top-K 复用 streaming Compute physical operator，减少 candidate-recovery 开销；
6. 增加 Compute deadline/cancellation，避免未来 timeout zombie work；
7. 重跑相同 A/B，timeout 保持 600 秒。

## 9. 质量信号

虽然最终 answer 为空，但 timeout 前最后一次 materialize 已读到直接 shutdown 证据：ExecutorService shutdown、JMX unregister、Mongo connection pool closed 等。也就是说 Agent 在 600 秒边界前已经接近 Native 的正确 RCA，只是没有剩余时间形成最终答案。

这进一步说明优先级应该是消除无效 discovery、planner cliff 和机械 round-trip，而不是给 Agent 增加 case-specific RCA 知识。
