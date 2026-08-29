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
- Phase B public CLI convergence code：`0c872fc5bc3c7e4ce2d42164d23b56d2f33dfdb3`
- Phase B contract tests HEAD：`d36f11e3394cebfd567cd93a8eae154fa42c8739`
- 未经明确确认，不合并到基础分支。
- Core 稳定前，不改 Mobile / MCP 上层业务设计。

当前阶段：**Phase B deterministic 已完成，进入 Phase C — Identity / grouping safety。**

### 1.1 Focused gate 豁免说明

2026-08-29 用户明确决定：

> 当前 focused real-model gate 可以暂不过，继续后续阶段。

这只表示 **focused 不再作为 A -> B -> C -> D 的实验阶段转换 blocker**，不表示 focused PASS，也不允许删除、降低或伪造 correctness 结果。

因此后续必须一直保留以下事实：

- focused 未闭合；
- no-harm 规则本身未取消；
- Final Gate 仍必须显式报告所有 unresolved / regression；
- 未解决的 focused correctness 不能在最终稳定结论中被写成 PASS。

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

Agent 负责 hypothesis、causal reasoning、root-cause conclusion、fix proposal。

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

硬优先级：

> **Correctness > Evidence Fidelity > Token Saving**

No-Harm 规则保持：

```text
free_shell passed == true
AND tracecite passed != true
=> no-harm regression
```

Token 节省、tool output 变小、context 不 overflow 都不能抵消 correctness 退化。

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

`probe/search/expand/sample/survey/...` 继续作为兼容接口和内部 primitive，但 Agent-facing host 不应在这些低层工具上复制 routing / integrity / projection 语义。

目标主链：

```text
Raw Source / Provider
  -> Canonical Identity
  -> Discover (Query -> EvidencePointer)
  -> Materialize (Pointer -> EvidenceWindow)
  -> Evidence Integrity
  -> EvidenceGap
  -> Minimal Retrieval Action
  -> Agent-visible Evidence
  -> Agent hypothesis / RCA
```

Router 只允许管理：

```text
DIRECT -> BOUNDED -> INVESTIGATE
```

禁止 Router 推断 root cause、给 hypothesis 排名或按 benchmark case 特判。

---

## 4. 已确认的结构风险

### P0

1. Agent 入口曾未统一：部分 CLI / integration 直接使用 `tools.search()/expand()`。
2. Projection 曾打开 source、补结构上下文和 scoped identity；这些语义必须由 Runtime owner。
3. Materialization 仍存在重复实现。
4. retrieval success 不能等于 hypothesis `supported`。
5. Provider record identity 必须全局 namespaced。
6. Scoped entity identity 必须进入主身份 contract。
7. Grouping 不得 normalize away entity identity。
8. EvidenceGap 必须继续从分散提示收敛到 canonical gap/progress/action 语义。

### P1

1. seen/context state owner 过多；
2. Agent compact/projection 路径过多；
3. investigate facade 重复；
4. exact relation 与 weak temporal relation retention 语义不足；
5. reducer score 存在 causal salience 风险；
6. SourceSession monkey patch 状态扩展长期过重。

长期状态 owner 目标只有：

```text
RetrievalSession
InvestigationState
```

---

## 5. Phase A — Runtime owns evidence semantics

### 5.1 已落地

- Agent projection 不再打开 source 发现新 Evidence；
- structured search fidelity 移入 canonical Runtime；
- scoped identity integrity 移入 Runtime；
- identity gap 接入 `missing_evidence` / progress；
- public retrieval outcome 使用 `not_assessed`，不把 search/read success 写成 `supported`；
- canonical identity integrity 使用 `data.evidence_integrity.scoped_identity`；
- actionable gap 可提升为 `data.actionable_retrieval`；
- local ID 明确携带 `identifier_only_correlation_safe=false`；
- identifier search 可推进到 observed scoped entity，再推进到 Runtime-observed sibling family；
- canonical benchmark host 可要求 Agent 优先执行 Runtime actionable retrieval；
- 没有加入 Kubernetes / Flutter / gold 特判。

### 5.2 Deterministic

Phase A deterministic gate 已 PASS，包括 Core CI、Ubuntu Python matrix、macOS Python、Evidence Intelligence deterministic benchmark。

### 5.3 Focused 当前事实

历史 focused 已证明：

- Mobile Payment 多轮能够 PASS/PASS，且部分 run TraceCite token 更低；
- Flutter 存在真实模型波动，历史既有有效 TraceCite PASS，也有 FAIL；
- Kubernetes 140268 中 shell 多次 context overflow，而 TraceCite 能 bounded 完成 retrieval，但 RCA correctness 尚未稳定闭合；
- 140268 已暴露 `testdevice`、scoped identity gap、sibling family 等机械证据导航问题；
- 这些问题只能通过通用 Runtime/host 契约修复，不允许 case-specific 修补。

最近 focused run `33245944773`（HEAD `b6ecb1c9...`）：

```text
Mobile Payment: PASS
Flutter 179398: FAIL
Kubernetes 140268: FAIL
```

因此：

> **Phase A focused 仍未通过。它目前仅被用户豁免为阶段转换 blocker，不是 PASS。**

---

## 6. Phase B — Entry path convergence

状态：**deterministic COMPLETE；focused 按用户决策不阻塞。**

### 6.1 已完成

1. Canonical benchmark host 已使用：

```text
EvidenceRequest
QueryTarget / RangeTarget / SourceTarget
retrieve()
project(profile="agent")
```

2. public `tracecite` console entrypoint 确认为：

```text
tracecite.integrations.stateful_cli:main
```

3. public CLI 默认 `search` 已改为：

```text
CLI args
 -> QueryTarget
 -> EvidenceRequest
 -> retrieve()
 -> canonical Runtime result
 -> CLI projection / ledger / context transport
```

4. public CLI `expand` 已改为：

```text
CLI args
 -> RangeTarget
 -> EvidenceRequest
 -> retrieve()
 -> canonical Runtime result
 -> CLI rendering
```

5. `search --output-path` 保留显式 legacy fallback，因为“写 filtered artifact”当前还没有进入 `QueryTarget` contract；没有静默丢失该兼容行为。

6. `tests/test_stateful_cli.py` 新增 contract tests：

- search 必须构造 typed `QueryTarget` 并调用 `retrieve()`；
- expand 必须构造 typed `RangeTarget` 并调用 `retrieve()`；
- routing / `not_assessed` canonical semantics 可穿过 public CLI；
- `--output-path` 明确走 legacy compatibility；
- ContextEngine / ledger projection 仍正常；
- adapter 在调用结束后必须恢复，不污染进程全局 CLI 状态。

### 6.2 Gate

HEAD `d36f11e3394cebfd567cd93a8eae154fa42c8739`：

```text
Core CI run 33246863204: PASS
Evidence Intelligence benchmark run 33246863162: PASS
```

Phase B 的主要 entry-convergence 目标因此已完成。

仍保留的 compatibility debt：

- `integrations.cli` 内部仍暴露 low-level search/expand symbol，供 legacy/internal path 使用；
- `search --output-path` 仍直接调用 legacy primitive；
- 未来若把 artifact-writing 纳入 typed Runtime contract，可再消除这一 fallback。

这些不能重新成为 Agent-facing semantic owner。

---

## 7. Phase C — Identity / grouping safety

状态：**CURRENT / 进行中。**

顺序：

1. Provider record IDs 全局 namespace；
2. scoped entity identity contract 完整化；
3. grouping 保留 entity diversity；
4. correlation exact/weak relation-strength no-harm；
5. reducer 只表达 retention priority，不表达 cause likelihood；
6. deterministic gate；
7. 更新本文档；
8. focused 作为非阻塞观测继续保留。

Phase C 禁止：

- 通过 benchmark case 名、gold、已知 root cause 推导 identity；
- 把 sibling fan-out 当成 identifier reuse 证明；
- 把 severity/error/timeout 当 cause probability；
- 为了压缩而删除 entity/source/provenance diversity。

---

## 8. Phase D — State simplification

Phase C deterministic 完成后进入：

1. 收敛 RetrievalSession；
2. 合并 ContextEngine / EvidenceContextEngine 的重复 seen/context ownership；
3. InvestigationState 只保留 reasoning/audit state；
4. SourceSession 正式 schema 化；
5. 收敛重复 Agent compact/projection owner；
6. deterministic gate；
7. 更新本文档。

Focused 继续保留为非阻塞实验信号，不伪造 PASS。

---

## 9. Final Gate

阶段性 focused 豁免 **不等于 Final Gate 豁免**。

最终稳定结论前必须重新运行并报告：

1. 完整 runnable 16-case × free-shell / TraceCite；
2. no-harm regression count；
3. 4 个 scale TraceCite context overflow；
4. `140848` 等 scale 优势是否保持；
5. small/ordinary case 是否出现数量级 token/tool-round 放大；
6. 当前 Flutter / 140268 unresolved 是否真正闭合。

如果 correctness 仍失败，文档必须写 FAIL / unresolved，不得因为阶段曾被豁免而改写成 PASS。

历史 16-case 基线 `33199132708`：

```text
13 valid paired aggregate:
free_shell input = 1,292,903
TraceCite input = 656,225
aggregate reduction ≈ 49.24%
```

该 aggregate 被 `kubernetes-140848` 大幅主导，不能宣传成一般场景平均节省 49%。历史普通 case 中 TraceCite 仍存在 token overhead，Final Gate 必须继续观察分布而不是只看 aggregate。

---

## 10. Core 稳定后的 Mobile / MCP

顺序保持：

```text
Core contract stable
 -> 更新最终测试事实
 -> 同步 core for_agent
 -> Mobile for_agent
 -> MCP for_agent
 -> contract / integration tests
```

Mobile / MCP 只消费稳定的：

```text
retrieve / investigate / project / capability
```

不复制 Router / Integrity / grouping / reducer 内部逻辑。

---

## 11. 当前一句话结论

> **Phase A 的 Runtime evidence semantics 和 Phase B 的 public entry convergence 已完成 deterministic 收敛；focused correctness 仍有 Flutter / 140268 未闭合，但按用户明确决策暂不阻塞实验阶段推进。当前进入 Phase C，优先处理 provider identity namespace、scoped identity 与 grouping diversity；Final Gate 仍保留完整 correctness/no-harm 要求。**
