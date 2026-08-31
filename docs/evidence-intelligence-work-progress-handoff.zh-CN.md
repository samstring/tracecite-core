# TraceCite Agent / MCP 工作进度与交接

> 本文档是当前 `feature_for_agent` 工作的权威交接记录。新对话应优先读取本文档、当前 branch HEAD 和最新 CI；旧聊天、旧 handoff、旧 benchmark 结论只作为历史。

更新时间：2026-08-31

## 1. 当前仓库与分支状态

### TraceCite Core

仓库：`samstring/tracecite-core`

当前正式 Agent 基线分支：

```text
feature_for_agent
```

Evidence Runtime 实现/实验分支：

```text
experiment/evidence-intelligence
```

2026-08-31 已将稳定的 Evidence Runtime 架构同步到 `feature_for_agent`。同步时两条分支共同代码 HEAD 为：

```text
127b43c402d29655c86230608eded3fcf2e8b40e
bench: exclude unavailable log case from log-code A/B
```

`feature_for_agent` 原先唯一独立的旧 handoff commit 已按用户要求丢弃，不作为后续架构基线。

本次文档更新会让 `feature_for_agent` 在上述代码基线之上多一个纯文档提交；Core 产品代码仍以 `127b43c...` 对齐后的实现为基础。

### TraceCite MCP

仓库：

```text
samstring/tracecite-mcp
```

目标分支：

```text
feature_for_agent
```

开始本轮 MCP 设计检查时 HEAD：

```text
f6fed44cd2f500cb0bcc604295c43426162a4409
test(agent): match canonical routing projection
```

**重要：目前只完成了 MCP 现状检查和目标架构确认，新的六原语 MCP 改造尚未提交。** 新对话不要误认为 MCP 已经完成迁移。

---

## 2. 已稳定的最高级架构边界

核心原则已经稳定，可作为 MCP v1 的设计前提：

> **Agent 负责想和决定；TraceCite 负责证据。**

### Agent / Agent Host 负责

```text
problem understanding
hypothesis generation
investigation order
what to inspect/query next
causal reasoning
root-cause conclusion
evidence sufficiency for the task
final answer
when to stop
```

### TraceCite Core 负责

```text
bounded evidence retrieval
exact materialization
replay / recall
provenance / source version
Evidence identity
coverage / truncation / missing-evidence facts
session-scoped novelty / repeated evidence
mechanical aggregation
caller-scoped deterministic traversal
integrity / mechanical verification
identity / correlation safety facts
```

### Core 不得输出或拥有

```text
root_cause_confidence
evidence_sufficient
ready_for_reasoning
stop_recommended
next_best_query
hypothesis priority
causal likelihood / ranking
```

机械事实不能升级为认知结论：

```text
new_evidence = 0          != investigation complete
no_match                  != event impossible
frontier exhausted        != root cause proven
identifier unsafe         != incident cause
```

这条边界已经写入：

```text
docs/PROJECT_GUARDRAILS.md
docs/adr-agent-runtime-semantic-boundary.zh-CN.md
docs/evidence-runtime-architecture.zh-CN.md
docs/agent-integration.md
```

除非发现真正的 Core contract 缺陷，否则后续 MCP / Pi / Codex / Claude 等集成不应为了单个 benchmark case 重新改变这条边界。

---

## 3. Canonical Agent-facing Evidence API 已稳定

MCP 和其他 Agent Host 应只依赖以下六个 canonical primitive：

```text
retrieve
materialize
replay
aggregate
traverse
verify
```

语义：

| Primitive | Core 机械职责 | 不负责 |
|---|---|---|
| `retrieve` | Caller 指定 target/query/scope，返回 Evidence、coverage、provenance、novelty | 选择调查方向 |
| `materialize` | 精确展开 caller 指定 range/ref | 判断是否证明假设 |
| `replay` | 精确重读已经交付的 immutable Evidence，不计新 Evidence | 把旧证据变成新支持 |
| `aggregate` | count/distinct/group 等确定性聚合 | causal ranking |
| `traverse` | caller 指定 seed/scope/limits 后做 bounded mechanical traversal | planner / next-best target |
| `verify` | integrity / manifest / source-version / mechanical predicate 验证 | 验证自然语言根因 |

核心实现入口：

```text
src/tracecite/runtime/evidence_api.py
src/tracecite/runtime/agent_api.py
src/tracecite/runtime/__init__.py
src/tracecite/__init__.py
```

`probe/search/expand/sample/survey/...` 如果仍存在，只视为历史/兼容 convenience surface；**新的 MCP v1 不应把它们作为正式 Agent tool surface。**

---

## 4. RetrievalSession 已稳定为唯一 Evidence session memory owner

Canonical owner：

```text
RetrievalSessionState
RetrievalSessionStore
```

位置：

```text
src/tracecite/runtime/retrieval_session.py
src/tracecite/runtime/session_retrieval.py
```

它拥有机械 retrieval memory：

```text
context/session id
revision
seen evidence/results/groups/relations
covered source-version ranges
source observations/generations
request fingerprints
exact duplicate requests
operation counts
recent retrieval operations
replay state
```

它明确不拥有：

```text
hypotheses
findings
root cause
evidence sufficiency
stopping decisions
```

MCP 应采用：

```text
MCP/Agent session_id
        ↓
RetrievalSessionStore
```

而不是在 MCP 再实现一套 novelty / coverage / dedup state。

---

## 5. MCP 当前代码与目标改造

### 5.1 当前 MCP 仍是旧的宽工具面

当前主要文件：

```text
samstring/tracecite-mcp
├─ src/tracecite_mcp/server.py
├─ tests/test_server.py
├─ README.md
├─ pyproject.toml
└─ .github/workflows/ci.yml
```

当前 `server.py` 仍暴露：

```text
tracecite_retrieve
tracecite_probe
tracecite_sample
tracecite_survey
tracecite_search
tracecite_expand
tracecite_verify
tracecite_investigation_create
tracecite_validate_finding
tracecite_list_extensions
tracecite_list_capabilities
tracecite_execute_capability
```

并且当前 `tracecite_retrieve` 没有把一个明确的 MCP `session_id` 映射到持久 `RetrievalSessionStore`。

因此当前 MCP 还没有真正对齐最新 Core contract。

### 5.2 已确认的 MCP v1 目标

MCP 应变成 Agent-neutral thin adapter：

```text
Agent / Claude / Codex / Cursor / Other Host
                     │
                     │ MCP
                     ▼
             TraceCite MCP Server
                     │
          ┌──────────┼──────────┐
          │ six canonical tools │
          │ session mapping      │
          │ serialization        │
          │ transport            │
          └──────────┬──────────┘
                     │
                     ▼
              TraceCite Core
```

MCP v1 正式工具面：

```text
tracecite_retrieve
tracecite_materialize
tracecite_replay
tracecite_aggregate
tracecite_traverse
tracecite_verify
```

MCP v1 不应拥有：

```text
planner
hypothesis generation
root-cause reasoning
next_best_query
evidence_sufficient
stop_recommended
Pi-specific convergence checkpoint
```

第一版也不应把以下旧 surface 暴露成正式 MCP tools：

```text
probe/sample/survey/search/expand compatibility wrappers
Investigation/Finding tools
Capability Registry management tools
```

如果以后 Domain Extension / server-side Provider 需要经 MCP 使用，应另外定义清楚 server-owned provider/capability registry 与安全边界，不要为了兼容旧 MCP 把它混进六原语 contract。

### 5.3 MCP 下一步工作（尚未提交）

按以下顺序执行：

1. 修改 `src/tracecite_mcp/server.py`
   - 收敛为六个 canonical tools；
   - 增加 `session_id` → `RetrievalSessionStore` 映射；
   - 不复制 Pi checkpoint / convergence 策略；
   - 不重新实现 Core novelty/coverage/dedup。
2. 更新 `tests/test_server.py`
   - 断言只有目标 canonical tool surface；
   - 测试同一 session 的 new/repeated/replay 语义；
   - 测试不同 session 隔离；
   - 测试 materialize/replay immutable SHA 约束；
   - 测试 aggregate；
   - 对 traverse 的 provider transport 只实现 Core 已能稳定表达的部分，不发明 provider semantics。
3. 更新 `README.md`
   - 架构改为 Agent → MCP → six primitives → Core；
   - 删除“Investigation Runtime / Capability Registry 是 MCP 主架构”的旧描述。
4. 必要时更新 `pyproject.toml` 的 Core compatibility 说明。
5. 用 Core `feature_for_agent` 跑 MCP CI。
6. 再做真实 MCP Host / Inspector / Agent smoke test。

---

## 6. Core 中 Pi 相关位置：当前仍保留，MCP 迁移尚未修改

以下内容是 **Pi benchmark / Pi adapter 层**。它们当前仍在 Core 仓库里，新的 MCP 工作尚未迁移、删除或替换这些文件。

它们可以继续作为历史 benchmark 和 Pi A/B harness，但 **MCP 不应依赖这些文件作为产品 contract**。

### 6.1 Pi Adapter / Bridge / Transcript 文件

```text
benchmarks/agent-investigation/pi_ab_runtime.py
benchmarks/agent-investigation/pi_log_code_tracecite_extension.ts
benchmarks/agent-investigation/pi_session_to_transcript.py
benchmarks/agent-investigation/pi_tracecite_bridge.py
benchmarks/agent-investigation/pi_tracecite_extension.ts
benchmarks/agent-investigation/pi_tracecite_extension_impl.ts
```

状态：

```text
保留
Pi-specific
未迁移到 MCP
未因本轮 MCP 设计而修改
```

其中：

- `pi_tracecite_bridge.py`：Pi tool → Python/Core bridge；
- `pi_tracecite_extension_impl.ts`：Pi tool registration、compact projection、Host activity、checkpoint 等；
- `pi_log_code_tracecite_extension.ts`：log+code A/B 的 runtime-log access guard；
- `pi_session_to_transcript.py`：Pi session → benchmark transcript；
- `pi_ab_runtime.py`：A/B runtime 辅助逻辑。

这些能力中只有“调用六个 Core primitives”的思想可复用；Pi tool registration、checkpoint、A/B guard、Pi transcript 都不属于 MCP Core contract。

### 6.2 Pi Skill

```text
.pi/skills/tracecite/SKILL.md
```

状态：

```text
保留
Pi-specific
当前仍依赖 Pi extension/tool naming
尚未改成通用 MCP/Agent Skill
```

不要直接把它当作 MCP Skill 原样复制。

### 6.3 通用 Agent Skill 候选

```text
.agents/skills/tracecite-investigate/SKILL.md
```

状态：

```text
保留
比 .pi Skill 更接近通用版本
尚未针对新的 MCP 六工具面完成最终 review / rewrite
```

后续应把“TraceCite API 正确使用语义”抽成 Agent-neutral skill：

```text
Core/MCP tool semantics
+ no_match / no_new_evidence / replay / provenance rules
+ Evidence boundary rules
```

但不能加入：

```text
preferred hypothesis
benchmark-specific search path
causal recommendation
stop recommendation
```

### 6.4 Pi-specific tests

当前明确的 Pi 测试：

```text
tests/test_pi_ab_benchmark_policy.py
tests/test_pi_ab_runtime.py
tests/test_pi_host_tool_activity.py
tests/test_pi_session_to_transcript.py
tests/test_pi_tracecite_bridge.py
```

状态：

```text
继续用于 Pi benchmark/harness
本轮 MCP 尚未修改
MCP 应在 tracecite-mcp 仓库维护自己的 contract/integration tests
```

### 6.5 Pi workflows

当前 Core 中仍保留：

```text
.github/workflows/pi-agent-139417-ab-validation.yml
.github/workflows/pi-agent-few-mb-forced-ab.yml
.github/workflows/pi-agent-k8s-focused.yml
.github/workflows/pi-agent-moderate-suite-preflight.yml
.github/workflows/pi-agent-moderate-suite.yml
.github/workflows/pi-agent-runnable-16-forced-tracecite.yml
.github/workflows/pi-agent-scale-priority-forced-tracecite.yml
.github/workflows/pi-evidence-runtime-ab.yml
.github/workflows/pi-log-code-ab.yml
.github/workflows/pi-scale-5case-repeat-ab.yml
.github/workflows/pi-tracecite-convergence-probe.yml
.github/workflows/pi-tracecite-skill-140268-retry.yml
.github/workflows/pi-tracecite-skill-scale-gate.yml
.github/workflows/pi-tracecite-skill-two-scale.yml
.github/workflows/pi-under20mb-forced-tracecite-ab.yml
```

状态：

```text
全部仍属于 Pi benchmark/probe 层
本轮 MCP 尚未迁移/修改
不要让 MCP 产品架构依赖这些 workflow
```

后续可以逐步清理过时 workflow，但在 benchmark 结果仍需要追溯时不要一次性删除历史 harness。

---

## 7. Pi A/B 当前已知结果与解释边界

TraceCite 当前最稳定的优势是：

> **降低 Evidence/context 的重复传输和模型处理负担，尤其在大日志场景。**

已有多轮实验常见到 processed context / cache-read 下降约 40%–70%，但不能宣传成所有 case 固定节省比例。

### Run #5

Run：

```text
33367498319
```

已确认的 `140039`：

```text
Native:    timeout
TraceCite: completed, 找到核心 runc/seccomp/EINVAL 根因链
```

Stop total tokens（按本项目约定的 stop-time usage 口径）：

```text
Native     ≈ 2.332M
TraceCite  ≈ 1.325M
observed delta ≈ -43.2%
```

但双方都有 provider rate-limit contamination，因此这一 pair 不能作为正式公平 A/B 因果结论。

`139417`：历史 runtime log 当前远端 404，已从 runnable log+code matrix 剔除；保留历史 case 文件只作 provenance。

`140268`：仍是 discovery-hard case；Native / TraceCite 都曾无法稳定找到隐藏 mechanism，说明 TraceCite 目前没有证明会普遍提升根因发现能力。

`140848`：历史结果显示双方都能找到 decisive panic/source mechanism，但 Agent 可能继续搜索到 timeout；TraceCite 能显著减少上下文膨胀，但 convergence 仍是 Host/Agent 问题。

因此当前产品结论应保持：

```text
已较强证明：bounded/provenance-aware Evidence flow 与 context efficiency
尚未证明：普遍提高 Agent root-cause correctness
仍需改进：hard discovery + Agent convergence
```

---

## 8. Benchmark 与 MCP 必须继续隔离

Benchmark 的 Pi guard / scorer / hidden gold 不得进入 MCP 产品逻辑。

保持：

```text
Agent-visible input
        !=
evaluator-only gold
```

MCP 不应包含：

```text
case-specific hints
preferred investigation path
known fix/root cause
benchmark stopping rule
```

`pi_log_code_tracecite_extension.ts` 中“TraceCite arm 禁止 native 读取 runtime log”的行为只是 A/B 公平性 guard，不是产品 MCP 必需能力。

---

## 9. Core 中仍存在但 MCP v1 不应暴露的 secondary surface

Core 当前仍有一些 secondary/legacy API，例如：

```text
InvestigationState / InvestigationStore
BudgetPolicy
Finding validation
Capability Registry
older integrations / compatibility wrappers
```

它们目前不要求从 Core 删除；但 MCP v1 不要因为它们存在就全部暴露给 Agent。

MCP v1 的依赖面应刻意保持：

```text
six canonical primitives
+ request/target types
+ RetrievalSessionStore
+ 必需的 stable provider/identity types（仅在真正需要时）
```

这样 Core 内部后续重构不会强迫 MCP 跟着大改。

---

## 10. 分支清理状态

Core 当前计划长期保留：

```text
main
feature_for_agent
experiment/evidence-intelligence
```

希望删除的旧分支：

```text
refactor/agent-v2
refactor/extension-v2-context
tmp/evidence-relationship-compact
work/evidence-intelligence-finalize
```

截至本文档更新时，连接器没有提供 delete-ref 操作，因此这些旧分支尚未由本会话删除。不要误认为已经完成分支清理。

---

## 11. 新对话接手顺序

如果下一步是继续 MCP，按这个顺序：

1. 读本文件；
2. 检查 `samstring/tracecite-core@feature_for_agent` 当前 HEAD；
3. 读：
   - `docs/PROJECT_GUARDRAILS.md`
   - `docs/evidence-runtime-architecture.zh-CN.md`
   - `docs/adr-agent-runtime-semantic-boundary.zh-CN.md`
   - `docs/agent-integration.md`
4. 检查 `samstring/tracecite-mcp@feature_for_agent` HEAD；
5. 读 MCP：
   - `src/tracecite_mcp/server.py`
   - `tests/test_server.py`
   - `README.md`
   - `.github/workflows/ci.yml`
6. 直接实施 MCP 六原语 + `RetrievalSessionStore` session mapping；
7. 更新 MCP tests / README；
8. 跑 MCP CI；
9. 再做真实 MCP Host/Agent 验收；
10. Generic Skill 重构可以随后独立进行，不要阻塞 MCP v1。

如果下一步是继续 Pi benchmark，则先检查最新 Actions/artifact，不要用旧聊天中的 run 状态猜测当前结果。

---

## 12. 不要做的事情

后续开发保持这些红线：

1. 不把 planner / reasoning / root-cause logic 放进 TraceCite Core。
2. 不让 MCP 发出 `stop_recommended` / `evidence_sufficient`。
3. 不把 Pi convergence checkpoint 复制成 MCP v1 的 canonical semantics。
4. 不在 MCP 重新实现 novelty / coverage / Evidence identity。
5. 不为了 benchmark 分数给 Skill/MCP 注入隐藏答案或 preferred search path。
6. 不把 `input + cacheRead` 称为 billable tokens；需要时明确叫 processed context/workload。
7. 不因为单个 difficult case 表现不好就重新扩大 Core public API。

---

## 13. 当前一句话结论

> **TraceCite Core 的 Agent/Evidence 架构边界和六个 canonical Evidence primitives 已稳定，可以把 `feature_for_agent` 作为 MCP 的 Core 基线；下一步工作重点已经从“继续改 Core 架构”切换为“在 `tracecite-mcp@feature_for_agent` 实现六原语薄适配 + RetrievalSession 映射”，Pi 相关代码继续作为 benchmark/Host 专用层保留，不进入 MCP contract。**
