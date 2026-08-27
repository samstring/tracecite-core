# TraceCite Context Engine

状态：已实现的 Agent 传输能力  
适用范围：`tracecite.integrations`、CLI Adapter、MCP 与其他有状态 Agent Host

Context Engine 用来减少多轮调查中重复进入模型上下文的工具结果，同时保持 TraceCite 的 Evidence 与可信边界。它不是领域 Extension API，不替代 InvestigationState，也不保存 Agent 的推理结论作为证据。

## 1. 边界

```text
Canonical Runtime Result
        |
        +----> Evidence Ledger（完整、内容寻址）
        |
        v
Context Engine
按 Agent context 记录已见 Evidence identity
        |
        v
Agent-facing Context Delta
```

Runtime 先产生完整 canonical Result。配置 Ledger 时，完整 search Result 必须先写入 Ledger，随后才允许 Context Delta 缩减本轮传给 Agent 的内容。因此 Context Engine 只改变传输视图，不改变 canonical Result。

## 2. Evidence identity

当前版本只使用不可变 Evidence URI 对可引用 search Evidence 去重。若某条 Evidence 没有 URI，Context Engine 不猜测其身份，而是继续返回，避免静默丢失数据。

不会使用 label、文本相似度、行内容、DomainEvent 类型或模型判断做去重。

## 3. Context state

每个 context 拥有独立且有界的传输状态：

```json
{
  "schema_version": 1,
  "context_id": "incident-42",
  "revision": 3,
  "seen_evidence": ["evidence://sha256/...#L120"],
  "seen_results": ["<sha256-result-id>"]
}
```

默认最多保留 4096 个 Evidence identity 与 512 个 Result ID。超出上限时淘汰最旧的传输记忆，并通过 `state_pruned` / `context_state_pruned` 暴露。淘汰最多会让很早以前的 Evidence 再次返回，不会造成未见 Evidence 被隐藏。

Context state 原子写入；`context_id` 使用受限安全标识符，不能进行路径穿越。

## 4. Delta 语义

每次 search 的 Agent 视图会报告：

- context schema / id / revision；
- 本轮新返回 Evidence 数量；
- 因已经看过而省略的可引用 Evidence 数量；
- 无法安全识别、因此未去重的 Evidence 数量；
- seen-state 大小与是否发生淘汰。

因此，一个重复 search 可以保持 `outcome=supported`，但本轮 Agent-facing Evidence delta 为空。这不表示 canonical Result 没有证据，而表示这些 Evidence 已经发送给当前 Agent context。Ledger 的 `result_id` 仍是恢复入口。

## 5. CLI

不传 context ID 时，原有 CLI 行为保持不变：

```bash
tracecite search app.log "timeout" --snapshot
```

跨轮 delta 必须显式启用，并要求同时配置 Ledger：

```bash
tracecite search app.log "timeout" --snapshot \
  --agent-profile stateful-index \
  --ledger-dir /tmp/tracecite-ledger \
  --context-id incident-42
```

从 canonical Result 恢复多条不可变 Evidence：

```bash
tracecite expand-many /tmp/tracecite-ledger RESULT_ID '#L120' '#L188-L190'
```

`--context-id` 没有 `--ledger-dir` 时返回机器可读错误。Context Delta 在已有 compact projection 之前应用，因此原有字符/证据预算继续作用于更小的 delta。

## 6. MCP 与其他 Host

有状态 Host 可以把 conversation、investigation、task 或其他稳定的 host-owned ID 映射为 Context Engine 的 `context_id`。该 ID 只表示传输记忆，不能当作用户身份、Evidence 或授权凭据。

TraceCite MCP 在 `tracecite_search` 上提供可选 `context_id`，状态保存于服务端控制的 `TRACECITE_MCP_STATE_DIR` 下，并通过 `tracecite_expand_many` 恢复完整 Evidence。模型不能选择服务端状态根目录。

## 7. 当前不做什么

当前 Context Engine 不会：

- 修改 canonical Result schema 或 EvidencePointer 语义；
- 推断 relevance 或 root cause；
- 把历史 Agent 结论当作 Evidence；
- 把 InvestigationState 与传输状态合并；
- 自动晋升 Knowledge；
- 使用 embedding / 模糊相似度做去重；
- 自动挑选代表性 Evidence Group。

代表性分组和更复杂的 Context Budget 可以继续在 Runtime/Integration 层演进，不需要修改 Extension Protocol v2。

## 8. 可信不变量

> 省 Token 不能让缺失、截断、近似或不可恢复的 Evidence 看起来像完整结果。

因此 Context Delta 始终保证 canonical Result 可恢复，并明确暴露“本轮因为已经看过而省略”的事实。Domain Extension 不需要感知 Agent 的传输状态。
