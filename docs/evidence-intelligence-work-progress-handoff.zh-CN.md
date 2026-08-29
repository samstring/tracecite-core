# Evidence Intelligence 工作进度与交接

> 本文档是 `experiment/evidence-intelligence` 分支当前工作的权威交接记录。旧聊天、旧实验记录和旧进度文件仅作为历史；出现冲突时，以本文档较新的决策和最新测试事实为准。

更新时间：2026-08-29

## 1. 当前工作基线

- 仓库：`samstring/tracecite-core`
- 当前工作分支：`experiment/evidence-intelligence`
- 基础分支：`refactor/agent-v2`
- 本轮减法重构开始前 HEAD：`e43c0cb8605992e1f9b2b2871a1571069e30b85a`
- Phase A deterministic cleanup 基线：`3e0155402fd5b7571b59c2f2a6e3b1c3ee045512`
- Phase A scoped-identity / sibling-family remediation：`b6ecb1c9c75962e324554987d219d9416b76913e`
- Phase B public CLI convergence：`d36f11e3394cebfd567cd93a8eae154fa42c8739`
- Phase C grouping entity-diversity：`85a08179ce66373f2b4272bfe1b89de2e6a1608d`
- Phase C provider namespace：`08a57547b38bb8f462ec7c43b4088f3848438955`
- Phase C relation-strength / reducer gate：`d722a1f31e4b55250625cdf5dd6be10d52ef000b`
- Phase D canonical RetrievalSession：`76dd2566a80571c83d47495d61c692ea7d5cfe9e`
- Phase D shared Context ownership：`83940d0e3f95c31ee56c0fcd5f4f9cf224220c8b`
- Phase D retrieval progress ownership gate：`08fb8f1a2b77ca8740e7327f52481cc5ab5f150c`
- 本轮 correctness-first 调查闭环代码基线（本文档更新前）：`cbeb4a34e9829ee1b98ff79ead7ee894ad31defc`
- 未经明确确认，不合并到基础分支。
- Core correctness 未闭合前，不推进 Mobile / MCP 上层同步。

当前阶段：**Correctness-first Investigation/Test Evidence Closure。Phase D 的结构收敛先暂停扩面，优先关闭 Kubernetes 140268 的真实 correctness 缺口。**

### 1.1 当前最高优先级

用户已明确：

> **先不要怕 API 的变动，主要是要保证正确性。**

因此当前设计原则调整为：

```text
Correctness
  > Evidence Fidelity / Integrity
  > API compatibility / 少改上层
  > Token Saving
```

允许为正确的调查契约修改 `InvestigationState / Hypothesis / Test / Finding` 相关 API；不能为了兼容旧调用习惯保留会产生错误结论的路径。

### 1.2 Focused gate 历史豁免与当前状态

2026-08-29 早期曾明确允许 focused real-model gate 暂不过，以便 A -> B -> C -> D 的 deterministic 重构继续推进。

该豁免只表示“阶段转换不被 focused 阻塞”，从未表示 focused PASS，也没有取消 no-harm / Final Gate。

现在已经确认 Kubernetes 140268 暴露的是 **Runtime correctness capability incompleteness**，因此当前主动回到 focused correctness 主线，不再继续把它当作单纯实验债务往后推。

---

## 2. 产品定位与不可破坏的不变量

TraceCite 定位为：

> **面向 AI Agent 的 Evidence Runtime / Evidence Control Plane。**

TraceCite 不替代：

- `rg` / grep；
- 通用代码搜索；
- Elasticsearch / Splunk / Observability storage；
- 自治 Agent / LLM planner；
- 自动 Root Cause Analysis。

Agent 负责：

```text
problem understanding
hypothesis generation
causal reasoning
test intent / expected observation / falsifier
root-cause interpretation
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
investigation state
mechanical evidence-sufficiency enforcement
```

No-Harm 规则保持：

```text
free_shell passed == true
AND tracecite passed != true
=> no-harm regression
```

Token 节省、tool output 变小、context 不 overflow 都不能抵消 correctness 退化。

---

## 3. Canonical public contract

长期 evidence public surface 仍以：

```text
retrieve(request)
investigate(...)
verify(...)
list_capabilities()
project(result, profile=...)
```

为主。

`retrieve()` typed targets：

```text
SourceTarget
QueryTarget
RangeTarget
ProviderTarget
```

但 Investigation 层现在确认必须拥有更强的 epistemic contract：

```text
Hypothesis
  -> Test
  -> linked Retrieval / Evidence
  -> Test Assessment
  -> Finding
```

`probe/search/expand/sample/survey/...` 可继续作为兼容接口和内部 primitive，但 Agent-facing host 不应在这些低层工具上复制 routing / integrity / projection / epistemic closure 语义。

目标主链更新为：

```text
Raw Source / Provider
  -> Canonical Identity
  -> Discover / Materialize
  -> Evidence Integrity
  -> EvidenceGap
  -> Minimal Retrieval Action
  -> Agent Hypothesis
  -> Agent-declared Test
  -> Evidence-backed Test Assessment
  -> supported / contradicted / unknown
  -> Finding gate
```

Router 只允许管理：

```text
DIRECT -> BOUNDED -> INVESTIGATE
```

禁止 Router 或 Runtime 注入 benchmark root cause、按 case 特判、或者把 mechanical retrieval score 当 cause likelihood。

---

## 4. 已确认的结构风险

### 4.1 已处理的 P0/P1

- Agent public entry 已收敛到 typed `retrieve()`；
- Projection 不再打开 source 发现新 Evidence；
- retrieval success 不再等于 hypothesis `supported`；
- scoped identity integrity 已进入 canonical Runtime；
- Provider record identity 已在 public Runtime boundary namespaced；
- grouping 已保留 exact entity identity；
- weak relation 与 exact identity relation 已在 retention path 中区分；
- reducer score 已明确标注为 retention priority，不是 cause likelihood；
- ContextEngine / EvidenceContextEngine 不再分别拥有独立 seen-state；
- retrieval novelty / covered ranges 不再以 InvestigationState executions 作为主状态 owner；
- **Test Assessment 已成为 evidence-backed 的正式 Runtime contract；**
- **decisive Finding 已增加 Test assessment hard gate。**

### 4.2 当前最高风险：Claim-relative evidence sufficiency

Kubernetes 140268 证明：Runtime 过去能判断“某个 identity retrieval gap 是否还有下一步机械动作”，但不能充分判断：

> **当前这个 Hypothesis / Claim 是否已经有足够证据，可以交付 decisive Finding？**

这两个问题不是一回事。

现有 scoped-identity ladder 可以正确完成：

```text
identifier = testdevice
-> local identifier
-> identifier-only correlation unsafe
-> preserve scope
-> sibling scoped entities observed
```

但它在 identity 子问题完成后会结束 mechanical identity retrieval；这并不意味着 root-cause Claim 已被证明。

Kubernetes 140268 真正还缺第二层：

```text
Unhealthy event
  -> routed target / PodUID
  -> target belongs to which scoped entity
  -> expected target vs actual target
  -> correct pod stale until later sync
```

因此当前核心缺口可概括为：

> **Identity Gap 已能识别；Causal / Relationship Gap 没有被继续传播到 Claim-level evidence sufficiency。**

---

## 5. Phase A — Runtime owns evidence semantics

状态：**deterministic COMPLETE。**

已落地：

- Agent projection 不再打开 source 发现新 Evidence；
- structured search fidelity 移入 canonical Runtime；
- scoped identity integrity 移入 Runtime；
- identity gap 接入 `missing_evidence` / progress；
- public retrieval outcome 使用 `not_assessed`；
- actionable gap 可提升为 `data.actionable_retrieval`；
- local ID 明确携带 `identifier_only_correlation_safe=false`；
- identifier search 可推进到 observed scoped entity，再推进到 Runtime-observed sibling family；
- canonical benchmark host 可要求 Agent 优先执行 Runtime actionable retrieval；
- 没有加入 Kubernetes / Flutter / gold 特判。

早期 focused 仍未闭合，因此 Phase A 的 deterministic 完成不等于 real-model correctness 完成。

---

## 6. Phase B — Entry path convergence

状态：**deterministic COMPLETE。**

已完成：

- Canonical benchmark host 使用 typed `EvidenceRequest` + `retrieve()`；
- public `tracecite` entrypoint 默认 search -> `QueryTarget` -> `retrieve()`；
- public expand -> `RangeTarget` -> `retrieve()`；
- `search --output-path` 仅作为明确 legacy side-effect fallback 保留；
- ContextEngine / ledger projection 仍在 Runtime result 之后工作；
- contract tests 防止 public CLI 再绕回 low-level semantic owner。

历史 Gate：

```text
Core CI run 33246863204: PASS
Evidence Intelligence benchmark run 33246863162: PASS
```

---

## 7. Phase C — Identity / grouping safety

状态：**deterministic COMPLETE。**

### 7.1 Provider record identity

不同 Provider 可以同时返回相同 local `id`，甚至相同 source-native `evidence_uri`；canonical Runtime 已将 record identity 收敛为：

```text
provider name + provider-local id
-> canonical provider://<provider>/<record-id>
```

source-native URI 仅作为 provenance metadata 保留。

### 7.2 Grouping entity diversity

旧 grouping key：

```text
(source, kind, normalized_template)
```

新 grouping identity：

```text
(source, kind, normalized_template, exact_entity_signature)
```

因此同一 exact entity 的重复消息仍可压缩，不同 entity 不会因模板 normalization 被错误折叠。

### 7.3 Relation strength / reducer semantics

事实层 `CorrelationGraph` 保持中立，不加入 cause weight。

Reducer 仅使用 mechanical retention path cost，且明确：

```text
score_semantics = retention_priority
```

不得把 score 当 root-cause probability。

历史 Gate：

```text
Core CI run 33247276940: PASS
Evidence Intelligence benchmark run 33247276942: PASS
```

---

## 8. Phase D — State simplification

状态：**Retrieval/context state ownership 子阶段 deterministic 已闭合；后续结构收敛暂缓扩面，优先 correctness。**

### 8.1 RetrievalSession / context ownership — COMPLETE

Runtime-owned：

```text
RetrievalSessionState
RetrievalSessionStore
```

统一管理：

```text
revision
seen_evidence
seen_results
seen_groups
seen_relations
covered_ranges
source_complete
```

迁移结果：

- `ContextEngine` / `EvidenceContextEngine` 不再各自拥有独立 state schema；
- 两个 projection engine 共用 canonical `_contexts/<id>.json`；
- Retrieval progress 的 seen Evidence + covered ranges 已从 InvestigationState execution replay 拆出；
- InvestigationState executions 保留 audit/reproducibility，不再作为 retrieval novelty 主状态；
- 旧 investigation 可从 executions 回放一次并迁移 progress sidecar。

历史 Gate：

```text
HEAD 08fb8f1a2b77ca8740e7327f52481cc5ab5f150c
Core CI run 33247711104: PASS
Evidence Intelligence benchmark run 33247711129: PASS
```

### 8.2 原计划的剩余 Phase D

原计划继续：

1. SourceSession schema / monkey-patch 收敛；
2. compact/projection owner 收敛；
3. investigate facade 去重复。

当前这些不是最高优先级。除非是为 correctness 修复所必需，否则先不继续纯结构整理。

---

## 9. Kubernetes 140268：当前 correctness blocker

### 9.1 Benchmark 要求

问题只允许使用提供的约 24MB CI build log，需要回答四个 root-cause dimensions：

1. `failure_localization`
2. `immediate_failure_mechanism`
3. `upstream_contributor`
4. `fix_alignment`

通过阈值包括：

```text
dimension_recall >= 0.75
supported_dimension_recall >= 0.75
citation_accuracy >= 0.5
unsupported_claim_hits == 0
contradiction_hits == 0
```

### 9.2 Upstream ground truth

Kubernetes PR `#140323` 的实际修复是：

> `kubelet: fix device health updates being routed to the wrong pod when device IDs collide across resources`

实际机制：

- 旧 `getPodAndContainerForDevice` 按 **device ID alone** 在 pods/resources 中查找；
- device ID 只保证在单一 resource 内唯一，不保证跨 resource 唯一；
- 不同 resource 可以同时暴露同一个 `testdevice`；
- Go map iteration 使错误命中具有非确定性；
- `genericDeviceUpdateCallback` 因此可能通知错误 Pod；
- `syncLoop` 同步错误 Pod；
- 正确 Pod 的 `allocatedResourcesStatus` 继续保持旧的 Healthy，直到下一次 periodic sync；
- e2e 每个 spec 都用 `testdevice`，但 resource name 随机化，因此相邻 spec 可在同节点发生冲突。

修复方向：

```go
- getPodAndContainerForDevice(deviceID)
+ getPodAndContainerForDevice(resourceName, deviceID)
```

也就是 lookup key 必须保留 scope：

```text
resourceName + deviceID
```

CI log 中存在直接证据：

- `test.device/device-plugin-failures-3083` 进入 Unhealthy；
- health/sync 事件却指向前一 spec `device-plugin-failures-5477` 的 PodUID；
- 正确 Pod 在超时后下一次 periodic sync 才变成 Unhealthy。

### 9.3 Focused #4：旧 canonical host 的失败事实

Run：`33253981796`

Flutter：PASS。

Kubernetes：FAIL。

```text
TraceCite run_status = ok
passed = false
dimension_recall = 0.25
supported_dimension_recall = 0.25
evidence_marker_recall = 1.0
citation_accuracy = 10 / 22 = 0.4545
unsupported_claim_hits = 0
contradiction_hits = 0
```

四个 dimension 中只有：

```text
failure_localization = hit
```

其余：

```text
immediate_failure_mechanism = miss
upstream_contributor = miss
fix_alignment = miss
```

旧 final answer 实际错误收敛到了：

```text
CI load / timing / race / reconciliation delay / timeout too short
```

并建议延长或重试 60s wait。

这不是单纯 scorer regex mismatch，而是错误 root-cause conclusion。

---

## 10. Root design diagnosis：不是顶层架构错误，是 Runtime capability incompleteness

当前结论：

> **TraceCite 的顶层架构方向没有被推翻；问题发生在 Runtime 对“证据是否足以支持当前 Claim”的能力不完整。**

过去 Runtime 主要能回答：

```text
这个 retrieval / identity gap 是否还有下一步 deterministic action？
```

但 decisive Finding 真正需要回答：

```text
Agent 当前声明的 Hypothesis / Claim，是否已经满足它自己声明的证据要求？
```

正确闭环应该是：

```text
Hypothesis / Claim
    ↓
Agent declares Test / expected observation / falsifier
    ↓
Evidence requirements
    ↓
existing Evidence
    ↓
Missing / conflicting Evidence
    ↓
retrieval
    ↓
Test Assessment
    ↓
re-evaluate Claim
    ↓
supported / contradicted / unknown
```

关键架构边界：

- Runtime **不能**变成 Kubernetes root-cause reasoner；
- Runtime **不能**因为 benchmark gold 里有 `5477` 就硬搜 `5477`；
- Runtime **不能**自己决定“CI load hypothesis 应该验证哪些 Kubernetes 专有事实”；
- Agent 负责 hypothesis 和 semantic Test；
- Runtime 负责记录 Test、绑定 Evidence、验证 assessment、阻止无证据 decisive Finding；
- Runtime 可以继续提供 generic identity / provenance / correlation-safety mechanical requirements。

---

## 11. 本轮 correctness-first 修复：Test / Finding evidence contract

### 11.1 核心规则

本轮决定：

> **Test 本身就是 Agent 声明的 Evidence Requirement，不再额外造一套重复 requirement schema。**

每个 Test 必须显式得到一次 assessment：

```text
supported
contradicted
unknown
```

决定性 Finding：

```text
supported / contradicted
```

现在会被 Runtime 拒绝，如果存在：

- declared Test 未评估；
- Test assessment 为 `unknown`；
- assessment 与 requested Finding outcome 冲突；
- `supported / contradicted` assessment 没有绑定可验证 Evidence。

证据不足时允许、并要求使用：

```text
Finding(outcome = unknown)
```

而不是把“搜不到更多”“超时”“retrieval ladder 结束”升级成 root cause proof。

### 11.2 主要实现提交

```text
e86bdc5 feat(evidence): add evidence-backed test assessment
fe33862 feat(evidence): require assessed tests before decisive finding
e86ce01 test(evidence): cover test-assessment finding gate
17eb7ef feat(runtime): expose test assessment contract
0ae77de test(evidence): validate assessment evidence contract
b84af34 test(investigation): assess declared test before finding
f01d192 test(summary): assess test before decisive finding
5c9c25b test(knowledge): require assessed finding evidence
```

新增核心文件：

```text
src/tracecite/runtime/test_assessment.py
```

并接入：

- Runtime public export；
- Finding validation；
- Investigation lifecycle；
- Summary / Knowledge candidate 流程；
- deterministic tests。

### 11.3 兼容性决策

新 hard gate 初次接入后，旧测试中有 16 处沿用：

```text
search -> decisive Finding
```

而没有显式 Test Assessment，因此失败。

处理方式：

> **没有为了兼容旧测试放宽新规则；而是把旧测试改成正确的 `Test -> assess -> Finding` 流程。**

这符合当前 correctness-first 决策。

---

## 12. Evidence-contract benchmark host

新增：

```text
benchmarks/agent-investigation/gmi_evidence_contract_host.py
```

主要提交：

```text
4df300e feat(benchmark): enforce evidence-contract investigation loop
bde5c07 test(benchmark): cover evidence-contract host closure
76df6f8 fix(benchmark): expose canonical evidence refs for assessment
3525a90 test(benchmark): cover late-linked evidence closure
a11f567 fix(benchmark): keep canonical refs visible on repeated evidence
```

它保留现有 canonical retrieval / identity / coverage 行为，只新增显式调查动作：

```text
tracecite_hypothesis
tracecite_test
tracecite_assess_test
tracecite_finding
tracecite_state
```

并允许：

```text
tracecite_inspect/search/get(..., hypothesis_id=?, test_id=?)
```

将 retrieval 结果正式挂到 Test。

### 12.1 Canonical Evidence ref

Agent-facing projection 过去经常表现为：

```text
uri_base + #L2
```

人可以拼回完整 Evidence URI，但让模型做 strict Test Assessment 容易出错。

Host 现在额外显式输出：

```text
@EVIDENCE_REF evidence://sha256/...#L...
```

并保证：即使 Evidence 在早期自由探索时已经见过，后续为某个 Test 再 retrieval 时，仍可获得并绑定 canonical Evidence ref。

### 12.2 Epistemic closure

只要还没有 Finding：

```text
tool_choice = required
```

模型不能跳过调查状态直接输出 final prose。

当 mechanical retrieval 因 no-growth / max-round 到达上限但仍没有 Finding 时：

- 停止继续 retrieval；
- 不允许直接把“没有更多 Evidence”写成 decisive conclusion；
- 只保留 epistemic closure tools：

```text
hypothesis
test
assess_test
finding
state
```

如果证据不足，应正式关闭为 `unknown`。

### 12.3 Paired runner host 选择

提交：

```text
2da80c2 feat(benchmark): allow explicit investigation host selection
c8c747f test(benchmark): validate paired retry host selection
```

`run_paired_retry.py` 现在可显式选择 host；默认仍保持 canonical host，避免其他 benchmark 被静默改写。

Focused workflow 单独指定 evidence-contract host。

---

## 13. 最新 deterministic gate

代码基线：`cbeb4a34e9829ee1b98ff79ead7ee894ad31defc`

```text
Core CI run 33257219671: PASS
Evidence Intelligence Benchmark run 33257219678: PASS
```

说明：

- Test Assessment hard gate 已能通过完整 Core matrix；
- architecture governance / schema compatibility 未因本轮 correctness-first 改动失守；
- evidence-contract host 自身的 deterministic tests 已进入 Core CI；
- deterministic PASS **不等于** Kubernetes real-model correctness PASS。

---

## 14. Focused rerun #5：最新真实模型结果

Run：`33257219670`

HEAD：`cbeb4a34e9829ee1b98ff79ead7ee894ad31defc`

模型：`MiniMaxAI/MiniMax-M3`

本轮首次让 focused Flutter + Kubernetes 都通过：

```text
gmi_evidence_contract_host.py
```

### 14.1 Flutter 179398

状态：**PASS**

```text
free_shell:
  run_status = ok
  passed = true
  primary_quality = 1.0

TraceCite:
  run_status = ok
  passed = true
  primary_quality = 1.0
```

因此 evidence-contract 调查闭环没有破坏当前 Flutter 修复。

### 14.2 Kubernetes 140268

状态：**FAIL / unresolved**

```text
free_shell:
  run_status = ok
  passed = false
  primary_quality = 0.25

TraceCite:
  run_status = ok
  passed = false
  primary_quality = 0.0
```

结论必须保持严格：

- evidence-contract host **没有解决** Kubernetes 140268；
- 本轮 TraceCite primary root-cause quality 从 focused #4 的 `0.25` 变成 `0.0`；
- 不能把“新增 Test/Finding gate”描述成 correctness repair 已成功；
- 它目前只证明 **错误结案路径可以被结构化约束**，但尚未证明 **关键 causal Evidence 能被成功找出并形成正确 Finding**；
- #5 artifact / transcript 还需要进一步逐轮分析，才能判断 `0.0` 是因为正确降级成 unknown、Test 设计不充分、retrieval 没拿到 causal relation，还是其它 host interaction 问题。

Artifact：

```text
focused-kubernetes-140268-repair-v2
artifact id = 9716285380
```

在分析 artifact 前，不对 #5 的 0.0 原因做猜测。

---

## 15. 当前下一步（按优先级）

### P0 — 分析 focused #5 Kubernetes artifact

必须读取：

```text
tracecite/transcript.jsonl
tracecite/score.json
tracecite/outcome.json
canonical-investigation.json（若 artifact 中保留）
pair.json
```

要回答：

1. Agent 实际创建了哪些 Hypothesis？
2. 每个 Hypothesis 创建了哪些 Test / expected observation / falsifier？
3. 哪些 retrieval 真正挂到了 Test？
4. Test Assessment 是 supported / contradicted / unknown？
5. Runtime 是否成功阻止 unsupported decisive Finding？
6. `primary_quality=0.0` 的 final answer 到底是 unknown、漏掉 dimensions、还是产生了另一种错误结论？
7. causal evidence（wrong PodUID / cross-scope target / periodic sync）有没有被 materialize？

### P1 — 如果 causal Evidence 仍未 materialize，补 generic gap propagation

不要写 Kubernetes 特判。

优先考虑 generic mechanism：

```text
observed event / relation
  -> target identifier
  -> resolve target identifier to scoped entity
  -> compare source scope / target scope
  -> emit Observation / EvidenceGap
  -> deterministic next relation/target frontier
```

或继续强化：

```text
Agent-declared Test
  -> unmet evidence requirement
  -> Runtime tracks coverage
  -> unresolved Test blocks decisive Finding
```

需要至少两个不同 domain / synthetic shape 的 deterministic tests，证明能力不是为 Kubernetes 140268 单点过拟合。

### P2 — 重新验证 citation accuracy

focused #4 中：

```text
citation_accuracy = 0.4545 < 0.5
```

若下一轮 root-cause dimensions 恢复/提高，仍需单独检查 citation scorer；不能把 citation failure 混在 causal correctness 里。

### P3 — Focused gate

只有 Flutter + Kubernetes TraceCite correctness 都 PASS，才进入：

```text
full Final Gate
```

### P4 — Full Final Gate / no-harm

必须重新跑并报告：

1. runnable 16 cases × free-shell / TraceCite；
2. no-harm regression count；
3. 4 个 scale context overflow；
4. Kubernetes 140848 scale 优势；
5. ordinary cases 的 token/tool-round overhead；
6. Flutter / Kubernetes 140268 correctness closure。

历史 16-case 基线：

```text
13 valid paired aggregate:
free_shell input = 1,292,903
TraceCite input = 656,225
aggregate reduction ≈ 49.24%
```

该 aggregate 被 Kubernetes 140848 大幅主导，不能宣传为普通 case 的平均 49% token reduction。

### P5 — 结构收敛 / merge / Mobile / MCP

只有 correctness + Final Gate 达到可接受状态后，再决定：

```text
继续 Phase D SourceSession/projection cleanup
-> merge into refactor/agent-v2
-> 更新 core for_agent
-> Mobile for_agent
-> MCP for_agent
```

---

## 16. Core 稳定后的 Mobile / MCP

顺序保持：

```text
Core contract stable
 -> 更新最终测试事实
 -> 同步 core for_agent
 -> Mobile for_agent
 -> MCP for_agent
 -> contract / integration tests
```

Mobile / MCP 只消费稳定的 public contract，不复制 Router / Integrity / grouping / reducer / investigation state owner 内部逻辑。

当前允许 Core API 为 correctness 发生较大调整，因此 **不要提前让 Mobile/MCP 锁死尚未稳定的 Investigation API**。

---

## 17. 新对话接手顺序

新对话优先读取：

1. 本文档；
2. `docs/architecture.zh-CN.md`；
3. `src/tracecite/runtime/test_assessment.py`；
4. `src/tracecite/runtime/finding_validation.py`；
5. `src/tracecite/runtime/investigation.py`；
6. `benchmarks/agent-investigation/gmi_evidence_contract_host.py`；
7. `benchmarks/agent-investigation/gmi_canonical_host.py`；
8. `src/tracecite/runtime/retrieval_guidance.py`；
9. `src/tracecite/runtime/evidence_ambiguity.py`；
10. focused #5 Kubernetes artifact / transcript。

不要从旧聊天里猜当前状态；以本文档 + branch HEAD + 最新 CI / artifact 为准。

---

## 18. 当前一句话结论

> **TraceCite 的顶层 Evidence Runtime 架构方向仍成立，但 Kubernetes 140268 已证明 Runtime 缺少“相对于当前 Hypothesis/Test 的证据充分性与 causal gap propagation”能力。本轮已把 Test 升级为 Agent 声明的 Evidence Requirement，并加入 evidence-backed Test Assessment + decisive Finding hard gate，同时用 evidence-contract host 强制真实 Agent 走 Hypothesis -> Test -> Evidence -> Assessment -> Finding 闭环。deterministic Core/benchmark 已 PASS，Flutter focused #5 也 PASS；但 Kubernetes 140268 在 focused #5 仍 FAIL，TraceCite primary quality 为 0.0。因此 correctness 尚未关闭，下一步首先分析 #5 artifact，再决定 generic causal relation/target retrieval 机制；在此之前不进入 Final Gate、merge 或 Mobile/MCP 同步。**
