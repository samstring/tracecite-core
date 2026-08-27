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

## 4. Delta 与“只在真正省时才发送”的语义

每次 search 的 delta projection 会记录：

- context schema / id / revision；
- 本轮新返回 Evidence 数量；
- 因已经看过而省略的可引用 Evidence 数量；
- 无法安全识别、因此未去重的 Evidence 数量；
- seen-state 大小与是否发生淘汰。

因此，一个重复 search 可以保持 `outcome=supported`，但本轮 Agent-facing Evidence delta 为空。这不表示 canonical Result 没有证据，而表示这些 Evidence 已经发送给当前 Agent context。Ledger 的 `result_id` 仍是恢复入口。

Context state 在合法 projection 后始终推进，但 **只有当 delta 在最终传输格式里严格更小时，才把 delta 发给 Agent**。对于 columnar JSON，按 compact JSON 的实际长度比较；对于 TCF `frame`，按 frame 渲染后的实际长度比较。若为了说明“省略了一条很短 Evidence”而新增的 Context metadata 反而更贵，则本轮继续返回普通 Agent View，但私有 seen-state 仍然推进。

因此启用 Context 不应仅因为附加 metadata 就让兼容的 Agent 视图变大。

## 5. CLI 与传输选择

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

如果 Host 明确支持文本帧，可以使用更紧凑的 TCF transport：

```bash
tracecite search app.log "timeout" --snapshot \
  --agent-profile frame \
  --ledger-dir /tmp/tracecite-ledger \
  --context-id incident-42
```

基于能力的 `auto` 选择规则是：只有 Host 明确声明 `stateful_history + batch_expand + text_frame` 时才优先 `frame`；支持有状态历史但不支持 TCF 时使用 `stateful-index`；再否则回退普通 Agent JSON。没有声明 `text_frame` 的 Host 不会突然收到 TCF。

从 canonical Result 恢复多条不可变 Evidence：

```bash
tracecite expand-many /tmp/tracecite-ledger RESULT_ID '#L120' '#L188-L190'
```

`--context-id` 没有 `--ledger-dir` 时返回机器可读错误。已有 Evidence / 行长度 / 输出预算同时作用于普通视图与 delta 视图，再根据最终传输大小选择更小的一份。

## 6. MCP 与其他 Host

有状态 Host 可以把 conversation、investigation、task 或其他稳定的 host-owned ID 映射为 Context Engine 的 `context_id`。该 ID 只表示传输记忆，不能当作用户身份、Evidence 或授权凭据。

TraceCite MCP 在 `tracecite_search` 上提供可选 `context_id`，状态保存于服务端控制的 `TRACECITE_MCP_STATE_DIR` 下，并通过 `tracecite_expand_many` 恢复完整 Evidence。模型不能选择服务端状态根目录。

MCP 或其他结构化 Host 不能因为 frame 更短就假装自己支持 `text_frame`；只有真正能解析/转发 TCF 的 Host 才应该声明该能力。否则继续使用 JSON fallback。

## 7. 公开真实日志验证

`benchmarks/agent-investigation/` 当前使用两份锁定 SHA-256 的真实公开输入：14.5 MB Kubernetes kubelet log，以及一份真实 Flutter/iOS crash report。固定查询 smoke 已验证：frame 能明显降低 TraceCite 的编码开销，frame + Context 还能在部分重叠查询中保留新 Evidence、同时去掉已见 Evidence。

这些结果测的是模型可见传输字符，不是完整 Agent 推理，也不是 provider 实际 token 总成本。因此不能把它描述成“TraceCite 已经证明整体 token 比 `rg` 更低”。模型级 benchmark 的 Host Protocol 与 scorer 是另一层验证。

## 8. 当前不做什么

当前 Context Engine 不会：

- 修改 canonical Result schema 或 EvidencePointer 语义；
- 推断 relevance 或 root cause；
- 把历史 Agent 结论当作 Evidence；
- 把 InvestigationState 与传输状态合并；
- 自动晋升 Knowledge；
- 使用 embedding / 模糊相似度做去重；
- 自动挑选代表性 Evidence Group。

代表性分组和更复杂的 Context Budget 可以继续在 Runtime/Integration 层演进，不需要修改 Extension Protocol v2。

## 9. 可信不变量

> 省 Token 不能让缺失、截断、近似或不可恢复的 Evidence 看起来像完整结果。

因此 Context Delta 始终保证 canonical Result 可恢复，并明确暴露“本轮因为已经看过而省略”的事实。Domain Extension 不需要感知 Agent 的传输状态。
