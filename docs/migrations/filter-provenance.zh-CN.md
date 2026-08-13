# Filter provenance 迁移说明

本次变更保持原有最终 `pattern`、过滤产物和运行 schema 版本不变，新增字段均为兼容性扩展：

- `FilterResult.pattern_components`、`matched_by_counts`；
- 每条 record/hit 的 `metadata.matched_by`；
- Scenario/Run 的 canonical `filter` provenance（`match_mode`、`components`、`preset` 以及可选 `scenario` 元数据）。

`matched_by` 具有确定性，并允许一条记录命中多个组件。Core 直接调用而未声明组件时使用保留的 `pattern` fallback，并设置 `matched_by_fallback=true`。Scenario resolver 替换表达式时，解析后的 `scenario:<name>` 是生效组件，preset/grep 只保留为 provenance 输入。

Preset 的版本/来源/哈希为可选元数据；缺少版本时序列化为 `unknown`。过长的 ID 和元数据会被有界截断并带有 `*_truncated` 标志。旧读取方可以忽略新增字段；新读取方应优先使用 canonical Run `filter` 对象，历史顶层最终 `pattern` 仅用于兼容展示。
