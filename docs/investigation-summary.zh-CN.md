# Investigation 完整性摘要（v1）

`tracecite.runtime.investigation_summary.summarize_investigation()` 提供
经过验证的 `InvestigationState` 的只读、有界视图。输入可以是 state 对象、
JSON mapping、`InvestigationStore` 或状态文件路径。加载不会写入 store，也不
会修改 revision。损坏、缺失或过大的输入默认返回小型
`status: "error"` 结构；需要失败即停时可传入 `strict=True`。

该结果只是建议性元数据，不是强制漏斗，也不是认识论结论。它不会复制
hypothesis claim、finding summary、参数、Evidence 正文或工具原始数据。明细
只包含有界 ID、状态和通用缺口类别。进度计数覆盖 observation、hypothesis、
（包括没有 Test 的 hypothesis）、test、execution 和 finding；execution 分别统计 error、unknown、缺失证据、
记录省略和记录截断。存在停止状态时，`stop` 给出有界的停止原因。

`suggested_actions` 使用稳定且与领域无关的类别：`formulate_test`、
`execute_test`、`gather_missing_evidence`、`seek_contradiction`、
`record_finding` 和 `stop/reopen`。这些只是 Agent 可考虑的选项，不要求执行
任何类别，模块也不会凭空创造 hypothesis 或领域查询。
`advisory_completeness.complete` 只表示本次有界协调视图没有列出缺口，不代表
调查正确、穷尽或可以安全结束。

摘要 schema 版本为 `1`。默认每个明细列表最多 32 项，序列化结果最多 24,000
字符；`omitted` 计数和 `truncated` 标志说明有界截断。调用方可以请求更小的
正整数限制，但不会突破硬上限。负数、非数字或低于最小值的限制返回使用
模块默认安全输出上限的有界 `invalid_limit:*` 错误结构，不会静默放大为无界
请求。
