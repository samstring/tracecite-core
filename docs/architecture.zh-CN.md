# TraceCite 架构设计

[English](architecture.md) | **简体中文**

状态：**规范性 / 当前（Normative / Current）**。适用于 `feature_for_agent_refacotr_shell` 的重构工作、官方领域扩展以及 Pi / Codex / Cursor / CLI / MCP / 自定义 Host。

> **Agent 负责想和决定；TraceCite 负责证据。**

本文是最高级 Living Architecture Contract。ADR / migrations 记录长期决策和迁移语义；本次 Evidence Shell / SourceVersion 重构详见 `docs/adr/0002-agent-evidence-shell-source-version.zh-CN.md`。

## 1. 产品边界

Agent 负责：

- 理解 Problem / Scope；
- 建立 Hypothesis 与调查方向；
- 选择搜索表达式和 Evidence Shell 程序；
- 因果推理和竞争解释；
- 判断 Evidence 是否足够；
- 最终答案、限定和 Stop decision。

TraceCite 负责确定性的 Evidence 机制：

- source/version 与 evidence identity；
- acquisition、snapshot/freeze、provenance、Coverage 与 integrity；
- 一次用户问题内稳定的 SourceVersion / QuestionSourceView；
- RetrievalSession 的 seen/repeated/covered-range memory；
- Evidence Shell 的机械执行和中间结果隔离；
- 用户配置的 Evidence transport budget 强制执行；
- 精确 materialization 与显式 replay；
- deterministic aggregate 与 caller-scoped traverse；
- 可选 InvestigationState coordination metadata；
- Extension / trust contract。

TraceCite Runtime 不得把 `root_cause_confidence`、`evidence_sufficient`、`next_best_query` 或 `stop_recommended` 当成 Runtime truth。

## 2. 架构不变量

1. Core 只提供通用、确定性的 Evidence 机制，不包含设备/产品/公司/应用/领域知识。
2. Core 不导入 Runtime 或具体 Domain package；Runtime 可依赖 Core。
3. Extension 只依赖公开 TraceCite contract，贡献领域事实/能力，不贡献 Agent reasoning policy。
4. 一个用户问题绑定一个固定 SourceVersion；调查中不得悄悄切换到更新后的 live bytes。
5. Search hit 不是 Evidence；至少要先经过 Segmenter 恢复完整 logical record。
6. Evidence transport token/byte budget 是 **User/Host Policy**，Agent 无权提高、绕过或动态覆盖。
7. 普通 Evidence Shell 搜索要么完整 matched records 在预算内，要么返回 `too_broad`；不得 first-N 后伪装成完整结果。
8. Oversized match set 不得通过完整 locator / EvidenceIndex dump 进入模型上下文。
9. Shell 中间数据和内部 MatchSet 不跨模型边界；只有最终小结果和显式 materialize 的 Evidence 可以进入 Agent context。
10. Canonical Evidence / Result 必须保持 provenance 与可恢复性。
11. `status`（执行）与认识层 `outcome` 分离；`too_broad` 是 transport fact，不是认识论结论。
12. Zero match、Coverage 不完整、missing evidence、source change、provider failure 都不能证明真实世界不存在。
13. RetrievalSession 只拥有机械 Evidence-session memory；不拥有 Hypothesis/root cause/sufficiency/stopping。
14. SHA 对每个 TraceCite 管理的 immutable SourceVersion/segment 只建立一次并复用。
15. Efficiency 只有在 correctness/support/provenance/recoverability 可接受后才算收益。

## 3. 逻辑架构

```text
                                  Domain Extensions
                              Mobile / CI / third-party
                                        |
                                        v
Raw Sources -> SourceVersion -> Evidence Runtime -> Integrations -> Agent Host
               |               |                  |              |
               |               |                  |              +-- Pi
               |               |                  |              +-- Codex
               |               |                  |              +-- Cursor
               |               |                  |              +-- MCP/custom
               |               |                  |
               |               |                  +-- compact projection / Context
               |               |
               |               +-- Evidence Shell / QueryPlan
               |               +-- internal MatchSet / intermediate rows
               |               +-- user Evidence budget gate
               |               +-- RetrievalSession
               |               +-- materialize / replay / aggregate / traverse
               |
               +-- immutable file / snapshot / live segments
               +-- SHA / manifest / line metadata / provenance

Agent owns: query program -> hypothesis -> causal reasoning -> sufficiency -> answer -> stop
```

## 4. SourceVersion / QuestionSourceView

`SourceVersion` 表示调查实际看到的不可变 bytes，而不是一个可能继续变化的 pathname。

一个用户问题开始时，Host/Runtime 解析一次 `QuestionSourceView`；本轮所有 search/run/materialize/replay 都复用该版本。

### 静态来源

明确 immutable 的文件不要求物理 copy。原文件本身可以作为 immutable source；SHA 第一次建立后缓存复用。

### 可能变化的普通文件

新用户问题开始时先用 cheap fingerprint 判断是否可复用已有版本：

```text
device / file-id
inode when available
size
mtime_ns
optional ctime/provider revision
```

fingerprint 不变 -> 复用旧 snapshot/path、SHA、line/index metadata。

fingerprint 变化 -> 建立新 SourceVersion。Fingerprint 只是“是否可以复用已验证强 identity”的 cheap key，最终 Evidence identity 仍依赖 immutable bytes + SHA/version。

### Live 来源

Live 大文件优先使用 cooperative `live_cut` + immutable segments，不应每个问题重新复制完整累计文件。

```text
writer -> live.log
question boundary -> live cut -> immutable segment N
writer continues -> new live.log
```

历史 segment 不重新 copy、不重新 SHA。逻辑 SourceVersion 可以由 segment manifest 组成。

无法 cooperative cut 时按能力退化：CoW clone/reflink -> 可证明 append-only 的 bounded byte view -> full copy fallback。

## 5. Evidence Shell / `tracecite_run`

Evidence Shell 是 Agent-facing 的统一机械搜索程序入口。Agent 可以组合搜索步骤，但 TraceCite 决定如何在当前 SourceVersion 上确定性执行。

示例：

```text
search '"statusCode":500'
| search 'ts-route-service'
| where latency >= 1000
```

Shell 的能力族包括：

- literal / grep-like search；
- regex；
- time/range/source scope；
- structured field predicate；
- filter/exclude；
- aggregate/count/group/distinct；
- sort/top/take/first/last；
- seek/near/range 等机械导航；
- 后续由 Capability Registry 注册的通用搜索 backend。

Evidence Shell 默认不是 unrestricted host bash；它只能只读访问授权 SourceVersion 和已注册 evidence/search primitives。不得 network、任意文件读取、shell escape、修改 Evidence 或绕过 transport policy。

Agent-facing 工具面应保持很小，目标形态是：

```text
tracecite_describe
tracecite_run
tracecite_materialize
```

旧 `retrieve/search/aggregate/...` 可以继续作为 canonical/compatibility surface，但复杂多步机械调查优先通过一次 `tracecite_run` 完成，避免每一步 tool output 都进入模型上下文。

## 6. Search -> Segment -> Complete Records

Evidence Shell 第一阶段产生 raw hit locator；Segmenter 决定一条完整 logical record 的边界。

```text
Raw SourceVersion
   -> search hits
   -> Segmenter
   -> Complete Records
   -> Evidence Budget Gate
```

不能把单个 grep physical line 当成最终 Evidence，尤其是 multiline log/trace。

当前实现阶段仍可复用 legacy `search_text` 以保持 regex/time/fold/segmenter 语义；目标 hot path 是直接 stream Record，不再要求 `matched_records.jsonl`、`hits.jsonl`、`evidence.log` 或 filter history。

## 7. Evidence Budget Contract

Evidence 最大 transport 预算只能由用户/Host 配置，例如：

```text
max_evidence_tokens
max_evidence_bytes  # hard safety cap
```

Agent tool schema **不得**暴露允许 Agent 调大这些值的参数。

如果完整 matched records 超过预算：

```text
status = too_broad
reason = MATCHED_EVIDENCE_BUDGET_EXCEEDED
refine_query = true
evidence = []
```

可以报告 `observed_at_least_tokens/bytes`；若为节省 I/O 提前停止，不得伪造 exact total。

`too_broad` 后 Agent 可以：

- 更精确 literal/regex；
- 增加 filter/where；
- 缩小 time/range/source；
- 使用 aggregate 回答 count/group/distinct；
- 更换更合适的搜索组合。

Agent 不可以：

- 调大 budget；
- 要求跳过 budget；
- 要求完整 locator dump；
- 用 first-N 伪装完整搜索。

显式 `first/last/top/take/sample` 仍可作为用户真正要求的 selection semantics，但必须明确是选择结果，不是完整匹配集合。

## 8. Internal MatchSet / intermediate state

`MatchSet` 是 Runtime 内部实现概念，不要求 Agent理解。它可以是 locator array、bitmap、range set、lazy iterator、spill file 或 backend handle。

大型中间集合默认留在 Runtime：

```text
173,320 -> 4,901 -> 331 -> 5
```

Agent 只看到最终小结果。若跨 tool call 必须继续使用大型集合，可以用稳定 `result_handle`，handle 必须绑定 SourceVersion 与 QueryPlan identity；不得把完整集合重新传给模型。

## 9. Canonical Evidence API

长期 canonical 机械原语继续保留：

- `retrieve`：caller 指定 source/scope/predicate -> Evidence + Coverage + Provenance + novelty/repetition；
- `materialize`：精确展开 caller 指定的不可变 source/version range/ref；
- `replay`：显式重读旧不可变 Evidence；novelty 仍为 0；
- `aggregate`：确定性的 caller-selected count/distinct/group；
- `traverse`：caller 指定 seed/scope/direction/limits 下机械遍历；
- `verify`：验证 integrity/source-version/Manifest/exact Evidence。

`tracecite_run` 是组合这些搜索/机械处理能力的 Agent program surface，不创建第二套 Evidence identity/session 语义。

## 10. RetrievalSession：唯一机械 Evidence Memory Owner

RetrievalSession 保存：seen Evidence identity、covered immutable ranges、source observations/generations、recent operations、request fingerprints、repeated/replay facts。

重复 Evidence：

```text
query A -> body E
query B -> same E again

new_evidence = 0
repeated_evidence > 0
matched_existing_evidence = [E ref]
```

`too_broad` 没有把 Evidence body 正式暴露给 Agent，因此不得把其内部扫描到的 rows 加入 `seen_evidence` 或 Coverage。

## 11. Materialize / Provenance / Citation

Search candidate 与最终 Evidence 分离。只有在候选足够小、Agent 需要阅读/引用时才 materialize exact context。

最终 Evidence 必须可解析到：

```text
source/version identity
segment/file SHA when applicable
exact line/range or equivalent locator
exact raw content
```

TraceCite 管理的 immutable SourceVersion 已有 SHA 后，下游 search/materialize/bridge 应复用该 identity，而不是每次重新 hash 全文件。对于 TraceCite 未冻结、仍可能被外部修改的 pathname，仍需要 integrity revalidation。

## 12. Agent / Host Boundary

Host 拥有 model/tool/context/wall-time budget、Evidence token policy、tool exposure、prompt 和 native-tool telemetry。

Agent skill 必须教会 Agent：优先用 `tracecite_run` 合并机械搜索；`too_broad` 时 refine query；不能提高用户 budget；不请求全部 locator；最终需要引用时 materialize。

当前仓库 Agent instruction source：`.agents/skills/tracecite-investigate/SKILL.md`。

## 13. Context / Correctness / Benchmark

TraceCite 的 token 目标不是“压缩已经准备返回的大结果”，而是让低价值中间大结果从一开始就不跨模型边界。

效率比较必须在 correctness/support/provenance/recoverability gate 后进行。正式 Agent benchmark 区分 `task_result` 与 `run_validity`；Provider 429/quota/outage/harness failure 是 infrastructure-invalid。

## 14. Dependency Direction

```text
tracecite_core
     ^
     |
tracecite.runtime
     ^
     |
+----+------------------+
|                       |
tracecite.extension   tracecite.integrations
|                       |
Domain Extensions     CLI / Pi / Codex / Cursor / MCP/custom
```

任何 Domain package 都不得成为 Core 或 Runtime 的 required dependency。

## 15. 当前实现与目标差距

| Capability | Status | 当前重构分支 |
|---|---|---|
| Existing SourceVersion identity (`sha256/cursor/generation/mutable`) | 已实现 | `evidence_identity.py` |
| RetrievalSession seen/repeated/range/replay | 已实现 | 既有 Runtime |
| Candidate-first literal scanner/local recovery | 已实现 | 既有 Runtime internal |
| `EvidenceShellPolicy` user/host-owned budget | 已实现第一版 | Agent request 无 budget override |
| `tracecite_run` Evidence Shell | 已实现第一版 | literal/regex/filter/where/count/group/distinct/explicit selection；继续扩展到全部现有搜索能力 |
| `too_broad` canonical transport status | 已实现第一版 | 超预算不返回 Evidence body/locator dump |
| Pi `tracecite_run` adapter | 已实现第一版 | budget 从 Host 环境/产品配置读取 |
| Agent skill for shell/refinement | 已更新 | `.agents/skills/tracecite-investigate/SKILL.md` |
| Search hot path 去除 `matched_records.jsonl` / legacy artifacts | 进行中 | 当前 shell 第一阶段仍暂用 `search_text` 保持语义兼容 |
| Agent query path 去除 high-cardinality EvidenceIndex | 进行中 | 新 shell 不生成 EvidenceIndex；旧 retrieve compatibility 尚待迁移 |
| Question-level SourceVersion cache / fingerprint reuse | 待实现 | 设计已在 ADR 固化 |
| LiveCut + immutable segment SourceVersion | 待接入 Agent Runtime | Core 已有 `live_cut.py` / `segment_store.py` 基础 |
| SHA/count full-file pass 合并与缓存 | 待实现 | bridge 已优先读取 `data.source_sha256`，完整 SourceVersion cache 尚未接入 |

## 16. 文档 / Governance

架构边界变化必须同步更新 `architecture.md` 和 `architecture.zh-CN.md`。不兼容架构变化需要 ADR；公开 schema/API 变化需要 migration note + tests。

当前设计 ADR：[ADR-0002](adr/0002-agent-evidence-shell-source-version.zh-CN.md)。
