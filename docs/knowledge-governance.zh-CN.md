# 知识治理

TraceCite 将 Agent 提案与可信领域知识物理分离。主发行包只提供通用生命周期，扩展负责把通过验证的候选转换为本领域知识。

```text
提案 + Evidence
      ↓
候选知识库
      ↓ 独立案例
verified / contradicted
      ↓ 不同审核人
领域适配器晋升
```

公共 API 位于 `tracecite.knowledge`：

- `KnowledgeGovernanceStore.propose()` 强制提供案例 ID 与 Evidence 引用。
- `verify()` 拒绝重复案例。默认至少两个独立支持案例；存在任何反例时禁止晋升。
- `promote()` 要求审核人与创建者不同，并且正式知识 SHA-256 校验通过后才调用领域适配器。
- `check_target()` 可以发现绕过 promotion 的正式知识修改。

候选文件与正式知识必须分开保存。JSON 使用原子写入；主项目不包含 Mobile、CI、产品或公司语义。

为兼容领域适配器，可以保留底层写函数，但 Agent 接入层只能暴露 propose、verify、promote，不能暴露直接写函数。
