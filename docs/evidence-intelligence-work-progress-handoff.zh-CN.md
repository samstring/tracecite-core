# Evidence Intelligence 工作进度与交接

> 本文档是 `experiment/evidence-intelligence` 分支当前工作的权威交接记录。旧聊天、旧实验记录和旧进度文件仅作为历史；出现冲突时，以本文档较新的决策和最新测试事实为准。

更新时间：2026-08-29

## 1. 当前工作基线

- 仓库：`samstring/tracecite-core`
- 当前工作分支：`experiment/evidence-intelligence`
- 基础分支：`refactor/agent-v2`
- Evidence Intelligence 继续只在实验分支开发；没有明确确认前不合并基础分支。
- 当前阶段重点不是继续把日志规模无限放大，而是验证：
  1. Agent 正确性不能因为 TraceCite 介入而下降；
  2. 小/简单 evidence 不应被重型 investigation 干扰；
  3. 大/高噪 evidence 仍应保持 bounded context 的优势；
  4. Core public contract 要稳定，使 Mobile / MCP / 第三方无需跟随内部实现频繁改动。

---

## 2. 产品定位与新的最高优先级

TraceCite **不是**：

- 通用代码搜索器；
- `rg` / grep 替代品；
- Elasticsearch / Splunk / Observability 存储平台；
- 自治 Agent / LLM planner；
- 自动 root-cause 推理器。

当前定位继续保持：

> **TraceCite 是面向 AI Agent 的 Evidence Runtime / Evidence Control Plane。**

Agent 继续负责：

```text
hypothesis
causal reasoning
root-cause conclusion
fix proposal
```

TraceCite 负责：

```text
evidence access
+ bounded retrieval
+ provenance
+ versioned identity
+ source/range recovery
+ correlation/grouping
+ context control
+ coverage/progress
+ novelty
+ deterministic stop
+ evidence integrity
```

### 2.1 No-Harm 是硬约束

本轮 16-case A/B 暴露出一个必须优先处理的问题：某些小/中等 case 中，free-shell Agent 可以答对，而 TraceCite Agent 因 evidence transport / selection / projection 的介入反而答错。

因此正式确定以下优先级：

> **Correctness > Evidence Fidelity > Token Saving**

硬规则：

```text
free_shell passed == true
AND
tracecite passed != true

=> TraceCite no-harm regression
=> 验收失败
```

Token/context 节省不能抵消这种正确性退化。

TraceCite 可以为了保真多给 Agent 一些证据，但不能通过压缩、排序、摘要或机械选择把原本可正确推理的 Agent 带向错误答案。

---

## 3. 16-case A/B 已确认的基线事实

当前统一矩阵为 16 个唯一 case × 2 arms = 32 个 Agent runs。

普通 case：

```text
doublecmd-2264
doublecmd-2616
doublecmd-2731
doublecmd-2772
doublecmd-2777
doublecmd-2809
doublecmd-2815
doublecmd-3061
flutter-179398
mobile-payment-runtime-evidence
prometheus-18018
pulumi-20529
```

Scale case：

```text
kubernetes-140039-runc-5347
kubernetes-140268
kubernetes-140628
kubernetes-140848
```

上一轮完整 paired run：`33199132708`。

### 3.1 大 evidence 的价值已经成立

4 个 scale case 中，free-shell 有 3 个发生 `context_window_exceeded`，TraceCite 0 个 context overflow。

`kubernetes-140848` 是最清晰的同质量 A/B：

- free-shell dimension recall：0.75；
- TraceCite dimension recall：0.75；
- 两边 marker recall：1.0；
- free-shell input tokens：1,126,926；
- TraceCite input tokens：244,202；
- input 减少约 78.3%；
- tool output 减少约 87.6%；
- cumulative attempted context 减少约 77.9%；
- peak context 减少约 85.1%。

因此已经有真实模型证据支持：

> **大规模、高噪 evidence 下，TraceCite 的 bounded evidence flow 可以显著降低 model-visible context，并避免 shell exploration 的 context collapse。**

这个结论继续成立；本轮 fidelity-first 改造不能破坏它。

### 3.2 小/中等 evidence 的 no-harm 问题

上一轮明确出现：

#### `flutter-179398`

- free-shell：PASS，concept recall = 0.75；
- TraceCite：FAIL，concept recall = 0.50。

#### `mobile-payment-runtime-evidence`

- free-shell：PASS，concept recall = 1.0；
- TraceCite：FAIL，concept recall = 0.6667；
- free-shell input tokens：13,143；
- TraceCite input tokens：88,943。

该 case 说明 TraceCite 不仅成本更高，而且丢失/弱化了完整事件链，使 Agent 没能完整连接 pay action、background transition、timeout、release、late callback、crash。

#### `kubernetes-140268`

- free-shell：`context_window_exceeded`，没有完成答案；
- TraceCite：完成调查，但 root cause 错误，dimension recall = 0.0；
- evidence marker recall = 1.0；
- citation accuracy = 1.0。

这说明该 case 的主要问题不是“完全搜不到相关 evidence”，而是 Agent 在 TraceCite 提供的 evidence view 上形成了错误因果结论。真实根因是 device ID 只在 resource scope 内唯一，但 lookup 只按 device ID 匹配；正确修复需要把 resource name 纳入 identity / lookup scope。

本轮不能通过修改 gold、降低 threshold 或放宽 scorer 来“修复”这些失败。

---

## 4. 现有 Router 保留，不重新造一套

Core 已经有：

```text
DIRECT -> BOUNDED -> INVESTIGATE
```

实现位于：

```text
src/tracecite/runtime/evidence_routing.py
```

Router 的职责继续严格限定为：

> **evidence transport cost / risk routing，不做 diagnosis。**

不新增第二套复杂 router，不引入基于 16 个 case 过拟合的 ML/打分模型。

### 4.1 本轮发现的实际问题

此前 DIRECT 的限制过强：

- 只有 investigation 的第一次本地 source retrieval 容易走 DIRECT；
- 一旦 history 中出现多个 source 或若干 execution，就快速进入 BOUNDED / INVESTIGATE；
- 对 Mobile Payment 这种由 5 个极小 JSON evidence 文件组成的 incident，即使全部 raw evidence 合计仍很小，也可能过早进入更重的 machinery。

同时，此前 `QueryTarget` 即使被 Router 判定为 DIRECT，底层仍主要返回 search EvidencePointer / label；Agent 往往还要额外调用 `get` 才能看到精确上下文。

这与 free-shell 的 `rg -n -C` / 直接阅读相比，会增加工具轮次，并可能弱化普通但关键的事件顺序。

---

## 5. DIRECT 的新语义：fidelity-first raw access

本轮正式把 DIRECT 收敛为：

> **对安全、足够小、尚未暴露过的本地 source，给 Agent 一次无损、line-addressable 的 raw evidence view；不做因果总结，不做 root-cause 排名。**

### 5.1 多个小 source 可以继续 DIRECT

不再因为 `source_count > 1` 就立即认为必须进入重型 investigation。

Router 现在估算：

```text
已经一次性 DIRECT 暴露过的唯一 source
+
当前新 source
```

其合计 fully line-addressable raw representation 是否仍在 `direct_char_budget` 内。

若仍在预算内：

```text
unseen source -> DIRECT
```

因此多个很小的 Mobile evidence 文件可以各自无损暴露一次，而不必因为“文件数量多”被机械升级。

### 5.2 同一 source 不重复 raw dump

DIRECT 是一次性的 fidelity path，不是重复倾倒路径。

```text
第一次 unseen small source -> DIRECT raw
再次查询相同 source      -> BOUNDED / INVESTIGATE
```

这样同时满足：

- 简单 case 不丢信息；
- 同一 raw source 不会每轮重复进入模型上下文。

### 5.3 DIRECT QueryTarget 也保留 raw ordering

`src/tracecite/runtime/retrieve_contract.py` 新增 DIRECT Query 行为：

1. 正常执行 canonical search，保留 EvidencePointer / Coverage；
2. 对同一稳定 source 做 SHA 校验；
3. 若 Router 已证明 aggregate raw 在 DIRECT budget 内，则把完整 source 以：

```text
filename:line raw text
```

形式放入 Agent-visible result；
4. 标记：

```text
direct_raw.fidelity = lossless_line_addressable
```

因此 Agent 不需要只依赖 selected labels 推断一个简单 incident 的时间/状态顺序。

如果 source 在 search 后改变、读取失败、或实际 raw representation 超过 budget，则不能伪装成 DIRECT；会保守退回 BOUNDED。

---

## 6. BOUNDED / INVESTIGATE 的大日志能力保持

本轮不是把所有 evidence 都改成 raw dump。

大/高噪 source 仍然使用原有：

```text
bounded search
max_evidence
max_line_chars
survey
signal hints
novelty
coverage
progress
recovery
```

因此目标曲线明确为：

```text
small/simple:
TraceCite ≈ shell
重点是不伤害 Agent

medium:
TraceCite bounded retrieval
减少重复 exploration

large/noisy:
TraceCite INVESTIGATE / bounded evidence flow
防止 context collapse
```

为了正确性，在 BOUNDED / INVESTIGATE 中允许适当多返回一些必要上下文；但不允许重新退化成把几十 MB raw evidence 直接塞给模型。

---

## 7. Evidence selection / hints 的边界

`evidence_selection.py` 中的 severity hints 继续只允许做：

```text
navigation hints
```

例如：

```text
panic
fatal
error
timeout
```

它们不能自动升级为 root-cause evidence，更不能直接暗示“timeout 就是根因”。

正式边界：

- hint 不等于事实结论；
- hint 不等于 root cause；
- hint 必须可以通过 RangeTarget / get 恢复到原始 source line；
- canonical Evidence / source identity / line recovery 必须保留；
- Agent 自己完成最终 causal reasoning。

后续若继续增强 contradiction / ambiguity / evidence-gap，也只能作为风险/导航信息，不能成为 Core 自动 root-cause engine。

---

## 8. Public API 继续保持稳定

长期 public surface 不变：

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

`retrieve()` typed target：

```text
SourceTarget
QueryTarget
RangeTarget
ProviderTarget
```

旧的：

```text
probe
search
expand
sample
survey
...
```

继续兼容，不要求上层为每个 Core 内部能力新增 RPC / enum / tool。

### 8.1 investigate() 的严格边界

允许 deterministic mechanical work：

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

禁止：

```text
LLM hypothesis
root-cause ranking
causal conclusion
```

---

## 9. Evidence Progress / Stop / Identity 决策继续有效

Evidence Progress 描述：

> “Evidence acquisition 已经进行到哪里”，不是“root cause 是否已经找到”。

正式概念继续包括：

```text
EvidenceRequirement
EvidenceGap
EvidenceDelta
EvidenceReadiness
EvidenceProgressTracker
CoverageStatus
ReadinessStatus
```

`ready` 只表示 caller-supplied mechanical evidence requirements 已满足，不表示 root-cause conclusion 为真。

Stop 继续只描述 evidence acquisition：

```text
NO_NEW_EVIDENCE
SOURCE_EXHAUSTED
FRONTIER_EXHAUSTED
BUDGET_EXHAUSTED
PROVIDER_UNAVAILABLE
SOURCE_CHANGED
```

Stop 不能等价于“root cause found”。

Evidence identity 继续区分：

```text
record identity
!= event identity
!= group identity
```

以及 versioned source identity：

```text
path + SHA256
cursor
generation
mutable
```

这些设计都不因本轮 DIRECT 调整而改变。

---

## 10. Mobile / MCP 影响

本轮不要求重新设计 Mobile。

Mobile 继续负责：

```text
iOS / Android evidence collection
session / stream
seal / archive
crash / behavior / performance / network evidence
保留完整原始 evidence
```

Core 负责：

```text
DIRECT / BOUNDED / INVESTIGATE
```

Agent 负责：

```text
reasoning / root cause
```

所以整体关系保持：

```text
Mobile / MCP / Provider
        ↓
完整、可恢复 Evidence
        ↓
TraceCite Core retrieve/investigate
        ↓
DIRECT / BOUNDED / INVESTIGATE
        ↓
Agent reasoning
```

上层最多需要跟随 stable `retrieve/project/capability` contract 做轻量适配，不应复制 Core routing logic。

---

## 11. 本轮已落地代码

### `src/tracecite/runtime/evidence_routing.py`

- DIRECT 改为 fidelity-first one-time exposure；
- history 正式跟踪 unique source paths；
- 新增 aggregate line-addressable char estimation；
- 多个 unseen tiny source 只要 aggregate raw 仍在 direct budget 内，就允许继续 DIRECT；
- same-source 重复查询不再重复 raw dump；
- large/high-cardinality/deep exploration 的升级逻辑继续保留。

关键 commit：

```text
70a309a refactor(evidence): keep safe unseen sources on direct path
```

### `src/tracecite/runtime/retrieve_contract.py`

- DIRECT `QueryTarget` 新增 lossless line-addressable raw view；
- canonical search pointer / coverage 仍保留；
- raw view 与 search source SHA 做一致性验证；
- source changed/read unavailable/raw over budget 时保守退回 BOUNDED；
- BOUNDED / INVESTIGATE 仍保持原有限制。

关键 commit：

```text
eedf913 feat(evidence): expose lossless raw context on direct query
```

### `tests/test_evidence_routing.py`

新增覆盖：

- DIRECT query 保留完整 raw ordering；
- 5 个 tiny unseen source 在 aggregate budget 内都保持 DIRECT；
- 同一 source 第二次 query 不重复 DIRECT raw；
- 原有 large/deep/high-cardinality routing 回归继续保留。

关键 commit：

```text
4d7eb77 test(evidence): cover fidelity-first direct routing
```

### `benchmarks/agent-investigation/aggregate_runnable_pairs.py`

新增：

```text
no_harm_passed
no_harm_regression_count
no_harm_regressions
quality_degradations
```

关键 commit：

```text
2a79a5b test(bench): enforce no-harm quality regression signal
```

### `tests/test_runnable_pair_aggregate.py`

新增 no-harm aggregate gate 单元测试。

关键 commit：

```text
9eb1724 test(bench): cover no-harm aggregate gate
```

### `.github/workflows/evidence-runnable-16-paired-retry.yml`

- 运行时相关代码变化会自动触发 16-case paired validation；
- aggregate 阶段硬性执行 no-harm gate；
- `free_shell pass -> TraceCite non-pass` 会使 workflow 失败；
- stale paired validation 使用 `cancel-in-progress: true`，只保留最新 revision，避免浪费模型额度。

关键 commits：

```text
f8e56a2 ci(bench): gate paired run on TraceCite no-harm
5584371 ci(bench): keep only latest paired validation
```

### `tests/test_gmi_canonical_host.py`

新增要求：真实 canonical benchmark host 的 DIRECT search 必须实际把 lossless raw evidence 暴露给 Agent，而不是仅 Core 内部结构存在。

关键 commit：

```text
2f29b4b test(bench): require direct raw evidence fidelity in host
```

### `.github/workflows/evidence-no-harm-regression.yml`

新增 focused 模型回归：

```text
flutter-179398
mobile-payment-runtime-evidence
kubernetes-140268-scale
```

3 个 case 并行，继续使用同一 canonical Agent loop / model / seed / provider retry；TraceCite arm 必须通过。

关键 commit：

```text
4118541 ci(bench): add focused no-harm regression
```

---

## 12. 当前测试状态（2026-08-29）

### 12.1 Core CI

针对本轮 DIRECT / no-harm 改造的 Core CI：

```text
run: 33234830784
```

结果：**PASS**。

通过矩阵：

```text
Ubuntu Python 3.10
Ubuntu Python 3.11
Ubuntu Python 3.12
Ubuntu Python 3.13
Ubuntu Python 3.14
macOS Python 3.14
```

architecture governance、schema compatibility、全部 Core tests 均通过；Python 3.14 build 也通过。

### 12.2 Evidence Intelligence deterministic benchmark

```text
run: 33234830748
```

结果：**PASS**。

Correlation/reduction、deterministic exploration 及 Evidence Intelligence tests 均通过。

### 12.3 Focused no-harm model regression

```text
workflow: Evidence No-Harm Regression
run: 33234902353
cases: flutter / mobile-payment / kubernetes-140268
```

文档本次更新时状态：**in progress**。

不得在 run 完成前宣称 3 个历史失败已经修复。

### 12.4 Full 16 paired A/B

```text
workflow: Runnable 16 Paired A/B Retry
run: 33234830787
head under test: 5584371226c67059c0e12b7c427400eaecb451e1
```

文档本次更新时状态：第一 paired job 已开始，其余按 `max-parallel: 1` 排队。

该 run 使用与上一轮相同的 paired Agent 原则，并新增 no-harm hard gate。

---

## 13. 本轮验收标准

本轮不是追求“TraceCite 每个 case token 都更小”。正式验收顺序：

### P0 — Correctness / No-Harm

```text
free_shell 能 pass 的 case
=> TraceCite 不允许变成 fail
```

这是硬门槛。

### P1 — Evidence Fidelity

DIRECT small evidence：

- exact raw source 可见；
- line-addressable；
- provenance / SHA 可恢复；
- 不用 summary 替代原始时序；
- 不允许 hint 冒充 root cause。

### P2 — Small-case overhead

小 case 应尽量接近 shell，不再因为重复 search/get/investigation machinery 出现数量级放大。

### P3 — Scale robustness

4 个 scale case：

```text
TraceCite context_window_exceeded = 0
```

必须继续保持。

### P4 — Scale efficiency

在同等质量下，继续确认大 evidence 的 model-visible context / input token 优势没有因 fidelity-first 改造被显著破坏。

---

## 14. 下一步

当前只按测试事实推进：

1. 等 focused 3-case model regression 给出结果；
2. 若 Flutter / Mobile 仍出现 `shell pass -> TC fail`，继续定位具体 tool call / evidence view 分叉，不降低 threshold；
3. 若 `140268` 仍错，重点比较 Agent 实际可见的 identity/scope/ordering evidence，优先补 evidence fidelity / recoverability，不给 Kubernetes 加 root-cause 特判；
4. 完成 full 16 paired run，检查 no-harm gate、普通 case token、4 个 scale context robustness；
5. 将最终模型结果补回本文档；
6. 只有 Core 方案稳定后，再评估 Mobile / MCP 是否需要轻量适配；当前不做上层大改。

---

## 15. 当前一句话结论

> **TraceCite 的下一阶段不是让 Core 更会“猜根因”，而是让 Agent 在简单 evidence 下尽量直接看到真实事实，在复杂 evidence 下获得 bounded、可恢复、不会带偏的事实；正确性是底线，Token 优化建立在这条底线之上。**
