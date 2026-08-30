# Evidence Intelligence 工作进度与交接

> 本文档是 `experiment/evidence-intelligence` 分支当前工作的权威交接记录。旧聊天、旧实验记录和旧进度文件仅作为历史；出现冲突时，以本文档较新的决策、branch HEAD 和最新 CI / benchmark 事实为准。

更新时间：2026-08-30

## 1. 当前工作基线

- 仓库：`samstring/tracecite-core`
- 当前工作分支：`experiment/evidence-intelligence`
- 基础分支：`refactor/agent-v2`
- 当前记录时 branch HEAD：`e2ec9f1713411b946c127c4fc9bc7c866e901715`
- 当前 HEAD message：`chore: make audit-decoupling regression explicit`
- B1 单一 retrieval-memory owner 已落地：`bba00e18a29ca26f853eb957453b30eb21b321b5`
- 未经明确确认，不合并到基础分支。
- Core correctness / contract 未稳定前，不同步 Mobile / MCP。

当前阶段：**Evidence Runtime 收敛 + Agent 调查轨迹可观测性 + correctness / A-B benchmark 验证。**

用户当前总指令：

> **把已经列出的工作全部做完；中途不需要逐项确认。**

因此后续默认直接继续，只有架构目标发生实质变化、权限阻断或需要用户承担不可逆风险时才中断说明。

---

## 2. 不可破坏的产品边界

核心原则保持：

> **Agent 负责想和决定；TraceCite 负责证据。**

Agent owns：

```text
problem understanding
hypothesis generation
investigation order
causal reasoning
conclusions
what to inspect next
when to stop
```

TraceCite owns：

```text
evidence access
provenance / source version
bounded retrieval
exact evidence identity
repeated-evidence suppression
replay / recall
coverage / novelty
mechanical retrieval history
mechanical identity / relation facts
```

禁止把 retrieval fact 转成认知 / 因果结论：

```text
new_evidence = 0             != investigation complete
no_match                     != event impossible
identifier_only_* = false    != root cause
recent low-yield retrieval   != stop recommendation
```

同时保持：

- 不向 prompt / skill 注入 benchmark answer；
- 不加入 case-specific root-cause hint；
- replay 必须返回 exact evidence；
- 不做 context dump；
- 不为省 token 牺牲 answer quality。

---

## 3. RetrievalSession：当前 canonical mechanical memory owner

B1 已完成关键收敛：

```text
RetrievalSessionState
RetrievalSessionStore
```

现在是 mechanical retrieval memory 的单一 owner，统一保存：

```text
revision
seen_evidence
seen_results
seen_groups
seen_relations
covered_ranges
source_observations
operation_counts
recent_operations
request_fingerprints
exact_duplicate_requests
```

`RetrievalOperation` 记录的是机械事实：

```text
operation
status
request_fingerprint
new_evidence
repeated_evidence
new_relations
new_lines
source_version
replayed
exact_duplicate_request
```

它明确 **不拥有**：

```text
hypotheses
findings
causal conclusions
evidence sufficiency
stopping decisions
```

### 3.1 已删除的错误方向

此前短暂实验过独立 `retrieval_telemetry.py` sidecar；已删除。

当前状态：

```text
src/tracecite/runtime/retrieval_telemetry.py  -> 不存在
B1 one-shot workflow                         -> 已删除
```

机械 retrieval history 直接进入 `RetrievalSessionState`，避免两个 state owner、两把锁和 sidecar 漂移。

### 3.2 B1 验证过程中的真实失败与修复

B1 收敛 CI 过程中连续暴露了几类真实问题：

1. sidecar experiment 的测试 / benchmark variant 仍残留引用；
2. 老测试还断言 `stop_reason`，与当前“TraceCite 不替 Agent 决定停止”的边界冲突；
3. one-shot helper 被 workflow 临时修改后，`git rm` 未加 force，导致最终 commit step 失败。

关键事实：在最终成功落地 B1 前，一次验证已达到：

```text
30 passed
architecture governance checks passed
```

之后 B1 最终以 commit：

```text
bba00e18a29ca26f853eb957453b30eb21b321b5
runtime: make RetrievalSession the single retrieval-memory owner
```

正式进入分支。

---

## 4. Repeated evidence：已确定的正确语义

关键原则：

> **TraceCite 只能记住“这段文本以前交付过”，不能假设“Agent 以前已经理解、记住或重视它”。**

因此：

1. 第一次命中：返回完整 evidence body；
2. 不同新 query 再命中旧 evidence：默认抑制重复 body，但返回当前 query 命中的 exact old refs；
3. Agent 可以 replay / expand / recall；
4. replay 是旧证据重读：`replayed=true`、`new_evidence=0`；
5. evidence novelty 与 current-query relevance 必须分开。

已落地 repeated-old-evidence ref 修复：

```text
a6216c8046b79b2f9c88172492c67ab2ed89837a
5f1f58720512d08c04efae2680615ca178f9c369
```

---

## 5. 当前要暴露给 Agent 的 session_progress

目标不是让 TraceCite 判断“够不够”，而是让 Agent 看见自己的 retrieval 轨迹。

建议 / 当前实现方向：

```text
session_progress:
  operation_counts
  unique_evidence_seen
  exact_duplicate_requests
  recent_window
  recent_with_new_evidence
  recent_repeated_only
  recent_no_match
```

其中 recent window 只表达机械历史，例如：

```text
最近 10 次 search：
- 1 次拿到新 evidence
- 6 次只命中旧 evidence
- 3 次 no_match
```

它 **不能** 表达：

```text
root_cause_confidence
evidence_sufficient
investigation_complete
stop_recommended
```

Skill / adapter 需要只解释这些字段的 mechanical semantics，不写“低收益就停止”之类策略性指令。

---

## 6. Pi / Skill 边界

Pi extension 的职责：

```text
Core result
-> compact projection
-> evidence refs / coverage / session_progress
-> boundary-safe guidance
```

不能在 adapter 层重新实现 Core 的 novelty / dedup / identity 逻辑。

需要保持并检查两个 Skill：

```text
.pi/skills/tracecite/SKILL.md
.agents/skills/tracecite-investigate/SKILL.md
```

Skill 只需要小幅说明：

```text
session_progress = mechanical retrieval history
```

并明确：

```text
它不表示 evidence sufficient
它不表示 root cause confidence
它不表示 investigation complete
它不替 Agent 决定 when to stop
```

---

## 7. A/B stability benchmark：已经得到的事实

重复稳定性 workflow：

```text
.github/workflows/pi-scale-5case-repeat-ab.yml
```

原设计：5 cases × 3 paired repeats × Native/TraceCite = 30 Agent sessions。

用户已明确第五个大文件 case `kubernetes-140628-scale` 不需要继续作为当前主验证目标；未来 rerun 应从 matrix 中移除，避免无必要消耗。

### 7.1 140039（约 2.29 MB）

TraceCite 3/3 task success。

观测 median：

```text
Native input:      72,360
TraceCite input:   30,536    (~ -57.8%)
Native cache:     564,177
TraceCite cache:  235,185    (~ -58.3%)
```

但 Native arm 有 provider 429，因此 clean strict A/B pair = 0/3。

结论：**上下文压缩信号明显，但不能作为干净的因果 A/B 结论。**

### 7.2 139417（约 13.49 MB）

该 case 明确暴露 Agent non-convergence：

```text
核心 evidence 很早（约 tool 4-7）已经出现，
但 Agent 继续几十次 retrieval / reasoning，
最终 TraceCite 多次撞到 600s timeout。
```

TraceCite search 中 no-new 的比例约：

```text
R1 ~74%
R2 ~69%
R3 ~67%
```

Dedup 本身工作正常；问题是 Agent 继续发起更多廉价小查询。

核心结论：

> **cheap step × too many steps = no convergence。**

同时该 case 的 scorer 还有 blind spot：gold 明确说 upstream contributor unsupported，但成功答案仍可能做 unsupported causal overreach 而未被 scorer 惩罚。后续 benchmark 结论前需要补 scorer / gold 约束。

### 7.3 140848（约 14.50 MB）

三次 trajectory 差异很大：

```text
R1: TraceCite 明显更长
R2: TraceCite 略长
R3: Native timeout，TraceCite 成功且显著更短
```

说明问题不是“TraceCite 一定拖慢”或“一定加速”，而是：

> **TraceCite 已能降低单次 retrieval 的上下文成本，但还不能稳定 Agent 的调查轨迹。**

这正是 `session_progress` 机械可观测性的动机。

### 7.4 Provider 429 的定位

429 / overload 会增加重试和 wall-clock，并污染 clean A/B；但在 139417 中 decisive evidence 在 429 出现很久之前已经到达，因此：

> **Agent 先进入长轨迹，provider overload 再放大长轨迹；429 不是最初的 trajectory root cause。**

---

## 8. Correctness / Investigation contract 仍需保留

此前已落地的 Test / Finding correctness contract 继续有效：

```text
Hypothesis
  -> Agent-declared Test
  -> linked Evidence
  -> Test Assessment
  -> Finding
```

TraceCite 可以阻止“没有 evidence-backed assessment 的 decisive Finding”，但不能自己生成 root cause。

Kubernetes 140268 曾暴露 claim-relative evidence sufficiency / causal gap propagation 不完整，因此后续不能只看 token 或 dedup 指标；correctness/no-harm 仍然是最高门槛。

---

## 9. 当前执行清单（继续做到全部完成）

按顺序继续，不逐项向用户确认：

### P0 — 完成 session_progress canonicalization

- 确认 `RetrievalSessionState` 是唯一 owner；
- search / expand / no_match / repeated-only / exact duplicate 全部在同一原子状态更新；
- replay 不误计为新 evidence；
- old persisted session 仍能加载；
- 不重新引入 telemetry sidecar。

### P1 — 完成 adapter / skill projection

- Pi extension compact `session_progress`；
- `.pi` Skill 更新；
- `.agents` Skill 更新；
- 明确不输出 stop / sufficiency / root-cause recommendation。

### P2 — deterministic tests / architecture gate

至少覆盖：

```text
new -> repeated-only -> no-match -> exact duplicate
overlapping expand
append growth
truncate/recreate generation
parallel session merge
old-state compatibility
no sidecar
boundary language
```

并跑：

```text
Core CI
architecture governance
Evidence Intelligence deterministic benchmark
```

### P3 — benchmark protocol 修正

- future matrix 移除 `140628-scale`；
- scorer 修复 139417 unsupported causal overreach blind spot；
- task success 与 provider-valid clean A/B 分开报告；
- 不把 `input + cache` 叫 billable tokens。

### P4 — focused repeated A/B

优先复测：

```text
139417   # pathological over-investigation
140848   # high trajectory variance
140039   # normal/control
```

关注：

```text
answer success
first decisive-evidence tool index
total tool calls
post-core calls
search new/repeated-only/no-match
input/cache/output/tool chars
provider contamination
```

目标：answer quality 不下降，同时 139417 的无效长尾显著缩短；正常 case 不应被强行截断。

### P5 — correctness / Final Gate

只有 correctness 与 benchmark instrumentation 可信后，才重新判断：

```text
full paired gate
no-harm regression
scale context overflow
ordinary-case overhead
```

### P6 — merge / Mobile / MCP

Core contract 最终稳定后：

```text
experiment/evidence-intelligence
-> 评估合并 refactor/agent-v2 / for_agent
-> core for_agent
-> Mobile for_agent
-> MCP for_agent
-> contract / integration tests
-> 文档同步
```

---

## 10. 新对话接手顺序

新对话先读：

1. 本文档；
2. branch HEAD；
3. `docs/PROJECT_GUARDRAILS.md`；
4. `src/tracecite/runtime/retrieval_session.py`；
5. `src/tracecite/runtime/session_retrieval.py`；
6. `benchmarks/agent-investigation/pi_tracecite_extension.ts`；
7. `.pi/skills/tracecite/SKILL.md`；
8. `.agents/skills/tracecite-investigate/SKILL.md`；
9. latest Core CI / Evidence Intelligence runs；
10. latest repeated A/B artifacts。

不要从旧聊天猜状态；本文档 + branch HEAD + latest CI/artifact 为准。

---

## 11. 当前一句话结论

> **TraceCite 的核心方向仍是 Evidence Runtime，而不是替 Agent 思考。Repeated-evidence dedup / exact refs / replay 语义已经成立；B1 已进一步把 retrieval history 合并进 canonical RetrievalSession，删除独立 telemetry sidecar。当前主要问题已经从“单次 retrieval 太大”转成“Agent 在拿到决定性证据后仍会继续大量低收益调用”。下一步是完成 session_progress 的 Core + Pi + Skill 闭环、补 deterministic / scorer 约束，再对 139417 / 140848 / 140039 做干净的 repeated A/B；answer quality / correctness 不允许为了 token 或调用数下降。Core 最终稳定后再进入 merge、Mobile 和 MCP。**
