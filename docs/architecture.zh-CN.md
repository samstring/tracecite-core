# TraceCite 架构设计

[English](architecture.md) | **简体中文**

状态：**规范性 / 当前（Normative / Current）**。适用于 `feature_for_agent_refacotr_shell` 的重构工作、官方领域扩展以及 Pi / Codex / Cursor / CLI / MCP / 自定义 Host。

> **Agent 负责想和决定；TraceCite 负责证据。**

本文是最高级 Living Architecture Contract。ADR / migrations 记录长期决策和迁移语义；本次 Evidence Shell / SourceVersion 重构详见 `docs/adr/0002-agent-evidence-shell-source-version.md`。

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
- 一个 RetrievalSession 内稳定的 SourceVersion / SessionSourceView；
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
4. 一个 RetrievalSession 对同一个 logical source 只绑定一个固定 SourceVersion；整个 session 内不得因为原始 mutable/live path 更新而悄悄切换版本。
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

## 4. SourceVersion / SessionSourceView

`SourceVersion` 表示调查实际看到的不可变 bytes，而不是一个可能继续变化的 pathname。

一个 RetrievalSession 第一次访问某个 logical source 时，Runtime 解析并绑定一个 `SessionSourceView`。之后同一个 session 内所有 search/run/materialize/replay 都复用该版本，即使原始 mutable/live source 已经变化，也不会重新 stat、snapshot、SHA 或 live cut。一次对话若持续复用同一个 RetrievalSession，就持续面对同一个稳定数据世界。

新 RetrievalSession 第一次访问该 source 时，才重新检查当前 source fingerprint。若 fingerprint 与最近已验证版本相同，则跨 session 直接复用原 snapshot/path、SHA 和 line metadata；只有 source 确实变化时才建立新 SourceVersion。

### 静态来源

明确 immutable 的文件不要求物理 copy。原文件本身可以作为 immutable source；SHA 第一次建立后缓存复用。

### 可能变化的普通文件

新 RetrievalSession 第一次访问 source 时先用 cheap fingerprint 判断是否可复用已有版本：

```text
device / file-id
inode when available
size
mtime_ns
ctime_ns
```

fingerprint 不变 -> 复用旧 snapshot/path、SHA、line metadata，不重新 copy、不重新 hash、不重新 count。

fingerprint 变化 -> 建立新 SourceVersion。Snapshot copy 时在同一顺序读取中同时计算 SHA 和 line count。Fingerprint 只是“是否可以复用已验证强 identity”的 cheap key，最终 Evidence identity 仍依赖 immutable bytes + SHA/version。

### Live 来源

Live 大文件优先使用 cooperative `live_cut` + immutable segments，不应在一个长对话里反复复制或切分同一累计文件。

```text
writer -> live.log
session first access -> live cut -> immutable segment N
writer continues -> new live.log
same session -> keep using bound immutable view
new session -> capture newer live bytes if source changed
```

历史 segment 不重新 copy、不重新 SHA。逻辑 SourceVersion 由有序 immutable segment manifest 组成；每条 Evidence 仍绑定具体 segment SHA + segment-local line range。

若 writer 未协作，当前实现使用机械验证的 append-only fallback：验证上一 capture boundary 附近 bytes 未变化后，只复制新增的完整行 bytes 到新 immutable segment。若不能证明连续性，则重新建立新的 immutable capture，而不是把未知变化错误地当 append。

当前 canonical public 名称是 `SessionSourceView` / `SessionSourceVersionStore`。内部历史实现仍保留 `QuestionSourceView` / `question_id` 兼容别名和旧持久化字段，不改变 session-bound 语义。

## 5. Evidence Shell / `tracecite_run`

Evidence Shell 是 Agent-facing 的统一机械搜索程序入口。Agent 可以组合搜索步骤，但 TraceCite 决定如何在当前 SourceVersion 上确定性执行。

示例：

```text
search '"statusCode":500'
| search 'ts-route-service'
| where latency >= 1000
```

当前 Shell 支持的通用机械能力包括：

- `all`；
- literal `search`；
- grep-like fixed / regex / invert / case-insensitive search；
- safe `regex`；
- `exclude` / `exclude-regex`；
- structured `where` comparison / contains / startswith / endswith / matches；
- `exists` / `missing`；
- `lines`；
- Host/tool 级 `last` / `since` / `until` / `segmenter` scope；
- `sort` / `reverse`；
- `take` / `head` / `first` / `last` / `tail`；
- `near` / `seek`；
- `count` / `group` / `distinct` / `uniq`；
- `emit`。

Evidence Shell 不是 unrestricted host bash；它只能只读访问授权 SourceVersion 和 TraceCite evidence/search primitives。不得 network、任意文件读取、shell escape、修改 Evidence 或绕过 transport policy。

Agent-facing 工具面应保持很小，目标形态是：

```text
tracecite_describe
tracecite_run
tracecite_materialize
```

旧 `retrieve/search/aggregate/...` 可继续作为 canonical/compatibility surface。Text `QueryTarget` 已归一到 Evidence Shell contract；复杂多步机械调查优先通过一次 `tracecite_run` 完成，避免每一步 tool output 都进入模型上下文。

## 6. Search -> Segment -> Complete Records

普通 Evidence Shell 搜索优先按下面顺序执行：

```text
Raw immutable SourceVersion
   -> raw physical-line candidate search
   -> candidate locator
   -> Segmenter local recovery
   -> Complete logical Record
   -> additional shell stages
   -> Evidence Budget Gate
```

不能把单个 grep physical line 当成最终 Evidence，尤其是 multiline log/trace。

对于可安全局部恢复的 JsonLine、单行 RawText、FormatSegmenter，以及 literal multiline FormatSegmenter，Runtime 先做 raw hit search，再只对 candidate 做 record recovery；没有隐藏 candidate-count limit。

如果 regex 语义可能跨多行、continuation state 无法局部证明，或者 time/range/pid scope 需要完整 record 语义，Runtime 可以回退到全 logical-record iteration，以 correctness 为先。

当前 Agent Shell hot path 不依赖 `search_text`，也不要求 `matched_records.jsonl`、`hits.jsonl`、`evidence.log`、filter history 或 unmatched-token summary。

## 7. Evidence Budget Contract

Evidence 最大 transport 预算只能由用户/Host 配置，例如：

```text
max_evidence_tokens
max_evidence_bytes  # hard safety cap
```

Agent tool schema **不得**暴露允许 Agent 调大这些值的参数。Materialize/replay 的 transport 上限同样必须服从 Host/User Evidence policy，而不是由 Agent 参数放宽。

如果完整 matched records 超过预算：

```text
status = too_broad
reason = MATCHED_EVIDENCE_BUDGET_EXCEEDED
refine_query = true
evidence = []
```

可以报告 `observed_at_least_tokens/bytes`；若为节省 I/O 提前停止，不得伪造 exact total。

若内部 aggregate 本身结果过大，则返回 `AGGREGATE_OUTPUT_BUDGET_EXCEEDED`，而不是把超大 group/distinct 列表传给模型。

有界 `group`/`distinct` 结果还必须防止单个超长字符串 key 穿过模型边界。超过 derived-value transport 阈值的 key 会变成 compact descriptor，包含有界 preview、长度、值摘要和代表性 Evidence URI；count、total、排序、Coverage 以及精确 source line 仍保持权威。短 key 继续使用历史 scalar 形状；需要完整长值时，Agent 应 materialize 该 URI 指向的行。

`too_broad` 后 Agent 可以：

- 更精确 literal/regex；
- 增加 search/filter/where；
- 缩小 time/range/source；
- 使用 aggregate 回答 count/group/distinct；
- 已知有效 anchor 时使用 near/seek；
- 更换更合适的搜索组合。

Agent 不可以：

- 调大 budget；
- 要求跳过 budget；
- 要求完整 locator dump；
- 用 first-N 伪装完整搜索。

显式 `first/last/head/tail/take` 仍可作为用户真正要求的 selection semantics，但必须明确是选择结果，不是完整匹配集合。

## 8. Internal MatchSet / intermediate state

`MatchSet` 是 Runtime 内部实现概念，不要求 Agent 理解，也不是当前 Agent API 的必要公开对象。它可以是 iterator、locator array、bitmap、range set、spill file 或 backend handle。

大型中间集合默认留在 Runtime：

```text
173,320 -> 4,901 -> 331 -> 5
```

Agent 只看到最终小结果。当前 all-or-refine shell 不要求公开 ResultHandle；如果未来真实跨调用 workflow 需要复用大型集合，再引入绑定 SourceVersion + QueryPlan identity 的稳定 handle，仍不得把完整集合传给模型。

Derived-value descriptor 属于这个 compact-result 边界：它不是对 SourceVersion Evidence 的有损替代，代表性 URI 是恢复精确值的 handle。

## 9. Canonical Evidence API

长期 canonical 机械原语继续保留：

- `retrieve`：caller 指定 source/scope/predicate -> Evidence + Coverage + Provenance + novelty/repetition；text QueryTarget 归一到 Evidence Shell；
- `materialize`：精确展开 caller 指定的不可变 source/version range/ref；
- `replay`：显式重读旧不可变 Evidence；novelty 仍为 0；
- `aggregate`：兼容性的确定性 count/distinct/group；Agent 文本调查优先使用 Shell aggregate；
- `traverse`：caller 指定 seed/scope/direction/limits 下机械遍历；
- `verify`：验证 integrity/source-version/Manifest/exact Evidence。

`tracecite_run` 是组合搜索/机械处理能力的 Agent program surface，不创建第二套 Evidence identity/session 语义。

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

同一 RetrievalSession/context 对同一个 logical source 始终复用第一次绑定的 SourceVersion。Host 不需要识别每条用户 message 的边界；如果“一次对话”就是一个 RetrievalSession，则整个对话固定使用同一 SourceVersion。只有创建新的 RetrievalSession，或未来显式调用 refresh source，才允许建立更新版本；禁止静默刷新。

## 11. Materialize / Provenance / Citation

Search candidate 与最终 Evidence 分离。只有在候选足够小、Agent 需要阅读/引用时才 materialize exact context。

最终 Evidence 必须可解析到：

```text
source/version identity
segment/file SHA when applicable
exact line/range or equivalent locator
exact raw content
```

TraceCite 管理的 immutable SourceVersion/segment 已有 SHA 后，Shell EvidencePointer、managed materialize 和 replay 直接复用该 identity，不重新 hash 全文件。SourceVersionStore 同时保留 latest source state 与 session-bound historical view，使旧 immutable segment 在新 SourceVersion 建立后仍可 replay。

对于 TraceCite 未冻结、仍可能被外部修改的 pathname，仍需要 integrity revalidation。

## 12. Agent / Host Boundary

Host 拥有 model/tool/context/wall-time budget、Evidence token/byte policy、source mode、RetrievalSession/conversation identity、tool exposure、prompt 和 native-tool telemetry。

Host 不需要为每条用户消息创建新 SourceVersion。只要同一次对话持续使用同一个 RetrievalSession/context，TraceCite 就持续复用其 source binding。新对话若使用新的 RetrievalSession，Runtime 会在该 session 第一次访问 source 时检查 fingerprint，并在未变化时跨 session 复用已有 snapshot + SHA。

Agent skill 必须教会 Agent：优先用 `tracecite_run` 合并机械搜索；`too_broad` 时 refine query；不能提高用户 budget；不请求全部 locator；最终需要引用时使用返回的 immutable `source_path + SHA + range` materialize。

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
| RetrievalSession seen/repeated/range/replay | 已实现 | 既有 Runtime + Shell admission |
| Raw-hit candidate-first + local complete-record recovery | 已实现 | `record_search.py` + `candidate_recovery.py` |
| `EvidenceShellPolicy` user/host-owned budget | 已实现 | Agent request 无 budget override；Pi materialize/replay 也服从 Host budget |
| `tracecite_run` Evidence Shell | 已实现 | literal/grep/regex/where/filter/sort/selection/near/seek/count/group/distinct |
| `too_broad` canonical transport status | 已实现 | 超预算不返回 Evidence body/locator dump |
| Artifact-free Agent search hot path | 已实现 | 不依赖 matched_records/hits/evidence.log/filter history |
| Agent QueryTarget 去除 high-cardinality EvidenceIndex | 已实现 | text retrieve/search 归一到 Evidence Shell |
| Session-level SourceVersion binding | 已实现 | 同一 RetrievalSession/source 固定一个版本；`SessionSourceView` 为 canonical public 名称 |
| Mutable fingerprint snapshot reuse | 已实现 | 新 session 首次访问时 unchanged -> reuse snapshot + SHA + line metadata |
| Snapshot SHA/count 单 pass | 已实现 | copy 同时 hash + newline count；不做 count snapshot + count original |
| LiveCut + immutable segment SourceVersion | 已实现 | 一个 session 首次访问时 freeze；新 session 可捕获新增 live bytes |
| Managed materialize/replay SHA reuse | 已实现 | immutable snapshot/segment 读取 exact range，不重新 whole-file SHA |
| Agent skill for shell/refinement | 已实现 | `.agents/skills/tracecite-investigate/SKILL.md` |
| Pi `tracecite_run` adapter | 已实现 | budget/source policy 由 Host 环境/产品配置持有 |
| Oversized derived-value transport | 已实现 | 长 group/distinct key 使用 preview + digest + Evidence URI descriptor |
| Public ResultHandle/MatchSet API | 待实现（延后） | 当前 all-or-refine contract 不需要公开 |
| Full regression + Native/TraceCite benchmark validation | 计划验证 | 代码完成后统一跑，不属于架构实现本身 |

## 16. 文档 / Governance

架构边界变化必须同步更新 `architecture.md` 和 `architecture.zh-CN.md`。不兼容架构变化需要 ADR；公开 schema/API 变化需要 migration note + tests。

当前设计 ADR：[ADR-0002](adr/0002-agent-evidence-shell-source-version.md)。
