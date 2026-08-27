# Investigation 时间线与结构比较

`tracecite.runtime.investigation_compare` 提供两个只读原语：

```python
from tracecite.runtime.investigation_compare import (
    compare_investigations,
    timeline_investigation,
)

timeline = timeline_investigation("investigation.json")
delta = compare_investigations("before.json", "after.json")
```

两个函数都接受已验证的 `InvestigationState`、`InvestigationStore`、状态
mapping 或 JSON 路径。路径和 mapping 会先通过有界源大小检查，再进行规范的
状态校验。实现不会写入状态、读取 Knowledge 库、执行工具，也不会打开
Evidence 指针所指向的源文件。

## 时间线

`timeline_investigation` 返回带版本的 `kind: "timeline"` envelope，包含
调查 ID、快照 revision，以及以下稳定控制事件：

- 调查创建；
- Hypothesis、Test、Execution、Finding 记录；
- Knowledge Candidate 链接；
- 存在时的 stop 转换。

事件按有界时间戳文本（缺失时间戳排在最后）、事件类型和 ID 排序；相同时间的事件
也有确定顺序。envelope 携带当前快照 revision；事件只包含 ID、status/outcome、
控制时间戳和关系 ID，
不会复制 claim、summary、operation 文本、stop detail、参数、Evidence URI/正文、
artifact 路径或领域 payload。

`max_events` 限制事件列表。`counts.total`、`counts.reported`、
`counts.omitted`、`omitted.events` 与 `truncated` 明确表示省略。达到
`max_output_chars` 时只按确定顺序裁剪列表，并保留紧凑控制 envelope，不会把 JSON
从中间截断。输入无效、损坏、缺失或超大时，默认返回
`status: "error", valid: false, error: {"code": ...}`；`strict=True` 会以稳定
错误码抛出 `InvestigationCompareError`。

## 结构比较

`compare_investigations(left, right)` 比较两个快照，也支持把同一状态文件的两个
revision 分别作为 mapping 或路径传入。结果包含：

- 左右来源元数据、revision、status 与 revision delta；
- observations、hypotheses、tests、executions、findings 和候选链接的数量，
  以及有界的 ID `added`/`removed`/`changed`；
- Hypothesis、Execution、Finding 的结构化 outcome 转换；
- budget 用量与策略变化标记；
- 通用 coverage 声明、omission、truncation、缺失 Evidence 与 Finding
  limitations 的 delta；
- stop 是否存在及 stop kind 的变化；
- 候选链接新增、删除以及 status/link 字段变化。

Changed 项只报告结构字段名称和 ID，不暴露 claim、summary、查询参数、Evidence
引用、artifact、stop detail 或候选 payload。这是结构 diff，不是异常检测、因果
分析或知识判断。

`max_items` 限制每个 ID/change/transition 列表。裁剪时保留每个列表以及顶层
`omitted` 计数；所有结果同时受 `max_output_chars` 限制，并且对相同已验证输入
保持确定性。

## 公共接入

两个函数都由 `tracecite` 和 `tracecite.runtime` 导出。CLI 提供相同的只读操作：

```bash
tracecite investigation timeline investigation.json
tracecite investigation compare before.json after.json
```

它们不是 tool dispatcher 操作，也不会创建 Execution。宿主必须保持相同的
source/limit/error envelope，不得把结构变化自动升级为 Finding、stop 转换或
Knowledge proposal。
