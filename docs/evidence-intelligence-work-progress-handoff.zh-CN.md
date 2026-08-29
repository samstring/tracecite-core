# Evidence Intelligence 工作进度与交接

> 本文档是 `experiment/evidence-intelligence` 分支当前工作的权威交接记录。旧聊天、旧实验记录和旧进度文件仅作为历史；出现冲突时，以本文档较新的决策和最新测试事实为准。

更新时间：2026-08-29

## 1. 当前工作基线

- 仓库：`samstring/tracecite-core`
- 当前工作分支：`experiment/evidence-intelligence`
- 基础分支：`refactor/agent-v2`
- 本轮减法重构开始前 HEAD：`e43c0cb8605992e1f9b2b2871a1571069e30b85a`
- 没有明确确认前，不合并到基础分支。
- Core 稳定前，不先改 Mobile / MCP 的上层业务设计。

当前阶段目标不是继续增加“智能规则”，而是收敛 Evidence Runtime 的主链，删除/合并重复 owner，并用真实 Agent A/B 证明核心卖点没有退化。

---

## 2. 产品定位与不可破坏的卖点

TraceCite 继续定位为：

> **面向 AI Agent 的 Evidence Runtime / Evidence Control Plane。**

TraceCite 不是：

- `rg` / grep 替代品；
- 通用代码搜索器；
- Elasticsearch / Splunk / Observability 存储平台；
- 自治 Agent / LLM planner；
- 自动 root-cause 推理器。

Agent 负责：

```text
hypothesis
causal reasoning
root-cause conclusion
fix proposal
```

TraceCite 负责：

```text
evidence access
provenance / source version
bounded retrieval
pointer -> raw evidence recovery
evidence integrity
coverage / novelty / progress
context control
deterministic mechanical correlation / exploration
```

### 2.1 硬优先级

> **Correctness > Evidence Fidelity > Token Saving**

No-Harm 硬规则：

```text
free_shell passed == true
AND
tracecite passed != true

=> TraceCite no-harm regression
=> 验收失败
```

Token 节省、tool output 减少、context 更小，都不能抵消正确性退化。

### 2.2 三个必须继续成立的核心卖点

#### A. 小/简单 evidence：接近 shell，不带偏

```text
small/simple evidence
TraceCite ≈ rg + cat
```

要求：

- 尽量直接看到原始事实；
- 保持顺序、scope、source、line、SHA；
- 不通过摘要/排序改变事实含义；
- 不为了省 token 增加数量级工具轮次。

#### B. 大/高噪 evidence：bounded context 不崩

已经有真实模型证据证明大日志是 TraceCite 的核心价值场景。

历史完整 paired run `33199132708` 中：

- 4 个 scale case 里 free-shell 有 3 个 `context_window_exceeded`；
- TraceCite 0 个 context overflow；
- `kubernetes-140848` 同质量下 free-shell input 1,126,926，TraceCite 244,202，约减少 78.3%。

本轮重构不得把大日志重新退化成 raw dump。

#### C. Evidence 必须可恢复、可验证

任何压缩/分组/选择都必须满足：

```text
Agent-visible compact evidence
        ↓
stable pointer / recovery handle
        ↓
immutable or version-checked raw evidence
```

不能出现“被省略以后无法恢复”的事实。

---

## 3. 当前 canonical public contract

长期 public surface 保持：

```text
retrieve(request)
investigate(...)
verify(...)
list_capabilities()
```

Integration transport：

```text
project(result, profile=...)
```

`retrieve()` typed targets：

```text
SourceTarget
QueryTarget
RangeTarget
ProviderTarget
```

兼容接口：

```text
probe
search
expand
sample
survey
...
```

兼容接口可以保留，但不应继续成为不同 Agent host 各自复制业务语义的入口。

---

## 4. Router 决策继续保留

Core 保留：

```text
DIRECT -> BOUNDED -> INVESTIGATE
```

Router 只负责：

> evidence transport cost / risk routing

禁止 Router：

- 推断 root cause；
- 给 hypothesis 排名；
- 根据 benchmark case 名称做特判。

### DIRECT

对安全、足够小、尚未一次性暴露过的 source：

```text
lossless line-addressable raw evidence
```

多个 tiny source 在 aggregate direct budget 内可以继续 DIRECT。

### BOUNDED

搜索 + 有界 materialization，控制返回规模，同时保留 recovery。

### INVESTIGATE

仅在大、高基数、多源、深探索场景启用机械：

```text
frontier
correlation
grouping
reduction
coverage/progress
context budget
```

INVESTIGATE 仍然不做 RCA。

---

## 5. 本轮重新审视后发现的结构性问题

这部分是本轮减法重构的直接输入。

### P0-1：Agent 入口没有完全统一到 canonical retrieve/investigate

目前 Runtime 已有 adaptive `retrieve()`，但部分 CLI / integration 路径仍直接调用低层 `tools.search()` / `tools.expand()`，再自行 compact。

风险：

```text
同一个 TraceCite
Python host / CLI / benchmark / MCP
可能得到不同 routing / integrity / projection 行为
```

目标：

> Agent-facing 主入口统一到 canonical `retrieve()/investigate()`；旧低层工具只保留兼容和内部 primitive 用途。

### P0-2：Projection 层职责越界

当前 `agent_projection -> evidence_fidelity` 已经会：

```text
打开 source
SHA 校验
扫描附近行
扫描 source 做 scoped identity verification
```

Projection 本应只负责 transport view，不应该成为第二个 Evidence Runtime。

目标：

```text
Runtime:
发现 / materialize / integrity

Projection:
canonical -> JSON / compact JSON / frame
```

**Projection 最终不得通过文件 I/O 发现新的 Evidence。**

### P0-3：Materialization 存在重复实现

目前至少存在：

```text
tools.expand()
DIRECT query 自己读取完整 source
evidence_fidelity 自己扫描 source/附近行
```

它们都在做 pointer/source -> raw evidence recovery。

目标：

> 收敛成一个 materialization primitive；`RangeTarget / expand` 是稳定底座，上层 Context Resolver 只决定需要恢复哪个边界。

### P0-4：Retrieval `outcome` 语义错误

Schema 明确定义：

```text
status = 工具执行状态
outcome = epistemic result
```

但当前 `search()` 有命中时会返回 `outcome=supported`，`expand()` 也固定返回 `supported`。

“搜到字符串/成功读到原文”并不等于“某个 hypothesis 被支持”。

目标：

```text
search / expand / survey / probe
=> outcome = not_assessed（或在确实无法评估时 unknown）

只有 assertion / explicit proposition verification
=> supported / contradicted
```

### P0-5：Identity contract 没有完全贯穿 provider -> correlation

已有 `EvidenceIdentity` 正确地区分：

```text
record identity != event identity != group identity
```

但 Provider / Orchestrator 仍大量直接使用 `EvidenceNode.id` 作为 investigation 级全局 key。

Provider 只保证 local ID 在单 provider 内唯一，因此不同 provider 都出现 `id="123"` 时不应该被当成同一个 record。

目标：

```text
record identity
= provider/source namespace
+ source version
+ local record id
```

### P0-6：Entity scope 不能靠事后 ambiguity helper 才补救

当前 `EntityRef.key = (namespace, kind, value)`，exact key 会被 correlation 视为 `same_entity`。

如果某个 ID 只在 resource/session/tenant scope 内唯一，而 provider 没把 scope 编进 identity domain，就可能产生错误 join。

目标：

> scoped identity 必须优先在 Entity identity contract 表达；ambiguity/integrity detector 是防线，不是主身份模型的替代品。

### P0-7：Grouping 不能 normalize away entity identity

`grouping.normalize_template()` 会归一化 UUID/hex/number，这对重复日志压缩有价值，但可能把：

```text
resource-3083
resource-5477
```

折成一个模板。

如果数字属于实体身份，这种折叠不能导致 identity diversity 消失。

目标：

```text
message payload 可以 normalize
entity identity 不允许被 normalize 掉
```

### P0-8：Evidence Gap 已有正式模型，但当前表现分裂

目前同类 integrity 状态可能分别出现在：

```text
ambiguity_hints
identity_verification
evidence_integrity.scoped_identity
missing_evidence
```

Runtime 又已经有正式：

```text
EvidenceGap
EvidenceRequirement
EvidenceProgressTracker
```

目标：

```text
IntegrityObservation
      ↓
EvidenceGap
      ↓
Minimal Retrieval Requirement
      ↓
Progress actionable_gaps
```

Gap 只能说明“哪块证据尚未闭合”，不能声明 root cause。

---

## 6. 明显需要合并/淘汰的重复设计

### 6.1 多套 seen/context state

当前存在：

```text
EvidenceProgressTracker
ContextEngine
EvidenceContextEngine
InvestigationState execution history
```

长期目标只保留两个 owner：

```text
RetrievalSession
- seen evidence/windows/source versions
- novelty
- coverage
- retrieval progress

InvestigationState
- question
- hypothesis
- test
- finding
- execution audit
```

`ContextEngine` / `EvidenceContextEngine` 的能力应逐步合并到统一 RetrievalSession，而不是继续并行扩展。

### 6.2 多套 Agent compact/projection

当前存在：

```text
agent_projection.project()
CLI _compact_search_result()
CLI _fit_expand_many_result()
AgentProfile / frame encoder
```

目标拆成两层：

```text
Projection:
canonical result -> bounded semantic view

Encoder:
JSON / columnar JSON / frame
```

Projection 只做字段/预算/重复信息裁剪，不获取新 Evidence。

### 6.3 两套 investigate facade

Runtime 与 Integrations 都存在相邻 `investigate()` facade。

长期只保留 canonical：

```text
runtime.investigate()
```

Agent package 改由：

```text
project(investigation_result, profile=...)
```

生成。

### 6.4 SourceSession 当前实现过重

SourceSession 概念可以保留，但当前通过 monkey patch 扩展 `InvestigationState` 的方式长期不理想。

目标收敛为正式版本化：

```text
SourceDescriptor / SourceSession
= SourceVersion + format + segmenter + recognition metadata
```

---

## 7. 本轮目标架构：唯一主链

最终主链收敛为：

```text
Raw Source / Provider
        ↓
Canonical Identity
        ↓
Discover
Query -> EvidencePointer
        ↓
Materialize
Pointer -> EvidenceWindow
        ↓
Evidence Integrity
ambiguity / contradiction / missing link / scoped identity
        ↓
EvidenceGap（如存在）
        ↓
Minimal Retrieval Action（如需要）
        ↓
Agent-visible Evidence
        ↓
Agent hypothesis / RCA
```

外围统一由：

```text
Router
DIRECT / BOUNDED / INVESTIGATE

RetrievalSession
coverage / novelty / progress / stop
```

控制。

### 7.1 `expand` 的长期定位

保留并强化，不废弃：

> **`RangeTarget / expand` 是 raw Evidence materialization 的底层 primitive。**

上层未来可以有 Context Resolver：

```text
普通 log -> ±N lines
YAML      -> record boundary
JSON      -> object boundary
stack     -> thread / stack block
```

但真正读取、hash 校验、line qualification、max_chars、coverage 必须走统一 materializer。

---

## 8. Correlation / Grouping / Reduction 的边界

这些能力不是删除，而是降为 INVESTIGATE 内部机械算法。

### Correlation

只描述 observable/deterministic relation。

需要避免：

- local ID 被错误当作 global identity；
- temporal-near 与 exact-entity 在 downstream retention ranking 中被当作等价 hop。

### Grouping

只压缩重复模式，不改变 provenance / entity diversity。

### Reduction

只能决定 transport retention，不得表达 root-cause relevance。

内部 `score` 更准确的语义应该是：

```text
retention_priority
```

Agent 不需要看到一个容易被理解为“根因概率”的裸分数。

Severity (`panic/error/timeout/...`) 只允许作为 truncation insurance / navigation signal，不作为 root-cause ranking。

---

## 9. 已经落地、必须保留的能力

### Fidelity-first DIRECT

- tiny unseen source 可以 lossless line-addressable 暴露；
- 多 tiny sources aggregate 在 budget 内可以继续 DIRECT；
- 同一 source 不重复 raw dump；
- source changed / over budget 时保守降为 BOUNDED。

### Focused no-harm gate

3 个重点 case：

```text
flutter-179398
mobile-payment-runtime-evidence
kubernetes-140268-scale
```

### Full 16 paired no-harm gate

硬条件：

```text
shell pass -> TraceCite fail
=> workflow fail
```

### Scoped identity / structured evidence 实验结论

已确认：

- `140268` 早期失败确实存在 structured leaf 丢 parent/sibling context 的问题；
- scoped identity gap 可以机械检测；
- 但这些逻辑不应该继续堆在 Projection，必须回收到 Runtime canonical evidence flow。

---

## 10. 最新真实模型事实

### Mobile Payment

最近多轮修复后可以恢复到 TraceCite PASS；说明 fidelity-first small multi-source DIRECT 是正确方向。

历史一次清晰结果：

```text
free_shell input: 19,955
TraceCite input: 13,715
两边 quality: 1.0
```

不能据此宣称所有小 case 都省 token，只能证明该 case no-harm 已修复且成本合理。

### Flutter

真实模型存在波动；近期既出现 shell/TC 同为 0.50，也出现 shell PASS / TC FAIL。

因此仍必须按 no-harm gate 处理，不能把所有失败都解释成随机波动。

当前主要风险是 Agent 把“memory corruption”进一步具体化为 evidence 尚未证明的 `use-after-free`。

### Kubernetes 140268

free-shell 仍容易 context overflow；TraceCite 能控制上下文，但 RCA 仍未稳定正确。

当前已确认：

- `Unhealthy` failure diff 可以被找到；
- `resourceID=testdevice` 可以被暴露；
- sibling scoped resources 可以被观察到；
- scope uniqueness gap 可以被提示/验证；
- Agent 仍可能过早选择 timeout/propagation timing hypothesis。

这说明下一步不能继续简单堆更多 raw context；需要把 evidence integrity / gap / materialization 主链收干净，避免 transport metadata 与因果显著性混在一起。

---

## 11. 本轮实施顺序

### Phase A — P0 semantic cleanup

1. 修正 retrieval `outcome` 语义；
2. 把文件 I/O / identity verification 从 Projection 移回 Runtime；
3. 统一 search -> materialize -> integrity 的 canonical 结果；
4. 保证 `project(profile="full")` 与 canonical Runtime 完全一致；
5. Agent projection 不再发现新 Evidence。

### Phase B — Entry path convergence

1. Agent-facing CLI / benchmark host 优先通过 `retrieve()`；
2. legacy direct `tools.search/expand` 只做兼容；
3. contract tests 证明不同 host 的 canonical semantics 一致。

### Phase C — Identity safety

1. provider record IDs namespaced；
2. scoped entity identity contract；
3. grouping 保留 entity diversity；
4. correlation/reducer relation-strength no-harm。

### Phase D — State simplification

1. 设计统一 RetrievalSession；
2. 合并 ContextEngine / EvidenceContextEngine；
3. InvestigationState 只保留 reasoning/audit state；
4. SourceSession 正式 schema 化。

Phase D 在 A/B correctness 稳定后再做，避免一次改太多状态语义。

---

## 12. 本轮测试/验收标准

### Gate 0 — deterministic

必须全部通过：

```text
Core tests
Python 3.10-3.14
macOS
architecture governance
schema compatibility
Evidence Intelligence deterministic benchmark
```

### Gate 1 — semantic contract

新增/保持：

- search/expand retrieval 不声明 hypothesis `supported`；
- Projection 无文件 I/O；
- canonical/full projection 不变；
- compact view 所有 omission 可恢复；
- local ID 不会因 provider 冲突被错误合并；
- grouping 不丢 entity diversity。

### Gate 2 — focused real-model no-harm

必须检查：

```text
Mobile
Flutter
140268
```

硬规则仍为 shell pass -> TC fail 不允许。

### Gate 3 — full 16 paired

Focused 稳定后重新跑完整 16-case × 2 arms。

重点检查：

- no-harm regression count = 0；
- 4 个 scale TraceCite context overflow = 0；
- `140848` 等 scale 优势没有被重构显著破坏；
- 小 case 不出现数量级 token/tool-round 放大。

---

## 13. 禁止事项

本轮不得：

- 为 `140268` / Flutter 写 case-specific 特判；
- 修改 gold 来适配当前答案；
- 降低 scorer threshold；
- 用模型输出反向硬编码 root cause；
- 为了测试变绿把大日志重新 raw dump；
- 把 RCA / hypothesis ranking 搬进 Core；
- 在 Core 稳定前先让 Mobile/MCP 复制新的内部 API。

---

## 14. Core 稳定后的 Mobile / MCP 顺序

```text
Core contract stable
        ↓
更新本文档最终测试事实
        ↓
同步 core for_agent
        ↓
Mobile for_agent 适配
        ↓
MCP for_agent 适配
        ↓
contract / integration tests
```

Mobile / MCP 只消费稳定的：

```text
retrieve / investigate / project / capability
```

不复制 Router / Integrity / grouping/reducer 内部逻辑。

---

## 15. 当前一句话结论

> **TraceCite 当前最重要的工作不是增加更多“聪明规则”，而是把已经证明有价值的 evidence access、materialization、integrity、context control 收敛成唯一主链：小 evidence 尽量像 shell 一样真实直接，大 evidence 继续 bounded 且不崩，任何中间层都不能让 Agent 比直接看 raw evidence 更容易得出错误答案。**
