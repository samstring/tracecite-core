# TraceCite vNext 问题：Run 33965883856 Orchestration / Projection Cliffs

状态：**Open — P0，最新 A/B 验证中**  
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

已实施 Skill 修复：`tracecite-mcp` commit `6a253ec8f12541a418fec6b6a8faf40e6d1c9d4b`；MCP CI `33966864148` 全部通过。最新 A/B 已 pin 到该 commit，待真实 Agent 验证 discovery 是否彻底消失。

## 4. P0-2：multi-field bounded projection 仍掉入 canonical remainder

本轮多个通用 program：

```text
sort FIELD asc|desc | head N | project FIELD_A FIELD_B ...
```

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

原因是 `timestamp` 属于 Segmenter special field。旧 Planner 只要发现任何 compiled analysis `needs_record=true`，就让整个 242k-row shared scan 走 `JsonLineSegmenter.segment_file()` + canonical Record 构造，即使其他 sibling 只需要普通 JSON 字段。

同一个 traces 文件只做普通 JSON field aggregate 时约 3 秒级，说明 shared scan 名称本身不代表相同 physical cost。

### 方案比较与最终决策

考虑过三种方向：

1. 只给 `timestamp` 写轻量 shortcut：性能成本最低，但会复制 JsonLineSegmenter 时间语义，长期容易产生 fast/canonical 漂移，拒绝。
2. 将 special-field analysis 单独拆成第二次 canonical scan：能避免拖慢普通 sibling，但仍需额外全量扫描，而且没有解决语义实现重复问题。
3. **把 JSON decode 与 Segmenter semantic enrichment 分层，并抽取单一 JSONL 语义实现**：一次 raw-line scan、每候选行最多一次 JSON decode，只有需要 `timestamp/level/msg` 时才从 decoded mapping 做语义 enrichment；canonical JsonLineSegmenter 也调用同一函数。

选择方案 3，因为它同时满足正确性、通用性、架构一致性、可维护性和性能要求，不依赖当前 case 的字段分布。

### 已实施

共享语义模块：

- `src/tracecite_core/jsonline_semantics.py`
- commit `6d2cd4d202d5db765a85575438b80ea17875d827`
- 统一拥有 JSONL timestamp/level/msg alias、时间戳解析/归一化语义。

canonical Segmenter：

- `JsonLineSegmenter` 改为 decode 后调用共享 `extract_jsonline_semantics()`：`92d6df294ab20d8c18ce1c74ba768930335bf5d0`
- 第一次 CI 暴露旧 `text_filter.py` 仍私有导入 `_normalize_timestamp`；这是迁移兼容缺口，不是架构方向错误。
- 保留 `_normalize_timestamp` 兼容 alias，但实现仍只有共享模块一份：`b7afd174ded5aa2687ff6f6d9e607f8ec2d2d7b2`。

Evidence Compute physical plan：

- commit `92534f30f01caa23602eb7943eafbbbfdbe2ecb1`
- 删除 whole-batch `any(needs_record)` 决策；
- JSONL 始终从 raw physical lines streaming；
- raw predicates 优先；
- 同一候选行 JSON 只 decode 一次；
- `timestamp/level/msg` 按需从 decoded mapping 做 lazy semantic enrichment；
- line/source/text 等 locator metadata 不需要构造 Record；
- absolute time scope 直接复用同一 semantic timestamp，同时保持“无可解析时间戳的记录不会被时间窗口静默排除”的 canonical 语义。

新增架构回归：

- `tests/test_jsonline_semantics_shared.py`：`292ffcfa1b7c2224223887e7c4fac6b402f32e21`
  - 验证共享语义与 canonical JsonLineSegmenter 完全一致；
  - 覆盖 ISO/epoch/非法 timestamp、level/msg alias、custom alias。
- `tests/test_evidence_compute_lazy_jsonl_semantics.py`：`d2824908347b04326c2c2d3a522c2edbde3ae902`
  - monkeypatch `JsonLineSegmenter.segment_file` 为失败，证明 shared Compute 不再构造 whole Record scan；
  - semantic + normal fields 一行只允许一次 `json.loads`；
  - absolute time scope 也不允许退回 Record scan。

最终 Core CI `33967903026`：Ubuntu Python 3.10–3.14 + macOS 3.14 全部通过。

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

## 8. 新确认的通用执行层缺口：Run Top-N / tail 仍未统一 physical scan

在等待最新 A/B 时继续审查发现：

- `tracecite_run` 的 `sort ... | head N` 虽已使用 heap，避免 full sort；
- 但其输入仍通过 `_initial_rows -> iter_matching_records -> Record`，JSONL 没有复用 Analyze 现在的 raw-line/shared-decode physical scan；
- canonical `tail_lines` 会先 `_line_count()` 全扫一次，再 `segment_file()` 从头扫描；
- pipeline 层 `tail N` 甚至没有 pushdown 到 source scanner。

SourceVersion/SourceSegment 已保存 `lines` 元数据，因此如果最新 trajectory 继续证明 tail/Run Top-N 是显著耗时，正确下一步是：

```text
Program IR Selection/TopK
        ↓ pushdown
SourceView physical line reader
  ├─ forward stream
  └─ reverse bounded stream
        ↓
shared JSON decode / semantic resolver
```

而不是新增 case-specific `fast_tail` 或增大 timeout。该方向可以让 `tail`、`last` 锚点、Run Top-N 与 Analyze 共用更底层 physical primitive。

## 9. 当前修复顺序

P0：

1. ~~修 direct-tool discovery 冲突~~ — Skill + MCP CI 已通过，真实 A/B 验证中；
2. ~~修 boolean where false no-match~~ — Core CI 已通过；
3. ~~扩展 bounded TopK IR 到 multi-field projection~~ — canonical/Compute parity 已通过；
4. ~~将 special-field enrichment 从整个 shared batch 中解耦~~ — lazy shared semantics + 全矩阵 Core CI 已通过；
5. 根据最新 A/B trajectory 决定是否将 `tracecite_run` JSONL Top-N / tail 下推到统一 SourceView physical scan；
6. 增加 Compute deadline/cancellation，避免 transport timeout 留下 zombie work；
7. 继续同一 A/B，timeout 保持 600 秒。

## 10. Iteration 3 — lazy JSONL semantics + direct-tool Skill + latest A/B

代码/Skill：

- MCP direct-tool discovery contract：`6a253ec8f12541a418fec6b6a8faf40e6d1c9d4b`
- shared JSONL semantics：`6d2cd4d202d5db765a85575438b80ea17875d827`
- canonical Segmenter uses shared semantics：`92d6df294ab20d8c18ce1c74ba768930335bf5d0`
- Evidence Compute lazy semantic physical plan：`92534f30f01caa23602eb7943eafbbbfdbe2ecb1`
- semantic parity regression：`292ffcfa1b7c2224223887e7c4fac6b402f32e21`
- no whole-Record scan regression：`d2824908347b04326c2c2d3a522c2edbde3ae902`
- migration compatibility alias：`b7afd174ded5aa2687ff6f6d9e607f8ec2d2d7b2`

验证：

- Core CI `33967903026`：SUCCESS，Ubuntu Python 3.10–3.14 + macOS 3.14 全部通过；
- MCP CI `33966864148`：SUCCESS。

最新 A/B：

- workflow commit：`3f1b0d917abaf865dbffc63e86006152248feea5`
- run：`33967988159`
- MCP pin：`6a253ec8f12541a418fec6b6a8faf40e6d1c9d4b`
- Agent timeout：仍为 600 秒；
- 新增 `agent-elapsed-ms.txt`，后续 real elapsed 直接读取，不再靠 transcript timestamp 近似；
- preflight 加入 lazy semantics、semantic parity、conjunction、last fastpath 等回归；
- 当前状态：Native / TraceCite 真实 Agent 阶段运行中。

## 11. 质量信号

虽然 run `33965883856` 最终 answer 为空，但 timeout 前最后一次 materialize 已读到直接 shutdown 证据：ExecutorService shutdown、JMX unregister、Mongo connection pool closed 等。也就是说 Agent 在 600 秒边界前已经接近 Native 的正确 RCA，只是没有剩余时间形成最终答案。

这进一步说明优先级应该是消除无效 discovery、planner cliff 和机械 round-trip，而不是给 Agent 增加 case-specific RCA 知识。
