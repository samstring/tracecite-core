# Evidence Intelligence 实验

状态：实验性；仅用于 `experiment/evidence-intelligence` 分支验证，不属于 Extension Protocol v2 稳定承诺。

## 目标

在不让 TraceCite 变成自治 Agent、代码搜索器或 Observability 存储平台的前提下，把已经生成的 runtime evidence 转换成：

1. 可通过稳定实体标识自动关联的证据图；
2. 对重复 evidence 做确定性 grouping 的代表性集合；
3. 基于 seed、graph distance、severity、entity expansion 和 source diversity 的确定性排序；
4. 在 Agent token budget 下生成可恢复、显式暴露 omission/coverage 的 EvidencePackage；
5. 不再绑定 `search` operation 的 canonical ledger 与跨轮 delta context。

## 边界

- `EntityRef` / `EvidenceRelation` 只描述事实身份与关系，不表达根因。
- Correlation 不生成 Finding；temporal relation 只是一条带 confidence/basis 的弱关系。
- Reducer 不使用 LLM，不修改 canonical evidence。
- EvidencePackage 是 Agent-facing projection；省 token 不能隐藏 Coverage 缺口。
- 原有 `EvidenceLedger` / `ContextEngine` 暂不删除。实验验证通过后再设计兼容迁移，而不是直接替换。

## 验收

组件 benchmark 只证明“压缩后仍保留规定 evidence marker”。最终合并回 `refactor/agent-v2` 前，还需要真实 Agent Host benchmark 证明：

- 总输入 token 下降；
- tool calls / 重复读取下降；
- evidence recall 不下降；
- answer correctness 不下降；
- citation 可恢复且准确。

只有这些结果成立，才应把实验 API 收敛为正式 Runtime/Integration contract。
