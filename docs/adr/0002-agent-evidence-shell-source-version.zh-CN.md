# ADR-0002：Agent Evidence Shell、SourceVersion 与 Evidence Budget

## 状态

Accepted for `feature_for_agent_refacotr_shell`.

## 背景

现有 Agent 路径已经具备搜索、segment、EvidencePointer、provenance、session novelty/coverage、materialize 等能力，但在大结果与 live source 场景存在明显问题：

- 每次搜索可能重复 snapshot、count、SHA；
- live source 使用完整 copy snapshot 时，大文件成本高；
- `matched_records.jsonl` / `evidence.log` / `hits.jsonl` 等 artifact 在 Agent hot path 产生额外 I/O；
- 大结果会进入 `EvidenceIndex`，完整 locator 列表可能直接进入 Agent 上下文；
- Agent 需要多轮调用 search/filter/aggregate 时，中间结果会反复进入模型上下文；
- 当前 output limit 更偏 candidate/evidence 数量，无法稳定约束真正进入模型的 token 规模。

本 ADR 将 Agent 调查路径统一为：固定 SourceVersion + Evidence Shell + matched-result budget gate + 最终 Evidence materialize。

## 决策摘要

1. 一个用户问题对应一个固定 `QuestionSourceView` / `SourceVersion`，整个 Agent 调查期间所有搜索、shell、segment、materialize 都只操作该版本。
2. Evidence 最大输入预算属于 **User Policy**，只能由用户或上层产品配置；Agent 无权动态放宽。
3. Agent 可以改变搜索表达式、组合 shell 操作、缩小范围，但不能提高 Evidence budget、绕过 budget 或要求把超限结果按“完整结果”返回。
4. 搜索结果先经过 shell/search -> hit -> segment -> complete record，得到完整 matched records 语义。
5. 不使用 first-N 作为搜索语义。若完整 matched result 超过用户配置的 Evidence budget，则返回 `TOO_BROAD / REFINE_QUERY`，不返回部分 Evidence、不生成 EvidenceIndex locator dump。
6. 若 matched result 未超预算，则进入现有 provenance / novelty / coverage / Evidence / materialize 流程。
7. Agent hot path 不再依赖 `matched_records.jsonl`、`evidence.log`、`hits.jsonl`、完整 `EvidenceIndex`；这些 legacy artifact 如仍被 CLI/兼容路径需要，可保留在非 Agent 路径。
8. 新增统一 `tracecite_run` / Evidence Shell。Shell 覆盖现有全部搜索能力，并允许在一次 tool call 内组合搜索、过滤、提取、聚合、排序、定位等机械操作；中间结果不跨模型边界。
9. 改版后的 Agent 使用方式必须通过仓库 skill 教会 Agent，包括 budget contract、TOO_BROAD 处理、shell 搜索策略、materialize 时机。

---

## 1. 核心模型

```text
User Question
    |
    v
QuestionSourceView / SourceVersion
    |
    v
Evidence Shell / tracecite_run
    |
    +--> search / regex / structured search / filter / extract
    +--> aggregate / group / sort / seek / near / range
    |
    v
Hit Locators
    |
    v
Segmenter
    |
    v
Complete Records
    |
    v
Matched Result Budget Gate
    |                    |
    | exceeds            | within budget
    v                    v
TOO_BROAD             Existing Evidence Flow
REFINE_QUERY          provenance
(no partial body)     novelty / coverage
(no EvidenceIndex)    materialize
                       |
                       v
                    Evidence
                       |
                       v
                    Citation
```

### 1.1 SourceVersion

`SourceVersion` 表示本轮调查实际看到的不可变 bytes，而不是一个不断变化的 pathname。

最小 metadata：

```text
SourceVersion
- source_id
- version_id
- source_kind
- immutable files / segments
- fingerprint
- sha256 or segment sha256 list
- bytes
- line metadata/index when available
- created_at
```

同一个 Agent investigation 期间不得切换 SourceVersion。

### 1.2 Evidence Program / Evidence Shell

Agent 可以表达完整机械调查，例如：

```text
search '"statusCode":500'
| search 'ts-route-service'
| near first before=2 after=3
```

或未来等价的结构化 DSL。

TraceCite 内部可以编译成 QueryPlan；Agent 不需要知道底层是 candidate_search、regex engine、structured extractor 还是其他 backend。

### 1.3 MatchSet / intermediate result

MatchSet 只作为 Runtime 内部实现概念。Agent 不需要理解或接收完整 locator 集合。

如果跨 tool call 需要继续操作大型结果，可以返回稳定 `result_handle`，但完整集合仍留在 Runtime。

### 1.4 Evidence

Evidence 是最终可被 Agent 阅读和引用的 immutable 原始内容。

搜索命中 != Evidence。

完整链路：

```text
SourceVersion -> Search -> Segment -> Complete Record -> Budget Gate -> Evidence
```

---

## 2. Evidence Budget Contract

### 2.1 Budget 只能由用户设置

Evidence transport budget 是用户策略，不是 Agent 参数。

```text
EvidenceBudget = UserPolicy
```

Agent 允许：

- 修改 query；
- 增加过滤条件；
- 改成 regex/structured search；
- 缩小 source/range/time window；
- aggregate 后再搜索；
- 使用 shell pipeline 将中间结果继续缩小。

Agent 禁止：

- 动态调大 max tokens；
- 请求跳过 budget；
- 将超限结果拆成“部分结果但声称完整”；
- 使用 EvidenceIndex 把全部 locator 导入上下文；
- 通过 shell `emit all` 绕过 transport policy。

### 2.2 Budget 以 token 为主，bytes 为安全上限

用户可配置：

```text
max_evidence_tokens
max_evidence_bytes   # optional hard safety cap
```

`max_evidence_tokens` 是语义主限制。

bytes cap 用于在 tokenizer 估算前提供快速 hard stop，避免极端 payload。

### 2.3 超限语义

当完整 matched records 超预算：

```json
{
  "status": "TOO_BROAD",
  "reason": "MATCHED_EVIDENCE_BUDGET_EXCEEDED",
  "budget_tokens": 12000,
  "observed_at_least_tokens": 12001,
  "guidance": "Refine the search query or narrow the source/range. The evidence budget cannot be increased by the Agent."
}
```

如果执行为了节省 I/O 在确认超限后提前结束，应使用 `at_least_*`，不能伪造 exact total。

超限时：

- 不返回 matched record bodies；
- 不返回完整 locator list；
- 不进入 EvidenceIndex；
- 不返回 first-N 伪装成完整搜索结果；
- Agent 根据 skill 重新生成更精确的 Evidence Shell 程序。

---

## 3. Search -> Segment -> Matched Records

### 3.1 Shell 搜索负责找到 raw hits

Shell 必须覆盖现有搜索能力，包括但不限于：

- literal search；
- regex；
- time/range scope；
- structured field matching；
- last/since/until；
- fold / segmenter 相关搜索；
- 后续新增 backend capability。

不要求底层都通过系统 bash 实现。Agent-facing shell 可以编译为受控 QueryPlan。

### 3.2 Segment 恢复完整 record

Raw hit 只代表物理命中位置。

```text
hit -> segmenter -> complete logical record
```

budget 判断基于最终会成为 Evidence 的完整 logical record，而不是 grep 行本身。

### 3.3 不做 candidate first-N truncation

搜索必须保持明确语义：

```text
完整且未超限 -> 进入 Evidence 流程
超限          -> TOO_BROAD
```

不能：

```text
只取前 20 条 -> Agent 误认为搜索完整
```

---

## 4. `matched_records.jsonl` 与 EvidenceIndex

### 4.1 Agent hot path 不再要求 `matched_records.jsonl`

理想执行：

```text
scanner
 -> hit
 -> segment
 -> complete record
 -> in-memory / streaming accumulator
 -> token/byte budget gate
 -> Evidence projection
```

不再：

```text
record
 -> serialize matched_records.jsonl
 -> read back
 -> EvidencePointer
 -> read again
 -> EvidenceIndex
```

若 CLI、debug、legacy filter 仍需要 records artifact，可以保留为 opt-in compatibility artifact，但不得成为 Agent runtime 的必要步骤。

### 4.2 Agent 搜索路径取消完整 EvidenceIndex

完整 locator list 不再作为大搜索结果 transport。

EvidenceIndex 如仍用于 legacy API，应与 Agent compact transport 隔离。

---

## 5. Snapshot / SourceVersion 策略

### 5.1 同一用户问题：只建立一次版本

```text
question start
 -> resolve SourceVersion V17
 -> all Agent operations use V17
 -> no repeated snapshot
 -> no repeated SHA
 -> no repeated count-original/count-snapshot
```

### 5.2 静态 immutable source

明确 immutable 的 source：

- 不做物理 copy；
- original path 即 immutable source；
- SHA 第一次计算一次并缓存；
- 后续直接复用。

### 5.3 普通可能变化的文件

新用户问题开始时先做 cheap fingerprint：

```text
device/file-id
inode when available
size
mtime_ns
optional ctime/provider revision
```

如果 fingerprint 与已验证 SourceVersion 相同：

```text
reuse old SourceVersion
reuse old snapshot path
reuse old SHA
reuse old line/index metadata
```

不重新 snapshot，不重新 SHA。

如果 fingerprint 变化：建立新 SourceVersion。

fingerprint 只用于判断是否可以复用已存在强 identity；Evidence 的最终 identity 仍由 immutable bytes + SHA 保证。

### 5.4 Live source

Live source 优先使用现有 `live_cut` + immutable segments，而不是每轮 `shutil.copy2` 整个大文件。

```text
writer -> live.log
question start -> cooperative live cut
                  |
                  +-> immutable segment N
writer continues -> new live.log
```

每个 segment：

- freeze once；
- SHA once；
- line/index metadata once；
- 后续 SourceVersion 复用已有 segment metadata。

逻辑 SourceVersion 可由 segment manifest 组成：

```text
V20 = [S1@shaA, S2@shaB, S3@shaC]
```

Version identity 可对小型 manifest 计算 hash，无需重新 hash 全部历史 bytes。

### 5.5 LiveCut 无法协作时的 fallback

优先级：

1. cooperative live cut；
2. filesystem CoW clone/reflink；
3. 对可证明 append-only 的源记录 question-start byte boundary，形成 bounded immutable view；
4. full copy fallback。

不能简单 rename 一个其他 writer 仍持有 fd 的文件并假定其已经 immutable。

---

## 6. SHA 与 line count

### 6.1 SHA 只建立一次

一旦 SourceVersion/segment 已经建立 SHA：

- search 不再 hash；
- aggregate 不再 hash；
- materialize 不再 hash；
- Agent bridge 不再 fallback hash 同一版本；
- provenance 直接引用缓存的 SourceVersion identity。

仅当外部 path 未被 TraceCite 冻结/管理时，才需要重新验证 expected SHA。

### 6.2 删除重复 count

不在每次搜索中重复：

```text
count(snapshot)
count(original)
```

若 total lines 必需，应在 SourceVersion 建立或首次 scan/index 时获取并缓存。

对新 segment，可把这些操作合并在一次 sequential scan：

```text
read bytes
 -> SHA update
 -> newline offsets/count
 -> current search/probe when applicable
```

---

## 7. Evidence Shell Contract

Agent-facing 主入口建议保持极少：

```text
tracecite_describe
tracecite_run
tracecite_materialize
```

`tracecite_run` 执行完整 Evidence Program。

Shell/DSL 至少应能表达现有全部搜索能力，并支持机械组合：

```text
search / grep
regex
where / filter
extract
count
group / aggregate
sort
top / take
first / last
range
seek
near
intersect / exclude when needed
emit
```

实现时可以先映射现有 primitives，再逐步补足；不得因为新 shell 接口而丢失现有搜索表达能力。

### 7.1 Shell 安全边界

默认不是 unrestricted host bash。

Evidence Shell 只能：

- 只读访问当前 SourceVersion；
- 调用已注册 evidence/search primitives；
- 在 Runtime 内处理中间集合；
- 输出受用户 budget 强制约束的结果。

默认禁止：

- 任意文件系统读取；
- network；
- shell escape/subprocess；
- 修改 Evidence/source；
- 任意输出绕过 budget。

若未来支持受信任的 native shell backend，也必须通过同一 SourceVersion 和 output gate。

---

## 8. Session / Novelty / Coverage / Materialize

现有这些机制继续保留：

- provenance；
- Evidence identity；
- novelty；
- repeated Evidence suppression；
- coverage；
- materialize；
- exact citation。

新的 Shell 主要替换/扩展的是：

```text
search execution -> candidate/matched-record generation
```

而不是重写最终 Evidence integrity 层。

超限结果因为没有成为 Evidence，不应污染 `seen_evidence` / coverage。

---

## 9. Agent Skill

必须更新 `.agents/skills/tracecite-investigate`（以及其他实际接入 Agent 的 instruction surface），明确教会 Agent：

1. 优先使用 `tracecite_run` 完成多步机械搜索，减少中间 tool output；
2. Evidence budget 是用户策略，Agent 不得要求增加；
3. 收到 `TOO_BROAD` 时必须缩小 query、范围、时间、字段或增加过滤；
4. 不要要求完整 locator dump；
5. 不要把 `take/head` 当作解决超宽查询的默认正确性手段，除非任务本身明确只需要 top/first/last；
6. shell 命中先经过 TraceCite segmenter 恢复完整 record；
7. 只有在候选足够小、需要阅读/引用时才 materialize；
8. 已看过 Evidence 应依赖 novelty/coverage，不重复索取正文；
9. 同一问题使用固定 SourceVersion，不主动刷新 live source；新用户问题由 Runtime 决定是否复用或生成新 SourceVersion。

---

## 10. 分阶段实现

### Phase 0：阻止上下文爆炸

- Agent projection 不再生成完整 EvidenceIndex locator list；
- 增加用户配置 Evidence token budget；
- 超限明确 `TOO_BROAD / REFINE_QUERY`；
- Agent 不可覆盖 budget。

### Phase 1：Search hot path 简化

- search -> hit -> segment -> record -> budget accumulator；
- Agent hot path 移除 `matched_records.jsonl` 必需依赖；
- 移除不必要的 `evidence.log` / `hits.jsonl` / filter history hot-path I/O；
- 保留 legacy compatibility path。

### Phase 2：Evidence Shell

- 新增 `tracecite_run`；
- 映射现有所有搜索能力；
- 支持一条程序内 search/filter/extract/aggregate/sort/seek/near；
- 中间结果不进入 Agent context。

### Phase 3：SourceVersion

- 一次用户问题固定 SourceVersion；
- fingerprint unchanged 复用 snapshot + SHA；
- SHA/count/index metadata cache；
- bridge/runtime 不再重复 hash。

### Phase 4：Live source

- Agent runtime 接入 `live_cut`；
- `segment_store` 扩展 SHA/index metadata；
- SourceVersion 支持 immutable segment manifest；
- 新问题只冻结新增 live delta，历史 segment 不复制不重 hash。

### Phase 5：Skill 与 benchmark

- 更新 Agent skill；
- 增加 TOO_BROAD/refinement tests；
- 增加 snapshot reuse / SHA reuse tests；
- 增加 livecut segment reuse tests；
- 重新跑已有 Native vs TraceCite benchmark，关注：
  - correctness；
  - provider fresh input tokens；
  - max single tool output；
  - snapshot/hash full-file passes；
  - wall time。

---

## 11. 不变量

重构后必须始终满足：

1. **Canonical source is immutable per investigation.**
2. **Evidence budget is user policy, never Agent policy.**
3. **Oversized search results never cross the model boundary.**
4. **No silent first-N truncation pretending to be complete search.**
5. **Search hit is not Evidence; complete segmented record is the minimum Evidence candidate.**
6. **EvidenceIndex must not dump high-cardinality locators to Agent.**
7. **SHA is computed once per immutable SourceVersion/segment and reused.**
8. **A user question never refreshes its SourceVersion mid-investigation.**
9. **Live history is reused incrementally; old large segments are not recopied/rehashed for every question.**
10. **Final citations always resolve to exact immutable bytes + source/version identity + exact locator.**

## 结果

新的 Agent 路径目标是：

```text
SourceVersion once
    -> Evidence Shell
    -> Search / Segment / Complete Records
    -> User-controlled Evidence Budget Gate
        -> TOO_BROAD -> Agent refines search
        -> acceptable -> provenance / novelty / coverage
    -> Materialize exact Evidence
    -> Citation
```

TraceCite 的 token 优势不依赖 Agent 总能写出完美 `grep | head`，而由 Runtime 强制保证：大结果和重复结果不进入模型，最终只把用户允许预算内的新 Evidence 交给 Agent。