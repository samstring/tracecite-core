# 第 7 步：Mobile / CI 领域验收（尚未执行）

本轮只固化流程与问题，不执行 Mobile/CI 真实场景验收，也不推进第 8 步 MCP、Codex Skill 或其他 Agent 平台接入。

## 执行前必须回答的问题

1. `tracecite-ci` 的最小试点放在哪个仓库，由谁维护？
2. Mobile 与 CI 各选哪两个可安全提交、可稳定复现的 fixture（成功/失败各一个）？
3. iOS、Android 是否都必须在首轮通过，还是 Mobile 首轮只选一个平台？
4. 哪些 Mobile 兼容入口属于公开 API，要保留几个版本？
5. live source 与 action 的授权粒度是扩展包、Scenario，还是单条命令？谁有权批准？
6. 扩展加载失败时，CLI 应整体失败、返回 `partial`，还是跳过扩展继续？生产环境是否允许 `strict=False`？
7. `no_match` 在 Mobile/CI 是否统一保持退出码 0？哪些领域结果必须返回非零？
8. Fast Path 与 Deep Path 的时间、Token、证据条数和上下文字符预算分别是多少？
9. Evidence coverage 最少包含哪些维度，什么条件下必须把结论降级为 `unknown`？
10. 哪些结果可作为独立验证，避免 Agent 用自己的结论验证自己的 Knowledge？
11. 首轮最重要的通过指标是什么：定位成功率、误诊率、首次证据时间、引用有效率，还是重复定位成本？
12. 失败后的回滚目标是什么版本，是否需要保留旧三包安装方式？

## A. 全新环境与包边界

- [ ] 从 wheel 安装 `tracecite`、`tracecite-mobile`、最小 `tracecite-ci`。
- [ ] 第三方只需依赖 `tracecite`，不依赖本地源码目录或私有模块。
- [ ] Core 不导入 Runtime、Mobile 或 CI；Runtime 不导入 Mobile 或 CI。
- [ ] 主包不包含设备、产品、公司或应用默认值。
- [ ] `tracecite_core` 公共 import 与 `tracecite-core` 低层命令在约定窗口内可用。

## B. 合成第三方扩展

- [ ] 在 TraceCite 仓库之外创建独立 package，全程不 patch/fork 主库。
- [ ] 通过 entry point 注册自定义 Source、Segmenter、Transformer、Assertion、Reporter、Runtime。
- [ ] 仅 `import tracecite` 不执行第三方注册代码。
- [ ] 显式加载后可按名称运行；重复加载幂等；版本不兼容与冲突可诊断。
- [ ] 安装或卸载扩展不改变默认 Runtime 行为。
- [ ] 未授权 live source/action 即使由扩展声明也不能执行。

## C. Mobile 验收

- [ ] `tracecite-mobile` 只依赖公开 `tracecite` 发行包。
- [ ] Mobile 通过 `tracecite.extensions` 注册 `MOBILE_RUNTIME`，不是 Runtime 内部特例。
- [ ] 原有 Scenario/Assertion/Reporting 兼容 import 保持对象一致。
- [ ] profile、preset、子场景、上下文文件、插件与版本信息都由 Mobile 注入。
- [ ] 至少一个 iOS 与一个 Android fixture 产生预期 Evidence、Result 和 Manifest。
- [ ] 缺少必需来源时返回 `outcome: unknown` 与明确的 `missing_evidence`。
- [ ] Mobile 的 live source/action 只在明确授权路径中运行。

## D. CI 最小试点

- [ ] 不修改 TraceCite 主包，只新增 CI extension。
- [ ] 构建成功与构建失败 fixture 复用同一 Result schema。
- [ ] CI pattern、preset、scenario、knowledge 全部留在 CI 包。
- [ ] `probe/search/expand/verify/run` 无需领域分支即可复用。
- [ ] 零命中不会被解释为“故障不存在”。

## E. P0 证据可信度

- [ ] snapshot 引用指向冻结副本，不指向后续可变的源文件。
- [ ] 引用文件可做哈希复验；任何篡改都会让 `verify` 失败。
- [ ] 非法 JSONL 行保留原始内容与 `parse_error`，不静默丢弃。
- [ ] 相同输入的 unmatched samples 与结果顺序确定。
- [ ] `expand` 拒绝越界引用，并遵守上下文及字符预算。
- [ ] 报告区分 support、contradiction、coverage 与 missing evidence。

## F. P1 可靠性与安全边界

- [ ] 压缩包成员数、单文件大小、总展开大小、压缩比超限时关闭失败。
- [ ] 路径穿越、软链接逃逸和不安全报告路径被拒绝。
- [ ] 默认 Runtime 拒绝 live source 和任意 action。
- [ ] 单个扩展加载失败可以隔离并返回结构化诊断。
- [ ] 运行时异常不会输出非结构化半截结果。

## G. 结论与 Knowledge 防污染

- [ ] `status` 与 `outcome` 分开测试；覆盖不足必须允许 `unknown`。
- [ ] Agent 结论不会自动写入或晋升为 Knowledge。
- [ ] Candidate Knowledge 记录独立案例、支持数、矛盾数、来源质量和版本。
- [ ] 同一 Agent 产生的 conclusion 不可作为自身 Knowledge 的独立验证。
- [ ] Pattern 有稳定 ID、版本、冲突、合并和淘汰策略，避免规则地狱。

## H. 产品效果与发布门禁

- [ ] 对已知问题比较 Fast Path / Deep Path 的耗时与 Token。
- [ ] 记录定位成功率、误诊率、引用有效率、人工日志阅读量。
- [ ] 记录首次与重复定位成本；Schema 更完整但定位成本上升视为不通过。
- [ ] Mobile 与 CI 均通过前不删除兼容入口。
- [ ] 验收通过后再决定 Knowledge registry、MCP 与 Agent 平台 adapter。
