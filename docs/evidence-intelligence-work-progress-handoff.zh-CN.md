# Evidence Intelligence 工作进度与交接

> 本文档是 `experiment/evidence-intelligence` 分支当前工作的权威交接记录。旧聊天、旧实验记录和旧进度文件仅作为历史；出现冲突时，以本文档较新的决策和最新测试事实为准。

更新时间：2026-08-29

## 1. 当前工作基线

- 仓库：`samstring/tracecite-core`
- 当前工作分支：`experiment/evidence-intelligence`
- 基础分支：`refactor/agent-v2`
- 本轮减法重构开始前 HEAD：`e43c0cb8605992e1f9b2b2871a1571069e30b85a`
- Phase A focused 真模型验证代码提交：`c778fc518dad10aa5c2aa54aec4a87400e8084a0`
- Phase A 最新 deterministic 修正后 HEAD：`3e0155402fd5b7571b59c2f2a6e3b1c3ee045512`
- 未经明确确认，不合并到基础分支。
- Core 稳定前，不改 Mobile / MCP 上层业务设计。

当前工作仍停留在 **Phase A**：deterministic gate 已通过，但 focused real-model gate 尚未闭合，因此不能进入 Phase B。

---

## 2. 产品定位与不可破坏的不变量

TraceCite 定位为：

> **面向 AI Agent 的 Evidence Runtime / Evidence Control Plane。**

TraceCite 不是：

- `rg` / grep 替代品；
- 通用代码搜索器；
- Elasticsearch / Splunk / Observability 存储平台；
- 自治 Agent / LLM planner；
- 自动 Root Cause Analysis 系统。

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
evidence fidelity
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

Token 节省、tool output 减少、context 更小都不能抵消正确性退化。

### 2.2 三个核心卖点必须继续成立

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

不能出现“被省略后无法恢复”的事实。

---

## 3. Canonical public contract

长期 public surface：

```text
retrieve(request)
investigate(...)
verify(...)
list_capabilities()
project(result, profile=...)
```

`retrieve()` typed targets：

```text
SourceTarget
QueryTarget
RangeTarget
ProviderTarget
```

`probe/search/expand/sample/survey/...` 可以作为兼容接口和内部 primitive 保留，但不同 Agent host 不应在这些低层工具之上各自复制一套 routing / integrity / projection 语义。

---

## 4. 目标主链

Core 最终收敛为一条主链：

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
coverage / seen / novelty / progress / stop
```

控制。

### 4.1 Router 边界

保留：

```text
DIRECT -> BOUNDED -> INVESTIGATE
```

Router 只负责 evidence transport cost / risk routing，禁止：

- 推断 root cause；
- 给 hypothesis 排名；
- 根据 benchmark case 名称特判。

### 4.2 `expand` / materialize 长期定位

`RangeTarget / expand` 保留并强化：

> **它是 raw Evidence materialization 的底层 primitive。**

未来 Context Resolver 可以决定天然边界：

```text
普通 log -> ±N lines
YAML      -> record boundary
JSON      -> object boundary
stack     -> thread / stack block
```

真正读取、hash 校验、line qualification、max_chars、coverage 应收敛到统一 materializer。

---

## 5. 已确认的结构性问题

### P0 — 必须优先解决

1. **Agent 入口未完全统一**：部分 CLI / integration 仍直接使用低层 `tools.search()/expand()` 并自行 compact。
2. **Projection 曾职责越界**：Agent projection 曾打开 source、补结构上下文、扫描 scoped identity；这些语义必须归 Runtime。
3. **Materialization 重复**：`tools.expand()`、DIRECT full-source read、fidelity/source scan 存在重复读取实现。
4. **Retrieval epistemic outcome 语义错误**：搜索命中/成功读取不能等于 hypothesis `supported`。
5. **Provider record identity 未全局 namespaced**：不同 provider 的 local `id="123"` 不应碰撞。
6. **Scoped entity identity 未进入主身份 contract**：只在 resource/session/tenant 内唯一的 ID 不能默认全局 same-entity。
7. **Grouping 可能 normalize away entity identity**：payload 数字/UUID 可归一化，但实体身份差异不能丢。
8. **EvidenceGap 表现分裂**：`ambiguity_hints / identity verification / evidence_integrity / missing_evidence` 应收敛为正式 gap/progress 语义。

### P1 — P0 稳定后收敛

1. 多套 seen/context state：`EvidenceProgressTracker / ContextEngine / EvidenceContextEngine / InvestigationState execution history`。
2. 多套 Agent compact/projection：`agent_projection / CLI compact / frame encoder`。
3. 两套相邻 investigate facade。
4. Correlation 的 exact relation 与 weak temporal relation 对 downstream retention 影响区分不足。
5. Reducer 的 severity/graph score 可能形成不必要的 root-cause salience。
6. SourceSession 通过 monkey patch 扩展状态的方式长期过重。

长期只保留两个状态 owner：

```text
RetrievalSession
- seen evidence/windows/source versions
- novelty / coverage / progress

InvestigationState
- question / hypothesis / test / finding
- execution audit
```

---

## 6. Correlation / Grouping / Reduction 边界

这些能力不删除，但只作为 INVESTIGATE 内部机械算法。

### Correlation

只描述 observable/deterministic relation；local ID 未确认 uniqueness domain 时不得提升成全局 same-entity。

### Grouping

只压缩重复模式，不改变 provenance / entity diversity。

```text
message payload 可以 normalize
entity identity 不允许被 normalize 掉
```

### Reduction

只能决定 transport retention，不得表达 root-cause relevance。

内部 `score` 的真实语义应接近：

```text
retention_priority
```

Severity (`panic/error/timeout/...`) 只允许作为 truncation insurance / navigation signal，不能包装成 cause likelihood。

---

## 7. 已经落地、必须保留的能力

### Fidelity-first DIRECT

- tiny unseen source 可以 lossless line-addressable 暴露；
- 多 tiny sources aggregate 在 budget 内可以继续 DIRECT；
- 同一 source 不重复 raw dump；
- source changed / over budget 时保守降为 BOUNDED。

### Structured evidence fidelity

已确认搜索只返回孤立 leaf 会损失语义；例如 `health: Unhealthy` 必须能够恢复其所属 record / entity / ID 上下文。

### Scoped identity integrity

已存在 bounded、SHA-stable verifier，可表达：

```text
scope_uniqueness_unverified
uniqueness_unverified_with_sibling_scope_fanout
```

它只能指出 correlation 缺口，不能声明 ID reuse 或 root cause。

### Citation parser correctness

`build-log.txt:84522` 这类 evidence input 引用有效；`kubeletconfig.go:186` 这类源码位置不再被误算为 evidence citation。没有降低 scorer threshold。

---

## 8. Phase A — Runtime owns evidence semantics

### 8.1 已完成代码

Phase A 已完成以下代码收敛：

- `project(profile="agent")` 不再负责打开/扫描 source 来发现新 Evidence；
- structured search fidelity 搬回 canonical `retrieve()` Runtime；
- scoped identity integrity 搬回 Runtime；
- identity gap 接入 canonical `missing_evidence` / `progress.actionable_gaps`；
- `search/expand` 的 public retrieval epistemic outcome 改为 `not_assessed`，不再把“找到/读到”包装成 hypothesis `supported`；
- 不恢复旧的重复 `data.identity_verification` alias，canonical representation 使用 `data.evidence_integrity.scoped_identity`；
- 保证 `RetrievalResult.to_dict()` 的 delta/new-evidence view 与 enriched canonical evidence 同步；
- 新增回归：raw search payload 直接 `project()` 不得偷偷读文件；public `retrieve()` 在 projection 前已包含 fidelity/integrity/gap 信息。

### 8.2 Deterministic Gate

Phase A 第一次 Core CI 出现 2 个旧 contract 断言失败：

- 旧测试仍要求 `data.identity_verification`；
- signal hint 文案仍要求旧措辞。

没有恢复重复设计，而是更新到新的 canonical contract。

当前最新 HEAD `3e0155402fd5b7571b59c2f2a6e3b1c3ee045512`：

- Core CI：通过；
- Ubuntu Python 3.10-3.14：通过；
- macOS Python 3.14：通过；
- Evidence Intelligence deterministic benchmark：通过。

**结论：Phase A deterministic gate 已完成。**

### 8.3 Focused real-model Gate — run `33240333967`

此 run 对应 Phase A 代码提交 `c778fc518dad10aa5c2aa54aec4a87400e8084a0`。

#### Mobile Payment

```text
free_shell:
  passed = true
  quality = 1.0
  input_tokens = 7,532
  model_calls = 4
  tool_calls = 8

TraceCite:
  passed = true
  quality = 1.0
  input_tokens = 5,760
  model_calls = 2
  tool_calls = 5
```

本轮 TraceCite input 比 shell 少 1,772，约 23.5%。

**结论：PASS/PASS；小多源 evidence 的核心卖点没有在 Phase A 退化。**

#### Flutter 179398

```text
free_shell:
  passed = false
  quality = 0.5
  input_tokens = 276,875

TraceCite:
  passed = null
  host_failure_reason = provider_insufficient_balance
```

TraceCite arm 没有得到可评分 final，因此本轮 **不能用于判定 TraceCite correctness**。同时 shell 本轮自身也只有 0.5，所以这一 run 不是 `shell PASS -> TC FAIL` 的 no-harm regression。

**结论：inconclusive；需要后续有效 provider run。**

#### Kubernetes 140268 scale

```text
free_shell:
  passed = null
  host_failure_reason = context_window_exceeded

TraceCite:
  passed = false
  dimension_recall = 0.0
  supported_dimension_recall = 0.0
  evidence_marker_recall = 1.0
  input_tokens = 244,813
  model_calls = 14
  tool_calls = 27
```

Agent 已经看到了两个 marker：

```text
device-plugin-failures-3083
device-plugin-failures-5477
```

但仍没有形成正确因果链。free-shell 再次 context overflow，证明 TraceCite 的大日志 bounded-context 卖点仍然存在；但“能完成”不能替代 correctness。

本轮不是 `shell PASS -> TC FAIL`，因为 shell 没有完成；但 focused workflow 明确要求 TraceCite 自身通过该 target，因此 gate 仍失败。

**结论：大日志 context control 保持，但 RCA correctness 未闭合。**

### 8.4 Phase A 当前判定

```text
Deterministic gate: PASS
Focused Mobile: PASS
Focused Flutter: INCONCLUSIVE (provider balance)
Focused 140268: FAIL
```

因此：

> **Phase A 不能标记为完整通过，也不能开始 Phase B。**

下一步仍属于 Phase A remediation：继续分析 `140268` 的 canonical evidence/gap/action 链，确认为什么 Agent 已经拿到 marker 和 scoped-identity gap 后仍会 premature-close；修复必须是通用 Evidence Runtime 行为，禁止加入 Kubernetes/case/gold 特判。

Flutter 需要在 provider 可用时取得有效 TraceCite arm，不能把 balance failure 当成模型失败或模型成功。

---

## 9. 当前真实模型事实（跨历史 run）

### Mobile Payment

多轮可恢复到 PASS/PASS，说明 fidelity-first small multi-source DIRECT 方向成立。历史一轮：

```text
free_shell input = 19,955
TraceCite input = 13,715
quality = 1.0 / 1.0
```

不能据此宣称所有小 case 都省 token。

### Flutter

真实模型存在波动；历史既有 shell/TC 同 0.5，也有 shell PASS / TC FAIL，因此必须持续按 no-harm gate 检查。

当前主要风险：Agent 会把 evidence 只支持的 broader memory corruption 过度具体化成尚未证实的 `use-after-free` / dangling-pointer mechanism。

### Kubernetes 140268

已确认：

- `Unhealthy` failure diff 可以找到；
- structured parent/sibling context 可以恢复；
- `resourceID=testdevice` 可以暴露；
- sibling scoped resources 可以观察；
- scope uniqueness gap 可以提示/验证；
- marker recall 可以达到 1.0；
- Agent 仍可能提前选择 timeout/propagation timing hypothesis。

因此不能继续简单堆 raw context；需要让 EvidenceGap / minimal mechanical retrieval / progress/stop 真正闭环，同时保持 Agent 自己负责 RCA。

---

## 10. 历史完整 16-case 基线

权威历史 run：`33199132708`，SHA `7b6bdc556974268af8aee1cac9c65cad5487d8cc`。

13 个 valid paired outcomes 聚合：

```text
free_shell input = 1,292,903
TraceCite input = 656,225
aggregate reduction ≈ 49.24%
```

但这个数字被 `kubernetes-140848` 大幅主导，**不得宣传成一般场景平均节省 49%**。

更重要的分布：

```text
median per-case reduction = -0.767573
=> median case TraceCite 约多 76.8% input

ordinary 12:
free_shell 165,977
TraceCite 412,023
=> TraceCite +148.24%

ordinary both-pass 10:
free_shell 64,499
TraceCite 100,932
=> TraceCite +56.49%
```

Scale 价值仍明确：

- `140848` ~14.5MB：两边质量 0.75，TraceCite input 约减少 78.33%；
- `140628` ~67.4MB：shell overflow，TraceCite pass；
- `runc` ~2.29MB：shell overflow，TraceCite pass 0.75；
- `140268` ~24.2MB：shell overflow，但 TraceCite correctness 仍未解决。

---

## 11. 后续阶段顺序

**必须遵守：每完成一个阶段，先更新并提交本文档，再开始下一阶段。**

### Phase A — 当前阶段

状态：**进行中 / focused gate 未闭合**。

剩余：

1. 修复/验证 140268 暴露出的通用 evidence-gap closure 问题；
2. 取得有效 Flutter TraceCite focused run；
3. deterministic gate；
4. focused 3-case gate；
5. 更新并提交本文档；
6. 只有以上完成后才能开始 Phase B。

### Phase B — Entry path convergence

尚未开始。

计划：

1. Agent-facing CLI / benchmark host 优先通过 `retrieve()`；
2. legacy direct `tools.search/expand` 只做兼容；
3. contract tests 证明不同 host 的 canonical semantics 一致；
4. deterministic + focused；
5. 更新并提交本文档。

### Phase C — Identity / grouping safety

尚未开始。

计划：

1. provider record IDs namespaced；
2. scoped entity identity contract；
3. grouping 保留 entity diversity；
4. correlation/reducer relation-strength no-harm；
5. deterministic + focused；
6. 更新并提交本文档。

### Phase D — State simplification

在 A/B/C correctness 稳定后再做：

1. 统一 RetrievalSession；
2. 合并 ContextEngine / EvidenceContextEngine；
3. InvestigationState 只保留 reasoning/audit state；
4. SourceSession 正式 schema 化；
5. deterministic + focused；
6. 更新并提交本文档。

### Final Gate

Focused 稳定后：

1. 完整 16-case × free-shell / TraceCite；
2. no-harm regression count 必须为 0；
3. 4 个 scale TraceCite context overflow 必须为 0；
4. `140848` 等 scale 优势不能被显著破坏；
5. 小 case 不允许数量级 token/tool-round 放大；
6. 更新并提交本文档；
7. Core 稳定后再适配 Mobile / MCP `for_agent`。

---

## 12. 禁止事项

不得：

- 为 `140268` / Flutter 写 case-specific 特判；
- 修改 gold 来适配当前答案；
- 降低 scorer threshold；
- 用模型输出反向硬编码 root cause；
- 为了测试变绿把大日志重新 raw dump；
- 把 RCA / hypothesis ranking 搬进 Core；
- 把 severity/error/timeout 包装成 cause likelihood；
- Core 稳定前让 Mobile/MCP 复制新的内部 API。

---

## 13. Core 稳定后的 Mobile / MCP 顺序

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

## 14. 当前一句话结论

> **Phase A 已完成 deterministic semantic cleanup，但真实 focused gate 尚未闭合：Mobile 证明小 evidence no-harm/成本合理，140268 再次证明大日志 context control 的价值，同时暴露 evidence gap 已可见但调查仍会 premature-close；在这个 correctness 问题和 Flutter 有效 focused run闭合前，不进入下一阶段。**
