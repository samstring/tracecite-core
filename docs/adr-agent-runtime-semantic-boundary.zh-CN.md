# ADR：Agent 语义判断与 Runtime 机械验证边界

状态：Accepted  
日期：2026-08-29

## 决策

TraceCite 不作为第二个诊断 Agent，也不独立判断自然语言因果结论是否为真。

职责边界如下：

- Agent / Host 负责理解问题、提出 Hypothesis、设计 Test、解释 Evidence、形成语义 Finding，并决定最终自然语言回答。
- TraceCite Runtime 负责确定性检索、Evidence provenance、Coverage、Integrity、Identity / Correlation safety、预算与调查状态关联。
- Agent 对 Test 或 Finding 标记 `supported` / `contradicted`，表示 Agent 的语义判断；除非该判断来自可确定性执行的 assertion / capability，否则不得表述为 Runtime 已验证语义真值。
- Runtime 的 Finding validation 只证明该 Finding 满足机械 grounding 契约，例如 Test 已执行、Evidence 可引用且来源正确、Coverage / Integrity 没有已知阻断问题。
- `valid=true` 与 `semantic_verified=true` 是不同概念。Agent 自评产生的结果必须保持 `semantic_verified=false`。
- Runtime 不改写 Agent / Host 的最终自然语言答案，也不通过 transport 层替模型提升或降低结论语义。Host 可以根据产品策略展示 InvestigationState，但该策略不属于 TraceCite Core 的根因判断能力。
- Retrieval exhaustion、没有下一条确定性 retrieval action、零命中或 Evidence 不再增长，都不能自动升级为某个 Hypothesis 被证明。

## 原因

如果 Runtime 需要理解任意自然语言 Hypothesis、自动发明其因果证明条件，并判断日志语义是否证明这些条件，TraceCite 就会变成另一个 LLM/诊断 Agent。这会与现有 Agent 重复职责，也会让 benchmark 无法区分“模型变聪明”与“Evidence Runtime 有价值”。

TraceCite 的独立价值应来自可复现的机械能力：大数据有界检索、证据寻址与来源、Coverage、完整性、身份关联安全、调查审计和 Token / Context 控制。

## Benchmark 约束

真实 Agent benchmark 应优先使用外部 Agent Harness，例如 Pi Agent。基线与 TraceCite 组必须尽量保持同一个 Agent、同一个模型、同一个输入和预算，仅改变 TraceCite 是否可用。

仓库内自定义 GMI Host 只保留为 legacy / deterministic benchmark harness，不作为产品 Agent 架构，也不作为主要真实 Agent 结论。
