# Migration 0003：有界 Derived-Value Descriptor

## 适用范围

本迁移适用于在 `feature_for_agent_refacotr_shell` 重构分支上消费 Runtime
Evidence Compute aggregate 结果的 Agent/Host integration。

## 变化

`group` 和 `distinct` 计算仍然精确，但超过 derived-value transport 阈值（当前
为 512 字符）的字符串 key 不再完整传输，而是使用 descriptor：

```json
{
  "preview": "有界前缀",
  "truncated": true,
  "length": 15844,
  "value_sha256": "...",
  "evidence_ref": "evidence://sha256/<source-sha>#L35754"
}
```

Descriptor 位于原有 `aggregate.values[*]` 或 `aggregate.groups[*].key` 位置。
短值继续保持历史 scalar 形状。`count`、total、排序、Coverage 以及
source/version identity 不变。若 consumer 需要完整值，必须把 Evidence URI 当作
恢复 handle，materialize 它指向的 source line；不能把 preview 或 digest 当作完整值。

## 兼容性

读取 Compute 结果时，consumer 必须接受 distinct value 和 group key 的
`string | descriptor` 形状。这是 ephemeral Agent result 的 additive transport
boundary 变化，不改变持久化 schema 版本或 canonical source bytes。无法处理
descriptor 的 integration 应显式拒绝结果或固定到旧分支，不得静默把 preview 当作精确值。

该变化防止单个超大的日志/message 字段在模型边界重新制造无界中间结果，同时通过
SourceVersion Evidence 保持精确恢复能力。
