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
- `promote()` 要求审核人与创建者不同，并且正式知识 SHA-256 校验通过后才调用领域适配器；同时记录有界的有效性元数据：来源/工具/Schema 版本、审核人和审核时间，以及可选的失效时间、重新验证时间和不透明 JSON 条件。
- `check_target()` 可以发现绕过 promotion 的正式知识修改。
- `evaluate_validity()` 和 `is_current()` 显式判断可信状态：已晋升知识可能是 `current`、`stale`、`expired` 或 `superseded`，只有 `current` 可使用。过期或到达重新验证时间的记录不会被静默信任；Core 不解释领域条件。
- `revalidate()` 是显式的独立审核，会刷新有效性元数据并保留有界审核历史；未重新声明的失效/重新验证时间会被本次审核清除。语义变化必须使用 `supersede()`（或带 `supersedes=` 的 `propose()`）创建新版本，保留旧 payload 与血缘，而不是原地改写。对于仅处于 candidate/verified 状态、尚未晋升的前版本，会立即标记为 superseded；对于已晋升前版本，只有替代版本成功晋升后才会标记 superseded，期间继续保持 current。
- 候选库每一个读-改-写操作都会在 JSON 文件旁使用跨进程锁。晋升和 supersession 的成功重试是幂等的，并发重试不会重复调用领域晋升适配器或创建第二个版本。

候选文件与正式知识必须分开保存。JSON 使用原子写入，跨调查丢更新窗口由文件锁关闭；主项目不包含 Mobile、CI、产品或公司语义。

当前 governance Schema 为 v2。读取 v1 候选库时会使用兼容默认值（来源/工具/Schema 版本为 `unknown`，旧晋升时间作为审核时间，版本为 1 且没有血缘）；调用 `KnowledgeGovernanceStore.migrate()` 可在同一把锁下持久化升级。元数据只允许有界 JSON；未知有效性字段、非法时间、超限值和畸形候选会校验失败，不会被信任。

Investigation Runtime 提供显式的
`InvestigationStore.propose_knowledge_candidate()` 桥接操作。它只接受带有
支持 Evidence 且关联 Test 的 `supported` Finding；`unknown` 和
`contradicted` Finding 不能作为可复用声明。桥接先通过
`KnowledgeGovernanceStore.propose()` 写入候选，再在 InvestigationState 中只
记录候选 ID、Finding ID、候选库链接和状态。提案失败不会留下状态链接；同一
Finding 重复提案会复用已有候选而不是创建重复项。候选 payload 保留调用方提供
的适用/排除条件、支持与反证引用、Coverage/限制、Test 策略/配方以及来源调查
schema/revision，供独立审核。

提案 Evidence 引用必须使用 Runtime 当前生成的不可变指针格式：
`evidence://sha256/<64 位十六进制摘要>#L<起始行>[-L<结束行>]`，并且行号从 1
开始且范围合法。在定义版本化 manifest URI 契约前，暂不接受 manifest 引用。
复用已有提案时会比较规范化 payload 以及 `kind`、`domain`、`scope`、创建者、
case 等稳定身份字段；包括适用/排除条件或候选库路径在内的参数漂移都会返回
冲突，不会静默复用旧提案。

InvestigationState 中保存的 status 是建立链接时的快照。独立审核、重新验证、
supersession 或晋升只会更新候选库，不会自动改写 InvestigationState；需要最新
状态时，宿主应显式读取候选并调用 `evaluate_validity()`。`usable: false` 是明确的
停止信号，不表示该声明为假。被 supersede 的候选仍可审计，新版本通过
`supersedes` 指针承接后续血缘。

为兼容领域适配器，可以保留底层写函数，但 Agent 接入层只能暴露 propose、verify、promote，不能暴露直接写函数。
