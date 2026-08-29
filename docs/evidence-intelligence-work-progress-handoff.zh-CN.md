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
- Phase C relation-strength / reducer gate HEAD：`d722a1f31e4b55250625cdf5dd6be10d52ef000b`
- 未经明确确认，不合并到基础分支。
- Core 稳定前，不改 Mobile / MCP 上层业务设计。

当前阶段：**Phase C deterministic 已完成，进入 Phase D — State simplification。**

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

### 已处理的 P0/P1

- Agent public entry 已收敛到 typed `retrieve()`；
- Projection 不再打开 source 发现新 Evidence；
- retrieval success 不再等于 hypothesis `supported`；
- scoped identity integrity 已进入 canonical Runtime；
- Provider record identity 已在 public Runtime boundary namespaced；
- grouping 已保留 exact entity identity；
- weak relation 与 exact identity relation 已在 retention path 中区分；
- reducer score 已明确标注为 retention priority，不是 cause likelihood。

### Phase D 仍要处理的 P1

1. seen/context state owner 过多；
2. Agent compact/projection 路径过多；
3. investigate facade 重复；
4. SourceSession monkey-patch / 动态状态扩展长期过重；
5. RetrievalSession 尚未成为唯一 retrieval/context state owner。

长期状态 owner 目标只有：

```text
RetrievalSession
InvestigationState
```

---

## 5. Phase A — Runtime owns evidence semantics

状态：**deterministic COMPLETE；focused 未闭合但按用户决策不阻塞后续实验阶段。**

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

最近 focused run `33245944773`（HEAD `b6ecb1c9...`）：

```text
Mobile Payment: PASS
Flutter 179398: FAIL
Kubernetes 140268: FAIL
```

因此 focused 仍是 unresolved debt，不是 PASS。

---

## 6. Phase B — Entry path convergence

状态：**deterministic COMPLETE。**

已完成：

- Canonical benchmark host 使用 typed `EvidenceRequest` + `retrieve()`；
- public `tracecite` entrypoint `stateful_cli.main` 默认 search -> `QueryTarget` -> `retrieve()`；
- public expand -> `RangeTarget` -> `retrieve()`；
- `search --output-path` 仅作为明确 legacy side-effect fallback 保留；
- ContextEngine / ledger projection 仍在 Runtime result 之后工作；
- contract tests 防止 public CLI 再绕回 low-level semantic owner。

Gate：

```text
Core CI run 33246863204: PASS
Evidence Intelligence benchmark run 33246863162: PASS
```

---

## 7. Phase C — Identity / grouping safety

状态：**deterministic COMPLETE。**

### 7.1 Provider record identity

问题：不同 Provider 可以同时返回相同 local `id`，甚至相同 source-native `evidence_uri`；旧实现会在 canonical progress 前碰撞。

修复：

```text
Provider native record
  -> provider name + provider-local id
  -> canonical provider://<provider>/<record-id>
```

- provider name 是 namespace owner；
- source-native URI 只作为 provenance metadata 保留；
- duplicate provider names 被拒绝，因为 namespace 不可判定；
- provider name / record id 做 URI escaping；
- 第二次同一 retrieval 才正确进入 repeated-evidence 语义。

### 7.2 Grouping entity diversity

旧 grouping key：

```text
(source, kind, normalized_template)
```

会把不同 entity 的高基数事件折叠。

新 grouping identity：

```text
(source, kind, normalized_template, exact_entity_signature)
```

- 同一 exact entity 的重复消息仍可压缩；
- 不同 entity 永不因为模板 normalization 被折叠；
- 无 entity 的历史 group key / group id 保持不变；
- entity set 顺序不影响 identity。

### 7.3 Relation strength / reducer semantics

事实层 `CorrelationGraph` 保持中立，不加入 cause weight。

Reducer 单独使用 mechanical retention path cost：

```text
exact entity / confidence=1 declaration -> cost 1
strong partial relation -> higher cost
weak relation -> still higher cost
```

因此 temporal proximity 可以帮助扩大 evidence frontier，但不会获得与 exact identity 相同的 retention boost。

同时：

```text
score_semantics = retention_priority
```

以及 diagnostics：

```text
retention_priority_not_causal_likelihood
```

明确禁止消费者把 score 当 root-cause probability。

### 7.4 Gate

HEAD `d722a1f31e4b55250625cdf5dd6be10d52ef000b`：

```text
Core CI run 33247276940: PASS
Evidence Intelligence benchmark run 33247276942: PASS
```

Phase C deterministic 完成。

---

## 8. Phase D — State simplification

状态：**CURRENT / 进行中。**

目标：

1. 收敛 RetrievalSession；
2. 合并 ContextEngine / EvidenceContextEngine 的重复 seen/context ownership；
3. InvestigationState 只保留 reasoning/audit state；
4. SourceSession 正式 schema 化，减少 monkey-patch/dynamic ownership；
5. 收敛重复 Agent compact/projection owner；
6. deterministic gate；
7. 更新本文档。

设计约束：

- retrieval novelty / covered ranges / seen Evidence 归 RetrievalSession；
- hypothesis/test/audit/decision trail 归 InvestigationState；
- projection 只做 transport shaping，不拥有 Evidence truth/state；
- Context optimization 可以引用 canonical state，但不能成为第二套 evidence truth owner；
- 不为了“少类/少文件”把职责重新混回 InvestigationState。

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

不复制 Router / Integrity / grouping / reducer / state owner 内部逻辑。

---

## 11. 当前一句话结论

> **Phase A Runtime evidence semantics、Phase B public entry convergence、Phase C identity/grouping/relation-strength 已完成 deterministic 收敛；focused correctness 仍有 Flutter / 140268 未闭合，但按用户明确决策暂不阻塞实验阶段推进。当前进入 Phase D，开始收敛 retrieval/context state ownership；Final Gate 仍保留完整 correctness/no-harm 要求。**
