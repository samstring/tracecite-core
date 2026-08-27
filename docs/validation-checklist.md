# 第 7 步：Extension v2 / Mobile / CI 领域验收

本清单用于验证 TraceCite 主包公共边界是否真正跨领域，而不是只对 Mobile 有效。Extension Protocol v2 Core Contract 已进入实现与 Core CI 验证阶段；Mobile v2 迁移、真实设备验收和 CI 最小试点按顺序继续。

当前重构基线统一为 `feature_for_agent`，重构分支从该基线创建。历史测试数字只用于审计，不作为本次验收结论；每个阶段以对应分支的最新 CI 为准。

## 执行前必须回答的问题

1. `tracecite-ci` 最小试点放在哪个仓库，由谁维护？
2. Mobile 与 CI 各选哪些可安全提交、可稳定复现的成功/失败 fixture？
3. iOS、Android 真机是否都纳入首轮发布门禁？
4. Extension v1 入口何时删除，是否只保留迁移文档而不保留长期兼容实现？
5. live source/action 的授权粒度是什么，谁有权批准？
6. Extension 加载失败时生产 Host 是否允许 `strict=False`？
7. `no_match` 在 Mobile/CI 是否统一保持退出码 0，并由 `outcome/coverage` 表达认识状态？
8. Fast Path / Deep Path 的时间、证据、Context 和调用预算分别是多少？
9. Coverage 最少包含哪些维度，何时必须降级为 `unknown`？
10. 哪些结果可作为独立 Knowledge 验证？
11. 首轮核心指标是定位成功率、误诊率、首次 Evidence 时间、引用有效率、上下文成本中的哪些？
12. MCP 对外工具面如何保持只依赖公开 Runtime/Context API？

## A. 全新环境与包边界

- [ ] 从 wheel 安装 `tracecite`、`tracecite-mobile` 和最小 CI extension。
- [ ] 第三方只依赖公开 `tracecite`，不依赖本地源码路径或私有 Runtime registry。
- [ ] Core 不导入 Runtime、Mobile、CI；Runtime 不导入 Mobile、CI。
- [ ] 主包不包含设备、产品、公司或应用默认值。
- [ ] `tracecite_core` 低层公共 import/命令按其独立版本策略可用。

## B. 合成 Extension Protocol v2 扩展

- [ ] 在 TraceCite 仓库外创建独立 package，不 patch/fork 主库。
- [ ] entry point 返回 `TraceCiteExtension` 或 `extension()` / `EXTENSION`。
- [ ] `ExtensionManifest` 的 id/domain/version/protocol 校验确定性。
- [ ] Capability 采用独立版本；未知/不兼容版本明确失败。
- [ ] 可声明 CorePlugin、Agent、Scenario、Assertion、Report Capability。
- [ ] 仅 `import tracecite` 不执行第三方 Extension。
- [ ] 显式加载后能力可用；同一 entry point 重复加载幂等。
- [ ] Extension ID 和 `(kind,name)` 冲突可诊断且默认不 replace。
- [ ] 未授权 live source/action 即使由 Extension 声明也不能执行。

## C. 稳定领域 Contract

- [ ] `EvidenceRef` 不绑定 Agent URI/短 ID 表示。
- [ ] `Coverage` 明确完整性、扫描/返回/省略、截断及原因。
- [ ] `DomainEvent` 只表达领域事实，不含 relevance、root cause、token priority 或 Finding outcome。
- [ ] `SourceDescriptor/SourceCursor/SourceChunk` 可同时表示文件、live/remote 增量 source。
- [ ] Runtime 把 `SourceCursor.token` 当 opaque token，不解释领域语义。
- [ ] `CapabilityResult.status` 与 Investigation `outcome` 独立。

## D. Mobile v2 验收

- [ ] `tracecite-mobile` 只依赖公开 `tracecite`。
- [ ] Mobile extension 入口声明 `ExtensionManifest + capabilities`，不接收 `ExtensionAPI`。
- [ ] Mobile 不把 `ScenarioRuntime` 作为公共扩展依赖；使用 `ScenarioCapability`。
- [ ] 原低层 Source/Segmenter/Preprocessor/Event Transformer 注册通过 `CorePluginCapability` 或公开 Core Plugin Contract 提供。
- [ ] 原设备/环境/进程/会话等 Agent 工具通过 `AgentCapability` 声明。
- [ ] profile、preset、subscenario、context files 和版本 provenance 由 Mobile Capability 提供。
- [ ] 至少一个 iOS 与一个 Android fixture 产生预期 Evidence、Result 和 Manifest。
- [ ] 缺少必需来源时保持 `unknown` 并明确 `missing_evidence/Coverage`。
- [ ] Mobile live source/action 只走明确授权路径。
- [ ] Mobile 不出现 ContextPack、token policy、MCP schema 等上层概念。

## E. CI 最小试点

- [ ] 不修改 TraceCite 主包，只新增 CI Extension。
- [ ] CI 使用同一 `TraceCiteExtension` / Capability Contract，不新增 CI 特例。
- [ ] 构建成功和失败 fixture 复用同一 Result/Coverage/Evidence 语义。
- [ ] CI pattern、preset、scenario、knowledge 保留在 CI 包。
- [ ] `probe/search/expand/verify/run` 不需要 Runtime 领域分支。
- [ ] 零命中不会被解释为“故障不存在”。

## F. P0 Evidence 可信度

- [ ] snapshot 指向冻结副本。
- [ ] Evidence/Manifest 可复验摘要；篡改使 Verify 失败。
- [ ] 非法输入不静默丢弃，保留 parse error/coverage signal。
- [ ] 相同输入的有界样本和结果顺序确定。
- [ ] `expand` 拒绝越界并遵守预算。
- [ ] 报告区分 support、contradiction、coverage 与 missing evidence。

## G. Context / Token 阶段验收

Context Engine 在 Core v2 Contract 与文档/测试稳定后实现。

- [ ] Canonical Result/Evidence 不因 Agent View 优化改变。
- [ ] Seen Evidence 属于 Investigation/Context state，不写入 Evidence 本体。
- [ ] 跨轮重复 Evidence 可抑制，同时保留恢复/审计路径。
- [ ] 重叠 expand range 可跨调用识别已读区间。
- [ ] Evidence grouping 返回代表样本并显式报告 group count/omission。
- [ ] Context Delta 只发送新增/变化信息，且不会静默丢失 Coverage gap。
- [ ] stop hint 只描述确定性的信息增益/预算状态，不自动作根因 Finding。
- [ ] 记录 raw size、Agent view size、重复抑制和调用次数等 Context metrics。
- [ ] Context Engine API 不进入 Domain Extension Protocol。

## H. P1 可靠性与安全边界

- [ ] 压缩包资源限制和路径安全保持 fail-closed。
- [ ] 默认 Runtime 拒绝未授权 live source/live action。
- [ ] 单个 Extension 加载失败可隔离并结构化诊断。
- [ ] Capability collision/version mismatch 不产生半注册状态。
- [ ] 运行异常不输出非结构化半截结果。

## I. 结论与 Knowledge 防污染

- [ ] `status` 与 `outcome` 分开测试。
- [ ] Coverage 不足允许 `unknown`。
- [ ] Agent 结论不会自动写入/晋升 Knowledge。
- [ ] 同一 Agent 结论不可成为自身独立验证。
- [ ] Knowledge 只推荐未来 Hypothesis/Test/Preset/Scenario，不替代当前 Evidence。

## J. MCP 发布门禁

MCP 最后处理：

- [ ] MCP 不导入 Mobile 私有模块或 Extension registry 内部状态。
- [ ] MCP 只消费公开 Runtime Capability / Extension metadata / Context projection API。
- [ ] MCP tool schema 不反向成为 Domain Capability Contract。
- [ ] live source/action 授权语义与 CLI/Python 一致。
- [ ] MCP 输出保持 Coverage、unknown、missing evidence 和恢复路径。
- [ ] Tool surface 经过收敛，避免机械暴露大量低层命令造成额外 Agent schema token。

## K. 架构演进与文档治理

- [ ] `docs/architecture.md` 与 `docs/architecture.zh-CN.md` 同步。
- [ ] Extension Protocol v2 的 ADR 已记录背景、替代方案、迁移和验证。
- [ ] v1 -> v2 迁移说明存在并由 Mobile 实际执行验证。
- [ ] 公共 API/Schema 有独立版本策略和自动化测试。
- [ ] Implementation status 表只描述已验证能力。
- [ ] Mobile 与 CI 两个领域验证前，不把 Mobile-specific 语义提升为主包通用能力。
