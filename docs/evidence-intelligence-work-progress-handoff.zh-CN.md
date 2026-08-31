# TraceCite Agent / MCP 工作进度与交接

> 本文档是当前 `feature_for_agent` 工作的权威交接记录。新对话应优先读取本文档、两个仓库当前 branch HEAD 和最新 CI；旧聊天、旧 handoff、旧 benchmark 结论只作为历史。

更新时间：2026-08-31

## 1. 当前一句话状态

> **Core 的 Agent/Evidence 边界与六个 canonical Evidence primitives 已稳定；`tracecite-mcp@feature_for_agent` 已完成六原语薄适配、RetrievalSession 映射、真实 stdio MCP 验证，并已通过 Codex CLI 与 Pi Agent 两条真实 Host → MCP → Core 端到端 smoke。下一阶段不再继续扩 Core/MCP 语义面，而是把现有 Pi benchmark 的 TraceCite arm 平行迁移到标准 MCP Host 路径并重新做受控 A/B。**

---

## 2. 仓库与分支基线

### TraceCite Core

仓库：

```text
samstring/tracecite-core
```

正式 Agent 基线：

```text
feature_for_agent
```

Evidence Runtime 实验/实现分支：

```text
experiment/evidence-intelligence
```

稳定产品代码基线：

```text
127b43c402d29655c86230608eded3fcf2e8b40e
bench: exclude unavailable log case from log-code A/B
```

`feature_for_agent` 在该产品代码之上曾有纯文档 handoff commit：

```text
3d1f4b727a7bd74b3a3230e885d70ecb9a8c0310
docs: refresh agent and MCP handoff
```

本次更新会再增加一个纯文档提交。不要把文档 commit 误认为 Core Evidence Runtime 产品逻辑变化。

### TraceCite MCP

仓库：

```text
samstring/tracecite-mcp
```

目标分支：

```text
feature_for_agent
```

六原语改造、Host 验收已经完成。关键提交链：

```text
a6a9537d4b99940603b3d6055a98037d7e32cf2f
ci(mcp): test redesigned feature branch directly

 e19e8364000c16888933094fc5e3856b99d1762a
 test(mcp): add real stdio protocol smoke

 a08efd6fcc89496dd68766795442d3c145ff79d5
 test(host): use Pi adapter namespaced MCP tool

 01575e24b15df6f90f9b55770645ad28eff62195
 docs(mcp): record Codex and Pi host validation
```

其中 `a08efd6...` 是 Codex/Pi Host smoke 双绿时的功能验证代码基线；`01575e2...` 只在其上补充 README 文档。

---

## 3. 已稳定的最高级架构边界

核心原则保持不变：

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

### Core / MCP 不得输出或拥有

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
integrity verified        != causal conclusion verified
```

除非发现真正的 Core contract 缺陷，后续 MCP / Pi / Codex / Claude 集成不得为了单个 benchmark case 重新改变这条边界。

---

## 4. Canonical Agent-facing Evidence API

正式 Agent/MCP surface 只有六个 primitive：

```text
retrieve
materialize
replay
aggregate
traverse
verify
```

对应 MCP 工具：

```text
tracecite_retrieve
tracecite_materialize
tracecite_replay
tracecite_aggregate
tracecite_traverse
tracecite_verify
```

语义：

| Primitive | Core 机械职责 | 不负责 |
|---|---|---|
| `retrieve` | Caller 指定 target/query/scope，返回 Evidence、coverage、provenance、novelty | 选择调查方向 |
| `materialize` | 精确展开 caller 指定 range/ref | 判断是否证明假设 |
| `replay` | 精确重读已交付 immutable Evidence，不计新 Evidence | 把旧证据变成新支持 |
| `aggregate` | count/distinct/group 等确定性聚合 | causal ranking |
| `traverse` | caller 指定 seed/scope/limits 后做 bounded mechanical traversal | planner / next-best target |
| `verify` | integrity / manifest / source-version 等机械验证 | 验证自然语言根因 |

`probe/search/expand/sample/survey/...` 即使仍作为 Core compatibility surface 存在，也不是新的 MCP v1 正式 Agent surface。

---

## 5. RetrievalSession 是唯一 Evidence session memory owner

Canonical owner：

```text
RetrievalSessionState
RetrievalSessionStore
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

它不拥有：

```text
hypotheses
findings
root cause
evidence sufficiency
stopping decisions
```

MCP 当前已经按以下方式实现：

```text
MCP/Agent session_id
        ↓
RetrievalSessionStore
```

没有在 MCP 再实现 novelty / coverage / dedup 数据库。

默认 MCP state root：

```text
~/.tracecite/mcp/_retrieval_sessions/
```

可通过：

```text
TRACECITE_MCP_STATE_DIR
```

覆盖。

---

## 6. MCP v1 当前已完成

`tracecite-mcp@feature_for_agent` 当前已经不是旧的宽工具面。

主要实现文件：

```text
src/tracecite_mcp/server.py
src/tracecite_mcp/session.py
src/tracecite_mcp/providers.py
src/tracecite_mcp/source_policy.py
skills/tracecite/SKILL.md
tests/test_server.py
tests/test_stdio_integration.py
.github/workflows/ci.yml
.github/workflows/agent-host-smoke.yml
scripts/codex_app_server_smoke.py
scripts/pi_fake_openai_server.py
```

当前完成项：

1. `server.py` 只暴露六个 canonical MCP tools；
2. `retrieve/materialize/replay` 明确要求 `session_id` 并映射到 Core `RetrievalSessionStore`；
3. MCP 没有复制 Pi checkpoint / convergence / stop 策略；
4. 本地 source access 使用 Host-owned allowlist：
   `TRACECITE_MCP_ALLOWED_ROOTS`；
5. Provider 通过 Host process-local registry 注册，模型不能发送 Python provider 对象或可执行 provider snapshot；
6. Generic Skill 已是 Agent-neutral，不含 benchmark 特定根因路径或 stopping 建议；
7. 普通 unit/stdio/build CI 已覆盖 Ubuntu Python 3.10–3.14 与 macOS Python 3.14；
8. 已增加真实 MCP stdio SDK round-trip；
9. 已增加 Codex CLI 与 Pi Agent 两条真实 Host smoke。

---

## 7. MCP transport 与 Host 验收结果

### 7.1 真实 stdio MCP

提交：

```text
e19e8364000c16888933094fc5e3856b99d1762a
test(mcp): add real stdio protocol smoke
```

`tests/test_stdio_integration.py` 不直接调用 Python server 函数，而是：

```text
spawn tracecite-mcp stdio server
        ↓
MCP ClientSession.initialize
        ↓
list_tools
        ↓
call tracecite_retrieve
        ↓
repeat same session call
        ↓
verify repeated-evidence semantics
        ↓
call aggregate
```

对应 MCP CI Run：

```text
33377768857
```

结果：全绿。

### 7.2 Codex CLI Host

Host workflow：

```text
.github/workflows/agent-host-smoke.yml
```

Codex smoke 路径：

```text
Codex CLI / app-server
        ↓ MCP
tracecite-mcp
        ↓ public TraceCite API
tracecite-core
```

验证内容：

- 安装官方 `@openai/codex`；
- 通过 Codex MCP config 注册 stdio TraceCite server；
- Codex inventory 看到且只看到六个 canonical TraceCite tools；
- 通过 Codex app-server 的 MCP tool-call API 真正调用 `tracecite_retrieve`；
- 第一次返回新 Evidence；
- 同一 session 第二次调用返回 `new_evidence=0` 且有 repeated evidence；
- 不依赖真实模型推理/API key 完成 MCP transport 验证。

### 7.3 Pi Agent Host

Pi 本身没有与 Codex 相同的原生 MCP client surface，因此通过：

```text
pi-mcp-adapter
+ standard project .mcp.json
```

真实路径：

```text
Pi Agent
   ↓ Pi tool call
pi-mcp-adapter
   ↓ standard MCP config / stdio
tracecite-mcp
   ↓ public TraceCite API
tracecite-core
```

测试使用本地 deterministic OpenAI-compatible fake model 驱动一个真实 Pi Agent tool-call loop：

1. Pi 向模型暴露 adapter 的 `mcp` tool；
2. fake model 请求调用 TraceCite MCP retrieve；
3. adapter 通过 `.mcp.json` 启动/调用 `tracecite-mcp`；
4. Core 返回包含 `target event` 的 Evidence；
5. adapter 将真实 tool result 作为 `role=tool` 回送模型；
6. fake model 完成 Agent turn。

这里发现并确认了一个 **Pi adapter 特有命名行为**：

```text
MCP server name: tracecite
canonical MCP tool: tracecite_retrieve

pi-mcp-adapter internal route:
tracecite_tracecite_retrieve
```

这是 `pi-mcp-adapter` 的 `<server>_<tool>` namespace，不是 TraceCite 产品 API。**不要因此把 TraceCite 的 canonical MCP tool 改成双前缀。**

### 7.4 双 Host 绿灯

最终双绿 Host run：

```text
Agent Host MCP Smoke
Run 33379555848
```

结果：

```text
codex-host  success
pi-host     success
```

同一功能 HEAD 的普通 MCP CI：

```text
MCP CI
Run 33379555845
```

结果：Ubuntu 3.10–3.14、macOS 3.14 与 package build 全部 success。

因此目前可以认为：

> **TraceCite MCP v1 的 six-tool contract、stdio transport、session mapping，以及至少 Codex CLI / Pi 两种不同 Agent Host 的标准 MCP 接入路径已经得到实际端到端验证。**

---

## 8. Pi benchmark 层仍然与 MCP 产品层隔离

Core 仍保留 Pi-specific benchmark/adapter 文件，例如：

```text
benchmarks/agent-investigation/pi_ab_runtime.py
benchmarks/agent-investigation/pi_log_code_tracecite_extension.ts
benchmarks/agent-investigation/pi_session_to_transcript.py
benchmarks/agent-investigation/pi_tracecite_bridge.py
benchmarks/agent-investigation/pi_tracecite_extension.ts
benchmarks/agent-investigation/pi_tracecite_extension_impl.ts
.pi/skills/tracecite/SKILL.md
```

以及多条 `.github/workflows/pi-*.yml` benchmark/probe workflow。

这些目前仍有历史 benchmark/provenance 价值，不要一次性删除。

但它们属于：

```text
Pi Host / benchmark harness
```

而不是：

```text
TraceCite MCP product contract
```

特别是：

- Pi checkpoint/convergence logic 不进入 MCP；
- A/B 中禁止 Native evidence-content tools 的 guard 不进入 MCP；
- benchmark hidden gold/scorer 不进入 MCP；
- Pi transcript conversion 不进入 MCP；
- case-specific preferred investigation path 不进入 Skill/MCP。

---

## 9. 当前 benchmark 结论仍保持克制

历史 Pi A/B 目前较强证明的是：

> **TraceCite 能降低 Evidence/context 的重复传输和模型处理负担，尤其在大日志场景。**

不能据此宣称所有 case 都固定节省某个比例，也不能把 `input + cacheRead` 称为 billable tokens；应称 processed context/workload。

已知代表性结果：

### 140039

历史 Run #5 中曾出现：

```text
Native:    timeout
TraceCite: completed，找到 runc/seccomp/EINVAL 根因链
```

stop-time processed context 口径约：

```text
Native     ≈ 2.332M
TraceCite  ≈ 1.325M
observed delta ≈ -43.2%
```

但双方存在 provider rate-limit contamination，因此这对不能作为正式公平 A/B 因果结论。

### 139417

历史 runtime log 远端 404，已从 runnable log+code matrix 排除；保留历史 case 仅作 provenance。

### 140268

仍是 discovery-hard case；Native / TraceCite 都曾无法稳定找到隐藏 mechanism。不能说 TraceCite 已证明普遍提升 root-cause discovery/correctness。

### 140848

双方都曾找到 decisive panic/source mechanism，但 Agent 可能继续搜索到 timeout。TraceCite 能减少上下文膨胀，convergence 仍主要属于 Agent/Host 问题。

当前产品结论保持：

```text
已较强证明：bounded/provenance-aware Evidence flow 与 context efficiency
尚未证明：普遍提高 Agent root-cause correctness
仍需验证：标准 MCP Host 路径下的真实 A/B 是否保持同样优势
仍需改进：hard discovery + Agent convergence
```

---

## 10. 下一阶段：把 Pi benchmark 平行迁到标准 MCP

这是现在最重要的下一步。

不要立即删除旧 `pi_tracecite_bridge.py` / Pi extension。先做 **parallel standard-MCP benchmark arm**，确保可以和历史 bridge 结果比较与回归。

建议顺序：

1. 在 Core benchmark harness 新增/改造一条标准 MCP TraceCite arm：

```text
Pi Agent
  ↓
pi-mcp-adapter
  ↓ .mcp.json
tracecite-mcp@feature_for_agent
  ↓
tracecite-core@feature_for_agent
```

2. 保持 benchmark-only guard 在 Pi harness：
   - TraceCite arm 的 runtime evidence content 只能经 TraceCite；
   - `find/ls` 最多做定位，不作为 evidence content bypass；
   - guard 不进入 MCP 产品逻辑。
3. 保持同一个 Agent prompt / model / case / timeout / scorer / hidden-gold separation；
4. 先做 1 个 smoke case，确认：
   - Pi 真正调用 adapter/MCP；
   - TraceCite tool result 被 transcript 捕获；
   - scorer 可继续工作；
   - token/context accounting 没因 adapter transcript 格式失真；
5. 再做 4-case 或稳定性重复；
6. 比较：

```text
Native
vs
旧 Pi bridge TraceCite
vs
标准 MCP TraceCite
```

重点回答：

- 标准 MCP transport 是否保持 Evidence/context efficiency；
- adapter 是否引入明显额外 token/latency；
- RetrievalSession repeated-evidence 行为是否在真实 Agent trajectory 中生效；
- 旧 bridge 是否还包含 MCP 不应拥有的特殊行为；
- 标准 MCP 是否足以成为后续 Codex/Pi/其他 Host 的统一产品路径。

只有标准 MCP benchmark 路径稳定后，再考虑逐步退休旧 Pi bridge。

---

## 11. Generic Skill 后续原则

`tracecite-mcp/skills/tracecite/SKILL.md` 已经是 Agent-neutral 基线。

不同 Host 可以有薄包装，但共享语义必须保持：

```text
six tool semantics
no_match boundary
new_evidence / repeated_evidence boundary
replay boundary
provenance/source-version rules
identity/correlation safety
Agent owns causal reasoning and stop decision
```

不能加入：

```text
preferred hypothesis
benchmark-specific search path
known root cause / fix
causal recommendation
stop recommendation
```

---

## 12. 新对话接手顺序

下一次继续工作时：

1. 读本文件；
2. 检查 `tracecite-core@feature_for_agent` 当前 HEAD 与 CI；
3. 检查 `tracecite-mcp@feature_for_agent` 当前 HEAD；
4. 检查 MCP 两条 workflow：

```text
.github/workflows/ci.yml
.github/workflows/agent-host-smoke.yml
```

5. 不要重新做六原语 MCP 改造；它已经完成；
6. 不要重新证明基础 stdio transport；它已经完成；
7. 不要再问 Codex/Pi 能否接 MCP；两条 Host smoke 已经通过；
8. 直接从 **Pi benchmark 标准 MCP arm** 开始；
9. 旧 Pi bridge 暂时保留作对照，不立即删除；
10. 若 benchmark 出现问题，优先判断是：

```text
Host adapter issue
benchmark harness issue
model/provider variance
Core contract defect
```

只有最后一种才考虑改 Core public API。

---

## 13. 红线

1. 不把 planner / reasoning / root-cause logic 放进 TraceCite Core。
2. 不让 MCP 发出 `stop_recommended` / `evidence_sufficient`。
3. 不把 Pi convergence checkpoint 复制成 MCP canonical semantics。
4. 不在 MCP 重新实现 novelty / coverage / Evidence identity。
5. 不为了 benchmark 分数给 Skill/MCP 注入隐藏答案或 preferred search path。
6. 不把 benchmark guard 伪装成产品安全/语义能力。
7. 不把 processed context 当 billable tokens 宣传。
8. 不因为单个 difficult case 表现不好就扩大 Core public API。
9. 不因为 `pi-mcp-adapter` 有双前缀内部路由就改 TraceCite canonical tool 名。
10. 不在标准 MCP benchmark 稳定前删除旧 Pi bridge/provenance harness。
