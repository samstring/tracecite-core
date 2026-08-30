# Evidence Runtime 重构工作计划与验收清单

> 本文档是 `experiment/evidence-intelligence` 分支当前重构工作的**唯一执行清单**。
>
> 规则：**先更新本文档，再修改代码；每个工作项必须有明确验收证据。**
>
> 本轮允许 breaking refactor：不使用 `v2` 命名，不保留仅为历史兼容而存在的不合理 API/schema/semantics。新的模型落地后即成为唯一模型。

相关权威文档：

- 架构：`docs/evidence-runtime-architecture.zh-CN.md`
- Guardrails：`docs/PROJECT_GUARDRAILS.md`
- 历史交接：`docs/evidence-intelligence-work-progress-handoff.zh-CN.md`

---

## 0. 当前目标

把 TraceCite 从“多套半重叠 investigation/retrieval 状态 + 局部 Agent guidance”收敛为：

> **一个纯粹的 Evidence Runtime + 稳定 Host Integration Contract + Evidence-aware Evaluation Contract。**

最终解决此前所有主要问题：

- repeated Evidence 重复发送；
- current query 命中 old Evidence 但 relevance 丢失；
- Agent 忘记旧 Evidence 无法回读；
- 大文件 context dump；
- Agent 在 `139417/140268` 中深挖不收敛；
- Agent 在 `140039/139417` 中切回 `bash/grep/read` 绕过 TraceCite telemetry；
- `140268` 等 case 的 direct evidence / inference / unsupported 边界混淆；
- Benchmark hidden truth 诱导过度断言；
- 429/overload 污染 A/B；
- Core API 频繁影响 Pi/MCP/Mobile；
- Token 优化与 correctness 目标错位。

---

## 1. 已确认实验事实

以下事实是本轮重构的设计输入，不得因后续单次随机 run 被随意推翻。

### 1.1 `140039`

历史 TraceCite 3 轮约：

```text
14 / 17 / 25 tools
```

加入 `session_progress` 后的新单轮：

```text
30 tools
TraceCite search = 2
bash = 15
grep = 8
read = 4
```

结论：

> 只观察 TraceCite retrieval 无法观察完整 Agent trajectory；Agent 可以切回 native tools 继续深挖。

### 1.2 `139417`

历史 TraceCite 3 轮：

```text
83 / 95 / 107 tools
全部 timeout
```

新 `session_progress` 单轮：

```text
84 tools
TraceCite search/expand = 44
native bash/read = 40
600s timeout
```

Agent 已看到近 10 次 retrieval 中大量 repeated/no-match，仍继续。

结论：

> Passive retrieval telemetry 本身不足以让 Agent 收敛；低 novelty 不是 stop conclusion；Host 必须能观察整条 trajectory，但 Core 不应替 Agent决定停止。

### 1.3 `140848`

历史观测到明显 trajectory variance：

- TraceCite 有正常 31/35-tool completion；
- 也出现 74-tool 深挖；
- Native 也曾出现 75-tool / 600s timeout。

结论：

> 深挖不是 TraceCite 独有；不能用 benchmark-specific prompt 把 Agent 固定到 preferred path。

### 1.4 `140268`

历史 3×A/B：Native/TraceCite 6/6 timeout。

TraceCite 很早返回：

```text
identifier_only_correlation_safe=false
minimum_safe_correlation_key=...
source_uniqueness=unverified
observed sibling entities
```

但 supplied log 不能直接证明 deeper internal lookup implementation。

结论：

> Identity safety fact 是正确 Core 能力；deeper cause/fix 必须允许 inference / unsupported boundary，不能逼 Agent 在日志中寻找不存在的直接证明。

### 1.5 Provider contamination

多轮出现 429 / overloaded。

结论：

> task success 与 clean A/B validity 必须分开。

---

## 2. 总体执行顺序

按以下顺序执行，不跳阶段：

```text
A. 删除越界语义
B. 统一 RetrievalSession owner
C. 重建 canonical Evidence API
D. 收敛 traversal/routing/selection
E. Host Observation Contract
F. Evaluation Contract
G. Adapter / docs 收敛
H. 4-case 单轮验证
I. 稳定性 repeated A/B
J. 再同步 MCP / Mobile
```

在 H 之前不宣称“已经改善”。

---

# A. 删除 Runtime 越界语义

状态：**COMPLETE**

## A1. 删除 EvidenceProgress 的 epistemic/stop 字段

目标删除：

```text
ready_for_reasoning
readiness
stop_recommended
```

以及所有隐含：

```text
no growth => should stop
requirements satisfied => investigation complete
```

允许保留：

```text
new_evidence
new_lines
new_entities
new_relations
source_complete
scope_exhausted
frontier_exhausted
consecutive_no_growth
coverage_status
```

若 acquisition 被硬限制终止，使用：

```text
acquisition_end_reason
```

### 验收

- [x] Runtime public result 不再出现 `ready_for_reasoning`。
- [x] Runtime public result 不再出现 `stop_recommended`。
- [x] `new_evidence=0` regression 仍明确只是 retrieval fact。
- [x] Guardrail test 禁止重新引入这些字段。

### A1 完成证据（2026-08-30）

- Runtime contract commits: `fce60a9`, `24de41d`, `08019cd`, `b2c397d`, `e3cb96e`, `f0cbe192`。
- `EvidenceReadiness / ReadinessStatus / StopKind / StopReason / ready_for_reasoning / stop_recommended` 已从 Runtime public progress contract 删除。
- `no_new_evidence` 改为 `data.novelty` retrieval fact；不再生成 stop reason。
- 只有明确 bounded acquisition end（例如 frontier/source exhausted）可返回 `acquisition_end_reason`。
- Focused gate run `33314454449`: `21 passed in 1.53s`；`scripts/check_architecture.py` PASS。
- 一次性 refactor helper/workflow 已在结果 commit 中自删除，不形成长期维护层。

## A2. 删除 skill 中任何 stop/sufficiency 暗示

### 验收

- [x] `.pi/skills/tracecite/SKILL.md` 只解释 API/evidence semantics。
- [x] `.agents/skills/tracecite-investigate/SKILL.md` 同样不提供 investigation strategy。
- [x] 没有 benchmark-specific clue。

### A2 完成证据（2026-08-30）

- 审核 `.pi/skills/tracecite/SKILL.md` 与 `.agents/skills/tracecite-investigate/SKILL.md`。
- 当前两份 skill 已明确：Agent owns hypotheses/order/causal reasoning/sufficiency/stopping；`new_evidence=0`、`no_match`、`session_progress`、identity constraints 均仅为机械事实。
- 未发现 benchmark hidden answer / preferred investigation path；因此本项不为制造 diff 而修改 skill。
- operation/API 名称后续随 canonical API 收敛在 H2 统一更新。

---

# B. RetrievalSession 成为唯一 Evidence Memory Owner

状态：**COMPLETE**

## B1. 合并 retrieval telemetry

删除独立：

```text
RetrievalSessionTelemetry sidecar
*.telemetry.json
```

将必要的纯机械 retrieval history 直接收进 `RetrievalSessionState`：

```text
recent operations
request fingerprints
search/expand/materialize/replay counts
new/repeated/no-match outcome
```

不保留 `v2` 文件名或并行 schema。

### 验收

- [x] 同一 session 只有一个 canonical persisted state owner。
- [x] no-match operation 也可被记录，但不制造 Evidence。
- [x] parallel/atomic update regression 通过。
- [x] session state 不包含 hypothesis / root cause / sufficiency / stop recommendation。

## B2. 保留 current-query relevance

### 验收

- [x] Query A 首次命中 L100：body 可见。
- [x] Query B 再命中 L100：`new_evidence=0`，body suppress，但返回 `matched_existing_evidence` exact ref。
- [x] changed query 不会因为 dedup 丢 relevance。

## B3. Replay / materialize 独立于 novelty

### 验收

- [x] replay exact Evidence body。
- [x] replay 返回 `replayed=true`。
- [x] replay 保持 `new_evidence=0`。
- [x] replay 不污染 recent novelty statistics。

## B4. InvestigationState 与 retrieval novelty 完全解耦

### 验收

- [x] 无 InvestigationState 时 canonical Evidence API 完整工作。
- [x] InvestigationState executions 不再作为 seen/range primary owner。
- [x] RetrievalSession 不读取 hypothesis/finding 决定 retrieval。

---

# C. 重建 Canonical Evidence API

状态：**COMPLETE**

最终 public canonical primitives：

```text
retrieve
materialize
replay
aggregate
traverse
verify
```

## C1. `retrieve`

### 验收

- [x] caller-supplied target/predicate/scope。
- [x] 返回 Evidence + Coverage + Provenance + Novelty。
- [x] zero-match 为 retrieval fact，不变成 absence proof。

## C2. `materialize`

替代“expand 作为核心概念”。

### 验收

- [x] EvidencePointer/source-version range 可精确展开。
- [x] 已覆盖 range 可 suppress duplicate body。
- [x] immutable source identity 校验保持。

## C3. `replay`

见 B3。

## C4. `aggregate`

优先支持 Agent 真实会回 shell 做的机械任务：

```text
count
distinct
group
distribution
exact occurrence summary
```

### 禁止

```text
root cause ranking
causal scoring
“most likely” evidence
```

### 验收

- [x] 至少覆盖当前 4-case 中常见的 count/group/distinct 需求。
- [x] aggregation result 仍有 scope/source-version/provenance。
- [x] 不需要 raw source dump 到 Agent context。

## C5. `verify`

### 验收

- [x] source/hash/manifest/integrity mechanical verification 保持。
- [x] caller-supplied predicate 可机械验证时使用统一 result contract。

## C6. Compatibility wrappers 清理

`probe/search/expand/sample/survey/...` 逐个审计：

- 有明确 convenience value：保留 wrapper；
- 只为旧错误行为存在：删除；
- 所有 wrapper 必须调用 canonical primitives；
- wrapper 不拥有 state / routing / novelty semantics。

---

# D. `investigate` 收敛为 `traverse`

状态：**COMPLETE**

## D1. 删除调查者语义

目标替换：

```text
investigate -> traverse
EvidenceInvestigation -> EvidenceTraversal
ExplorationPolicy -> TraversalLimits
```

如果旧名字没有独立价值，直接删除，不做长期 alias。

## D2. Caller owns seed/scope/direction

Core 仅做 caller-selected scope 内 deterministic traversal。

### 验收

- [x] Runtime 不自行选择“更重要”的 sibling/entity。
- [x] Runtime 不生成 `next_best_entity` / `next_query`。
- [x] frontier 仅用于 mechanical traversal execution，不代表 investigation order。
- [x] `identifier_only_correlation_safe=false` 等 identity constraints 保持。

---

# E. Routing / Selection 收敛

状态：**COMPLETE**

## E1. Routing 只负责 Transport

允许输入：

```text
source size
context budget
seen coverage
repeated ratio
output limits
```

允许输出：

```text
direct / bounded / materialized transport form
```

禁止输出：

```text
cause likelihood
next entity
investigation priority
stop recommendation
```

### 验收

- [x] routing unit tests 检查仅依赖 mechanical transport facts。

## E2. Evidence Selection 明确为 lossy transport heuristic

### 验收

- [x] generic signal hints 不声称 causal relevance。
- [x] full match set 可恢复。
- [x] truncation/omission 显式。

---

# F. Host Observation Contract

状态：**F1 COMPLETE；F2 DEFERRED UNTIL AFTER I**

> 此层不进入 Core Evidence state。

## F1. Pi Tool Activity Ledger

记录：

```text
total tool calls
TraceCite evidence operations
native search/read calls
opaque shell calls
model calls
wall time
provider-visible token fields（若可用）
```

### 验收

- [x] `140039` 中 `grep/bash/read` 不再从 trajectory telemetry 消失。
- [x] `139417` 中 TraceCite/native 40/40 类混合深挖可完整观察。
- [x] opaque shell 明确标 `opaque`，不伪装成 canonical Evidence。

## F2. Optional Host Checkpoint

Checkpoint 仅展示机械 activity summary，并要求 Agent自行重新选择 continue / answer。

### 禁止

```text
Evidence sufficient
You should stop
Root cause likely X
```

### 验收

- [ ] checkpoint prompt 不包含 hidden benchmark strategy。
- [ ] checkpoint 可关闭；Core 单独使用仍完整。
- [ ] checkpoint 是否有价值必须单独 A/B，不默认并入 Core product claim。

---

# G. Evaluation Contract

状态：**COMPLETE**

已有实验 overlay：support-aware scoring。

目标正式收敛为 gold schema：

```text
supported
inference_supported
unsupported_from_log
```

## G1. Evidence support level 正式进入 scorer

### 验收

- [x] `supported` 要求 direct evidence/citation。
- [x] `inference_supported` 要求 qualified inference。
- [x] `unsupported_from_log` 奖励明确 evidence boundary。
- [x] inference/unsupported 被说成 direct fact 计 overclaim。

## G2. 删除 benchmark hidden-answer pressure

### 验收

- [x] `139417` 不要求 Agent 为日志无法建立的 upstream cause 编确定结论。
- [x] `140268` 不要求日志直接证明不存在的 internal lookup implementation。
- [x] correctness truth 与 known upstream fix 可区分：known fix 不能自动等于 supplied-log-supported truth。

## G3. Infra validity 独立

每个 arm 输出：

```text
task_result
run_validity
```

### 验收

- [x] 429/overload 不计 product loss。
- [x] contaminated run 可用于 trajectory diagnosis，但不能进入 clean A/B win/loss。

---

# H. 文档与 Adapter 收敛

状态：**CORE COMPLETE；H3 上层同步冻结至 I/J 后**

## H1. Agent integration docs

当前 `docs/agent-integration.md` 中的 normative investigation loop 与 Guardrails 有冲突风险。

目标：

- API/semantics 留在 integration doc；
- investigation workflow 只作为 non-normative example；
- 不教 Agent preferred investigation strategy。

## H2. Pi skill

只保留：

- Evidence API semantics；
- provenance/replay/coverage semantics；
- identity safety semantics；
- Host checkpoint 边界（若启用）。

## H3. MCP / Mobile 暂缓同步

在 Core canonical contract + 4-case validation 稳定前：

- [x] 不更新 MCP。
- [x] 不更新 Mobile。

Core 稳定后再一次性同步，避免上层跟随中间重构反复变化。

---

# I. 4-Case 验证 Gate

状态：**READY；最终实现已收口，但新 case 尚未运行。先 smoke 第一个小 case。**

固定 case：

1. `kubernetes-140039-runc-5347-scale`
2. `kubernetes-139417-scale`
3. `kubernetes-140848-scale`
4. `kubernetes-140268`

先每 case 单次 paired A/B。

## Gate 1 — correctness

- [ ] required answer/support-aware quality 不低于当前 baseline。
- [ ] unsupported / contradiction 不增加。
- [ ] provenance/citation 可复核。

## Gate 2 — convergence

重点观察：

```text
core evidence 首次到达 tool index
final answer tool index
post-core tool calls
TraceCite vs native evidence calls
repeated/no-match ratio
timeout
```

预期：

- `139417/140268` 不再长期稳定落在 80–100+ calls / timeout；
- `140039/140848` 正常轨迹不能被新架构显著拖长。

不设 benchmark-specific hard-coded stop 数字。

## Gate 3 — efficiency

在 Gate 1/2 通过后再比较：

```text
model calls
tool calls
provider input
provider cache-read
provider output
model-visible tool chars
wall time
```

禁止把 provider input+cache_read 随意称为统一 billable token。

## Gate 4 — clean validity

- [ ] 至少有可解释的 provider-clean paired runs 后再下 A/B 产品结论。

---

# J. 稳定性验证

状态：**BLOCKED BY I**

只有 4-case 单轮显示方向正确后才执行：

```text
每 case 3 paired repetitions
串行
短 arm 间隔
不再固定 45s repeat delay
```

目标不是追求某一次漂亮 run，而是测 trajectory variance。

---

# K. 上层同步

状态：**BLOCKED BY I/J**

当 canonical Evidence API 稳定后：

1. 更新 MCP for_agent；
2. 更新 Mobile for_agent；
3. 上层只依赖 canonical API/contract；
4. Core 内部模块名/实现后续变化不要求上层同步。

---

## 3. 明确删除/不再继续的实验性方向

以下内容不再作为长期架构继续叠加：

- [x] 独立 `RetrievalSessionTelemetry` sidecar；
- [x] 仅 TraceCite-local `session_progress` 作为完整 investigation solution；
- [x] `ready_for_reasoning`；
- [x] `stop_recommended`；
- [x] Runtime 自动决定 next investigation entity；
- [x] 为保旧 API 建 `v2` 并行模型；
- [x] benchmark-specific skill hints；
- [x] 禁止 Agent 使用 native tools 来“强制 TraceCite 赢 benchmark”；
- [x] 为了 token saving 牺牲 answer/evidence correctness。

---

## 4. 每个代码提交的强制记录格式

每个重构 commit 后，在本文档对应工作项下补：

```text
Status: TODO / IN PROGRESS / COMPLETE / BLOCKED
Commit: <sha>
Tests: <local/CI run ids>
Why: <解决哪个已确认问题>
Behavior change: <外部 contract 有什么变化>
Remaining risk: <还没证明什么>
```

禁止只写“refactor / cleanup”而不说明行为目标。

---

## 5. 当前立即执行顺序

代码与 contract 收口完成后，验证严格按：

1. 先完成 G2/G3、Host activity 分类与 benchmark workflow 最终化；
2. 跑 post-finalization canonical unit/architecture gate；
3. **只跑第一个小 case `kubernetes-140039-runc-5347-scale` smoke paired A/B**；
4. smoke 的入口、trajectory telemetry、canonical scorer、`task_result/run_validity` 与 artifact 全部正常后，才跑 4-case 单轮；
5. 4-case 单轮方向有效后，才跑 `4 × 3` paired stability；
6. stability 串行、短 arm 间隔；不再使用固定 45 秒 repeat delay；
7. F2 optional checkpoint 是否继续实验，必须由单独 A/B 决定，不作为 Core gate；
8. MCP / Mobile 最后同步。

任何新想法若不属于上述工作项，先更新本文档说明“为什么需要新增工作项”，再实现。
---

## 6. 2026-08-30 本轮 canonical 收敛证据回填

> 下表按第 4 节强制格式记录。本表只关闭已经有 commit + gate 证据的工作项；4-case / repeated A/B 尚未运行，因此 I/J 不提前打勾。

### B — RetrievalSession canonical owner

Status: **COMPLETE**  
Commit: `a7baa1d971d375c482431b54f45776d215c51f11`  
Tests: canonical final gate `33317449637`；包含 `test_runtime_session_retrieval.py`、`test_session_novelty_regressions.py`、canonical Evidence contract 与 architecture check。  
Why: 删除并行 retrieval sidecar/state ownership，保证 novelty、covered range、replay/repeated relevance 只有一个机械 owner。  
Behavior change: changed-query repeated hit 保留 `matched_existing_evidence`；replay 明确为旧 Evidence reread 且不增加 novelty；canonical Evidence API 可脱离 InvestigationState 工作。  
Remaining risk: 真实 Pi 长轨迹下的行为价值仍需 I/J benchmark 验证。

### C — Canonical Evidence API

Status: **COMPLETE**  
Commit: `a7baa1d971d375c482431b54f45776d215c51f11`  
Tests: canonical final gate `33317449637`；顶层 public-surface assertion 强制包含 `retrieve/materialize/replay/aggregate/traverse/verify`。  
Why: 删除多套半重叠入口，把 evidence acquisition/recovery/aggregation/verification 收敛成一个稳定 contract。  
Behavior change: `tracecite.__all__` 直接暴露 canonical primitives；`AggregateRequest` 正式进入 public surface；旧错误 API 不作为顶层 canonical contract。  
Remaining risk: Pi/MCP/Mobile adapter 的上层同步在 I/J 后再做。

### D — Traverse mechanical boundary

Status: **COMPLETE**  
Commit: `a7baa1d971d375c482431b54f45776d215c51f11`  
Tests: canonical final gate `33317449637`；canonical contract / runtime boundary / architecture check。  
Why: 删除 Runtime “调查者”语义，避免 Core 决定 investigation order。  
Behavior change: public contract 使用 `EvidenceTraversal / TraversalLimits / traverse`；caller owns seed/scope/direction；frontier 只表示 mechanical traversal。  
Remaining risk: 真实 Agent 是否因此减少无效深挖只能由 I/J 验证。

### E — Routing / Selection mechanical semantics

Status: **COMPLETE**  
Commit: `a7baa1d971d375c482431b54f45776d215c51f11`  
Tests: canonical final gate `33317449637` 中 `tests/test_evidence_routing.py`、`tests/test_evidence_selection.py` PASS。  
Why: 防止 transport heuristic 变成因果/优先级/stop policy。  
Behavior change: routing/selection 只使用 mechanical transport facts；lossy selection 必须保留 truncation/omission/recovery 语义。  
Remaining risk: 不同 source density 下的质量/成本影响留给 I/J。

### F1 — Pi Host Tool Activity Ledger

Status: **COMPLETE**  
Commit: `c95f2eeaa1885745bcea8fd684325bff09fcebaf`  
Tests: Host/eval focused gate `33318061265`；`tests/test_pi_host_tool_activity.py`、`tests/test_pi_session_to_transcript.py`、architecture check PASS。  
Why: TraceCite-local retrieval telemetry 看不到 Agent 切回 `grep/read/bash` 的真实 trajectory。  
Behavior change: Pi extension 从真实 `tool_call/tool_result` 记录 TraceCite/native activity；`grep/find`=native search，`read`=native read，`bash`=native other 且 `opaque=true`；activity 可写入 `TRACECITE_PI_ACTIVITY`，transcript 保留 activity/duration/summary。  
Remaining risk: F2 optional checkpoint 未实现/未验证；是否有产品价值不能从 F1 推断。

### G1 — Support-aware scoring becomes canonical scorer behavior

Status: **COMPLETE**  
Commit: `c95f2eeaa1885745bcea8fd684325bff09fcebaf`  
Tests: Host/eval focused gate `33318061265`；`tests/test_root_cause_benchmarking.py`、`tests/test_support_aware_root_cause_benchmarking.py`、support self-test PASS。  
Why: 避免 benchmark 通过外部 overlay 才理解 direct / inference / unsupported evidence boundary。  
Behavior change: `tracecite.root_cause_benchmarking.score_transcript()` 直接应用 `supported / inference_supported / unsupported_from_log`；canonical `passed` 即 support-aware 结果，同时保留 `legacy_passed` 诊断字段；旧 `support_level_score.py` 仅保留 compatibility helper。  
Remaining risk: G2/G3 的 case-level truth/infra validity 仍要在新的真实 A/B 中确认。

### H1 — Agent integration doc

Status: **COMPLETE**  
Commit: `3c2c39e6605cebb565d8c3ce3d367b0e2e99c734`  
Tests: docs-only change；后续 Core CI 作为 repository integrity gate。  
Why: 删除与 Guardrails 冲突的 normative investigation playbook。  
Behavior change: `docs/agent-integration.md` 只定义 canonical Evidence API、RetrievalSession、routing/selection、Host telemetry、evaluation 与 trust boundary；示例明确为 non-normative。  
Remaining risk: 中文 integration doc 尚未在本项要求中同步；若对外发布双语文档，应在 Core contract 稳定后一起校准。

### H2 — Two skills use final canonical API semantics

Status: **COMPLETE**  
Commit: `.agents/skills/tracecite-investigate/SKILL.md` = `8040a8c292ae7bf5f3e3e894b6b40d6ee7364844`；`.pi/skills/tracecite/SKILL.md` = `3b1359a30ef9e5cf30e00020fb8e91a3afb38cd7`。  
Tests: docs/skill integrity through Core CI；canonical code semantics already gated by `33317449637` and `33318061265`。  
Why: 防止 skill 继续教授旧 `search/expand/investigation` 作为第二套架构。  
Behavior change: 两份 skill 以 `retrieve/materialize/replay/aggregate/traverse/verify` 为唯一 canonical semantics；Pi `tracecite_search/tracecite_expand` 只作为 adapter mapping 描述。  
Remaining risk: MCP/Mobile 依然按 H3/K 明确暂缓，不能提前同步。

### Cleanup evidence

- canonical C/D one-shot cleanup commit: `a7baa1d971d375c482431b54f45776d215c51f11` 自删 canonical helper/workflow。
- Host/eval one-shot cleanup commit: `6f4ec266b5468b891d006ec03ca4e33fd112bd9d`。
- 当前进入 I 前的原则：**先跑第一个小 case `kubernetes-140039-runc-5347-scale`；确认入口、Host activity、canonical scorer 与 A/B artifact 正常后，才允许扩到其余 3 case。**



### G2 — Hidden-answer pressure removed from case truth

Status: **COMPLETE**  
Commit: `211219782f688aa0d8222d305612d059bf42ea09`  
Tests: 新增 case-level regression，锁定 `kubernetes-139417` 与 `kubernetes-140268` 的 `upstream_contributor/fix_alignment=unsupported_from_log` 与 boundary patterns；post-finalization gate 尚未运行。  
Why: supplied log 无法直接证明 known upstream implementation/fix 时，不应把 upstream knowledge 伪装成日志 direct truth。  
Behavior change: correctness 仍可保留 known upstream fix reference，但 canonical scoring 根据 supplied-evidence support level 奖励明确 boundary，而不是强迫 Agent 编出确定结论。  
Remaining risk: 真实回答是否稳定遵守 boundary 仍需 I/J。

### G3 — Infra validity separated from task result

Status: **COMPLETE**  
Commit: `211219782f688aa0d8222d305612d059bf42ea09`  
Tests: 新增 `tests/test_benchmark_run_result.py`；post-finalization gate 尚未运行。  
Why: 429/402/502/503/504、provider overload 与 timeout 会污染 paired A/B，不能自动算 TraceCite/native product loss。  
Behavior change: `benchmarks/agent-investigation/run_result.py` 为每个 arm 生成独立 `task_result` 与 `run_validity`；provider contamination、timeout、host nonzero exit 与 answer quality 分离；trajectory 同时输出 core evidence 首次到达、post-core tools、native/TraceCite/opaque-shell 计数与 low-novelty ratio。  
Remaining risk: provider-clean paired sample 数量仍由 I/J 决定。
