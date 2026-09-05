# TraceCite vNext：Evidence Compute Runtime 总体架构与实施计划

> 状态：设计提案；在 7 分钟 blind A/B 验收前不视为已落地架构。
>
> 核心边界：**Agent 负责推理、假设、因果判断、充分性与停止；TraceCite 负责对授权 Evidence 做确定性计算、SourceVersion、provenance、coverage 与传输控制。**

## 1. 为什么重新设计

当前 TraceCite 已经能提供 Native 默认没有的能力：

- RetrievalSession 内固定 SessionSourceView / SourceVersion；
- Segmenter 恢复完整逻辑 Record；
- Evidence identity、provenance、materialize、replay；
- Host/User 拥有 Evidence budget，Agent 不能自行放大；
- 大集合不通过高基数 EvidenceIndex 进入模型；
- Runtime 内可以做搜索、过滤、聚合和部分 fast path。

但真实 Native-vs-TraceCite RCA 轨迹暴露了主要差距：Native 能在一个 Shell/Python 调用里完成 scan/filter/group/join/bucket/compare，TraceCite 仍让 Agent 参与过多机械编排。后果是：

1. model/tool round trip 更多；
2. 历史上下文被模型反复读取，cached input 上升；
3. 每一个额外模型边界都可能触发 provider 429/retry；
4. Agent 更容易沿同一个假设不断补证，而不是把多项机械检查一次完成后再统一推理；
5. wall time 受到模型往返而不只是 Runtime 扫描性能影响。

因此 vNext 的目标不是“继续增加 Evidence Shell 命令”，而是从 **Evidence Search Runtime** 演进为 **Evidence Compute Runtime**。

## 2. 反方问题：如果没有 TraceCite，大模型自己干会不会更好？

会，在很多任务上 Native 是一个非常强的竞争方案。

Native 的优势：

- Agent 可以现场写任意 Python/Shell；
- 中间数据天然留在脚本进程，不必进入模型；
- 新的机械算法不需要产品预先增加 operator；
- 一次 tool call 可以完成大量机械工作；
- 无需 pointer -> materialize 的额外协议层。

所以 TraceCite 只有满足以下组合才值得存在：

1. evidence 规模可以很大，但模型 working set 有硬边界；
2. SourceVersion / provenance / replay / Host policy 比 Native 更可靠；
3. 大量机械计算留在 Runtime，不把中间行交给模型；
4. 相同分析任务的模型边界数量接近或少于 Native；
5. context/token 明显更低；
6. wall time 不比 Native 差；
7. 最终答案人工审核不比 Native 差。

如果做不到这些，增加 IR、optimizer、session cache 等复杂度就不值得。

## 3. TraceCite 自身会带来的弊端

### 3.1 系统复杂度

IR、执行器、缓存、lineage、transport gate、MCP projection 都可能成为新的 bug 面。

### 3.2 表达能力天花板

受控 Runtime 永远不等于 unrestricted Python。设计只能追求“对授权 Evidence 的纯计算接近编程灵活性”，不能宣称完全替代 Native。

### 3.3 优化器语义风险

任何 fast path 都可能与 canonical semantics 不一致。最近 `sort -r/-nr`、Unix compat 回归已经证明这一风险真实存在。

### 3.4 provenance 成本

如果 derived result 为了证明 lineage 保存几十万 member Evidence ID，会重新造出 EvidenceIndex 问题。

### 3.5 工具/schema 自身也占上下文

一个巨大 `tracecite_analyze` JSON schema 也会浪费模型 token。因此公共工具必须少、schema 必须小。

### 3.6 过度压缩可能损伤推理

如果只给统计值而不给可恢复的原始 Evidence，Agent 可能缺失关键质性细节。因此压缩必须可回溯，不是删除证据真相。

### 3.7 代表 Evidence 的选择偏差

Runtime 如果自己挑“最相关”证据，就开始侵入 reasoning。代表样本只能使用明确机械规则，例如 caller 指定 top-K、first/last、稳定 hash sample 等。

## 4. 总体架构

```text
                                  Agent
                                    |
                 +------------------+------------------+
                 |                  |                  |
            Analysis API       Program API       Shell Compat
                 |                  |                  |
                 +------------------+------------------+
                                    |
                                    v
                          Evidence Plan IR
                                    |
                                    v
                       Query / Compute Optimizer
                                    |
          +-------------------------+--------------------------+
          |                         |                          |
   Streaming Engine          Sandboxed Pure UDF       Correlation Engine
          |                         |                          |
          +-------------------------+--------------------------+
                                    |
                                    v
                         Typed Record / RecordSet
                                    |
                                    v
                                Segmenter
                                    |
                                    v
                     SessionSourceView / SourceVersion
                                    |
                                    v
                    logs / traces / metrics / code / ...
```

横向能力：

```text
InvestigationSession
├─ SourceVersion bindings
├─ Evidence ledger
├─ Materialization ledger
├─ Result/computation identities
├─ Coverage facts
├─ Computation cache
└─ Model-visible ledger

Transport Gate
├─ Host-owned byte/token/row limits
├─ bounded result types
├─ no unbounded RecordSet crossing
└─ exact Evidence only by bounded materialization
```

## 5. 以前的 Evidence、Segmenter 还在吗？

全部保留，而且更明确地成为底座。

### Segmenter

```text
raw bytes / lines
    -> candidate
    -> Segmenter
    -> complete logical Record
```

Compute Engine 不能为了性能绕过完整 Record 语义。多个分析能安全共享扫描时才 fusion；如果执行模式不兼容，可以在同一个 Agent tool call 内部拆成多 pass。

### Record

Record/Typed Record 成为 Compute Engine 的主要输入：

- stable identity；
- SourceVersion；
- source/range provenance；
- timestamp；
- mechanically extracted fields；
- raw body 或可恢复 handle。

### Evidence

Evidence 不再要求每个计算都返回完整 pointer 列表，而是成为 derived result 背后的 provenance anchor。

### SourceVersion / SessionSourceView

保持不可退让：同一个 InvestigationSession 的依赖计算必须处于同一个 evidence world。

### Materialize / Replay

继续保留，但从调查主循环降为“需要读原始 Evidence/最终引用时”的精确 primitive。

## 6. Evidence Plan IR 是什么

不同前端统一编译到同一种内部计划：

```text
Shell-like syntax ---+
Analysis API      ----+--> Evidence Plan IR --> optimizer --> executor
Program API       ---+
```

例如：

```text
Scan(traces)
 -> Filter(serviceName == "route")
 -> Filter(statusCode >= 500)
 -> GroupBy(operationName)
 -> Count
 -> TopK(10)
```

IR 的作用是把“Agent 怎么表达”和“Runtime 怎么高效执行”解耦。

IR 只能描述确定性机械计算，不能包含：

- likely root cause；
- hypothesis confidence；
- next hypothesis；
- sufficient evidence；
- stop recommendation。

## 7. 三种 Agent 入口

### 7.1 Analysis API（优先）

Agent 已经知道要做哪些机械检查时，一次提交多个分析，而不是一项一项唤醒模型。

第一版只做结构化机械 batch，不接受“帮我找根因”这种自然语言 planner 请求。

### 7.2 Program API（目标架构，暂缓实现）

未来如果固定 IR operator 仍明显限制 Agent，可增加 capability-sandboxed 纯计算语言：变量、if、bounded loop、pure function、map/filter/reduce、时间运算、自定义纯 UDF。

禁止 filesystem/network/process/shell/env/secrets/side effects。

### 7.3 Shell Compatibility

现有 Evidence Shell 保留为兼容前端，不再是长期能力边界。

## 8. 如何保证灵活性而不是无限增加 DSL 指令

长期采用两层：

```text
可识别声明式 dataflow
  -> optimizer 可做 pushdown/shared scan/top-K/streaming aggregate

纯 UDF escape hatch
  -> Agent 自己组合特殊计算逻辑
```

第一阶段不实现 UDF VM。只有真实 paired trajectory 证明“剩余轮次主要因为无法表达自定义纯计算”时才进入这一阶段。

## 9. 什么可以进入大模型，什么必须留在 Runtime

硬边界：

```text
                         Runtime World
----------------------------------------------------------------
Raw Source
Segmented Records
RecordSets
Full match sets
Intermediate tables
Join results
Indexes/cache
Execution plans
Full internal lineage

======================= TRANSPORT GATE =========================

                          Model World
ScalarResult
Small AggregateResult
Small ContrastResult
TopKResult
Stable handles
Explicit bounded MaterializedEvidence
Small mechanical delta/checkpoint
```

### 默认允许发送给模型

- scalar / count；
- 小型 aggregate；
- 小型 caller-selected contrast；
- top-K；
- coverage/completeness/truncation；
- SourceVersion/result identity；
- 少量 caller/mechanically-selected Evidence handles；
- 显式 materialize 的原始文本。

### 默认禁止发送

- 完整中间 RecordSet；
- 高基数 locator 数组；
- 每行重复 source/SHA/URI；
- 完整 lineage member list；
- 整个 session history；
- 已经发送过的完全相同 body；
- Runtime debug diagnostics，除非显式调试。

## 10. Evidence 数量不等于 Evidence transport

如果完整匹配 12,431 条：

```text
match_count = 12431
coverage = complete
result identity = ...
representatives = bounded/optional
```

不需要向模型发送 12,431 pointer。

普通 Evidence search 的现有规则仍保持：如果完整最终 matched Evidence 本身要返回给 Agent 且超预算，必须 `too_broad` + zero partial Evidence；不能偷偷 first-N。

## 11. Derived result lineage 怎么避免变成新的 EvidenceIndex

Derived aggregate 通常保存/传输 compact proof recipe，而不是完整 member IDs：

```text
SourceVersion identity
+ normalized Plan identity
+ Runtime semantic version
+ coverage/completeness
+ result identity/hash
```

因为 SourceVersion 不变，需要验证时可以确定性复算。

只有真正发送给模型的代表/物化 Evidence 才需要单条 pointer。

## 12. ResultHandle 生命周期

未来 ResultHandle 只能是优化，不是新的永久 canonical store：

- session scoped；
- immutable；
- SourceVersion + normalized plan keyed；
- typed；
- coverage-aware；
- Host cache budget 限制；
- 可淘汰；
- 淘汰后可在 immutable source 上确定性复算。

第一编码切片不依赖 ResultHandle 才能成立。

## 13. 三类 Budget

### Compute Budget

限制内部 work：scan bytes、CPU/instructions、memory、wall time、join complexity。

### Transport Budget

限制 Runtime -> Model：bytes、estimated tokens、rows/groups、handles。

### Materialization Budget

限制显式原始 Evidence body。

三者都由 Host/User 控制，Agent 不能升级。

## 14. 如何真正减少模型次数

关键不是把每个 JSON 从 3KB 压成 2KB，而是消掉完整模型边界：

1. 一个 `analyze` 能提交多个已经选择的机械 aggregate；
2. compatible computations 共享一次 scan/JSON decode；
3. 后续可引入 caller-defined window/cohort comparison，让一轮完成 before/after 等机械计算；
4. Runtime 内部 handle/cache 避免大集合往返；
5. 已发送 exact body/result 不重复传输；
6. Host 如果支持 checkpoint/history replacement，可进一步压缩旧历史，但这不是 Core 可单独保证的能力。

第一阶段的可移植目标是：**减少 model/tool boundaries**。

## 15. 为什么不让 Runtime 自动做 RCA 策略

`before/after`、window、contrast、join 是通用机械能力，可以有；“什么时候必须比较 before/after”“健康期存在所以不是根因”属于推理策略，不能写进 Runtime/Skill。

同样禁止：

- 自动选择某个 service；
- 自动选择 memory/OTel/JVM 等候选；
- 自动 root-cause ranking；
- 自动判断 sufficient/stop。

Agent 决定分析方向，TraceCite 只便宜、可靠地执行它。

## 16. 当前 Skill 的边界修正

此前 Skill 曾包含 causal/stopping/temporal-contrast 策略。这类规则已被设计审查判定越界，vNext benchmark 必须使用清理后的 Skill：只说明 session、budget、too_broad、analyze/run/materialize/replay 等工具机械语义。

这也是防止“因为看过 benchmark 答案而靠提示适配”的必要措施。

## 17. 自我审查

### 审查 A：是否通用？

最小 IR、batch compute、shared scan、Transport Gate、SourceVersion、Evidence lineage 都可用于日志调查、代码分析、CI failure、security logs、observability 等，不依赖当前 RCA case。

结论：通过，但 caller 必须自己选择分析。

### 审查 B：是否在重造 Spark/Pandas？

有风险。因此不一次实现 SQL、WASM、graph、UDF、所有 join。先实现真实轨迹证明有价值的最窄 compute fusion。

结论：只允许增量实现。

### 审查 C：Native 会不会还是更简单？

完全可能。因此 architecture 不是因为“更漂亮”就成功。必须用 paired run 证明 token/context、time、answer quality。

结论：benchmark 是设计 gate。

### 审查 D：压缩会不会让答案变差？

会，如果不可恢复。所有 derived result 必须保持 recoverable lineage；原始 Evidence 可以显式 materialize。

结论：Transport Gate 限制传输，不删除 truth。

### 审查 E：representative 是否会引导模型？

会。因此只能 mechanically/caller-selected，不做“causal relevance”排名。很多 aggregate 默认甚至可以不返回 raw representative。

### 审查 F：checkpoint 能不能由 Core 保证？

不能删除 Host 已经放进模型历史的内容。Core 能做的是新结果 bounded + exact duplicate suppression；历史 replacement 依赖 Host。

结论：优先减少 model boundary，不把 checkpoint 当虚假承诺。

### 审查 G：lineage 会不会爆炸？

不能存所有成员 ID。使用 SourceVersion + normalized plan + coverage + result hash 的 compact recipe，需要时复算。

### 审查 H：429 是谁的问题？

429 是 provider 返回，但 TraceCite 如果制造更多 model rounds/更高 context throughput，会间接提高发生概率。需要把 provider overload 与产品导致的请求压力分别统计。

## 18. 第一可编码切片

设计审查后的结论不是全面重写，而是：

### Core

1. 最小 Plan/IR，只覆盖当前已验证的 deterministic aggregate path；
2. 一次 batch 提交有限数量 named analyses；
3. 同一 source/session 绑定同一 SessionSourceView；
4. JSONL compatible analyses 共享 scan 和 JSON decode；
5. 每项独立 status/coverage；
6. bounded output；
7. 不安全/不兼容时在同一 Agent 调用内部 canonical fallback；
8. 用 equivalence tests 对比独立 canonical calls。

### MCP

1. 一个紧凑 `tracecite_analyze`；
2. schema 不暴露 Host budget 控制；
3. projection 不重复 metadata，不传中间 RecordSet；
4. Skill 只教 API mechanics，不教调查策略。

### 暂缓

- general UDF/VM/WASM；
- natural-language planner；
- causal strategy；
- arbitrary join；
- automatic history rewriting；
- 大规模 public API 重构。

## 19. 编码 Go / No-Go

满足以下条件才允许改 product：

1. 通用 evidence-compute 机制；
2. 不含 benchmark case ID/service/fault/OTel/JVM/memory 等特定知识；
3. 不破坏 Segmenter/SourceVersion/Evidence/provenance/budget；
4. 能减少完整 model boundary，而不只是少几十字节；
5. 能对 canonical semantics 做机械回归；
6. 有真实轨迹对应的效率问题。

当前结论：

- **GO：最小 batch/shared-scan + compact MCP analyze。**
- **NO-GO：全面 vNext rewrite、UDF VM、autonomous planner。**

## 20. 编码后的 7 分钟 benchmark 循环

复用当前 RCAEval case 只作为 blind regression/performance probe，绝不能把 case truth 写进产品。

### Blind protocol

1. Native 和 TraceCite 使用同一匿名 telemetry；
2. 两边都看不到 case/fault annotation；
3. 两边完成 final answer 后才读取真实 source annotation；
4. 最终正确性人工审核，不用 gold/regex scorer 决定；
5. 分别看 root component、concrete mechanism、causal chain、证据支持、unsupported inference。

### 时间上限

Agent investigation timeout 固定 **420 秒（7 分钟）/ arm**。

### 429 处理

出现显著 429/overload 时：

1. 分类 rate-limit / overload / quota / context-too-large；
2. 看 TraceCite 是否因为额外模型轮次/context throughput 放大限流；
3. 如果 provider instability 足以主导 7 分钟结果，重跑；
4. 纯 provider outage 不修改 Runtime；
5. 如果 TraceCite 自己多轮导致请求压力，则把“多余轮次”视为产品效率缺陷。

### 验收门槛

有效 paired run 必须同时满足：

1. **答案质量：TraceCite 人工审核不低于 Native；**
2. **时间：TraceCite 不慢于 Native，且两边 <= 420 秒；**
3. **token/context：TraceCite 明显低于 Native；**
4. model/tool rounds 应显著下降；
5. Evidence/SourceVersion/provenance/budget regressions 全绿。

记录 fresh input、cached input、output、model calls、tool calls、model-visible tool-result bytes（可测时）。`fresh + cached` 只能标成工程 context-read volume，不冒充通用 billing cost。

## 21. 失败后怎么循环

每次失败：

1. 先人工读两边 final answer；
2. 再读真实 annotation/source；
3. 分类错误：Runtime correctness、transport/context、unnecessary orchestration、performance、generic capability gap、Agent reasoning、provider invalid；
4. 只有 concrete generic defect 才改产品；
5. 先加通用 regression；
6. 再跑同样 blind pair；
7. 重复，直到门槛满足，或者证据表明架构本身不值得继续扩张。

Agent reasoning error 本身不能成为“往 Runtime/Skill 塞推理规则”的理由。

## 22. Anti-overfitting firewall

禁止产品代码/Skill/tests 出现为当前 case 服务的：

- case ID；
- service name；
- hidden fault type；
- OTel/JVM/memory 特定诊断规则；
- 特定错误 -> 特定下一步分析；
- root-cause stop/ranking；
- gold/scorer hack；
- 针对当前答案写的 prompt coaching。

每个 benchmark 驱动的改动都必须回答：

> **如果我从来不知道当前 case 的隐藏答案，我仍然会希望所有 TraceCite 用户拥有这个行为吗？**

答案为否，就拒绝该改动。

## 23. 最终目标

把交互从：

```text
query -> model -> query -> model -> materialize -> model -> aggregate -> model ...
```

变成：

```text
caller-selected mechanical analysis
        -> Runtime large compute / shared scan
        -> compact bounded result
        -> model reasoning
        -> next meaningful analysis
```

最终设计承诺不是“TraceCite 比 Python 更自由”，而是：

> **对授权 Evidence 的机械计算尽量接近 Native 的组合能力和效率，同时提供 Native 默认没有的 SourceVersion、Evidence identity、provenance、replay、Host policy 和模型传输边界。**

若这一承诺无法在真实 paired run 中成立，则不继续扩大 vNext 复杂度。
