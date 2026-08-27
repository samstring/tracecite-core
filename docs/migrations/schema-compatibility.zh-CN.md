# 持久化 schema 兼容性治理

TraceCite 使用标准库实现的注册表
`src/tracecite/runtime/schema_compat.py` 记录兼容性承诺。注册表与公开
schema 实现分离，逐项声明当前版本、用于校验 fixture 的 reader、支持的
旧版本以及证明声明的 fixture。

在 checkout 根目录运行：

```sh
python scripts/check_schema_compat.py
```

命令输出排序稳定、可供机器读取的 JSON；源码常量、fixture、reader 或迁移
声明发生漂移时返回非零状态。该命令可直接用于 CI，不需要网络或第三方依赖。

## 覆盖范围

注册表目前覆盖：

- 版本化的 `AgentResult` 传输 envelope（临时数据，不是磁盘存储）；
- 版本化的 `InvestigationSummary` advisory envelope（临时数据，不是调查
  状态文件）；
- 版本化的场景输入文档；
- 版本化的运行 manifest；
- records/hits JSONL 过滤产物，分类为无版本的 additive 产物；
- `InvestigationState`、嵌套的 `BudgetPolicy` 以及 cache sidecar；
- `KnowledgeGovernanceStore`，包括明确的 v1 到 v2 迁移。

过滤 JSONL 刻意不虚构 schema 版本或迁移。新的 provenance 字段是 additive，旧
reader 仍可读取；不兼容变更必须先增加显式版本以及迁移 fixture。像
`InvestigationSummary` 这样的内存报告是派生的临时值。由于它是公开的版本化
输出，注册表仅为它记录版本；它不是磁盘状态文件，也不因此获得迁移承诺。

## 兼容性规则

每个版本化条目都指向源码版本常量，并提供当前版本的 golden fixture。只有同时
声明旧版本 fixture、reader 和迁移 handler 时，才承诺支持旧版本。检查器调用现有
公开 reader；对于旧版本，会迁移临时副本并确认结果落在当前版本。检查器不依赖
Git 历史、不从文档文字推断版本，也不会静默改写用户数据。

不兼容的持久化 schema 变更需要更新注册表、为旧版本及迁移添加确定性 fixture，
并在本目录增加简短说明。无版本 additive 元数据变更应记录旧 reader 仍然有效的
理由；不要声称不存在的迁移。
