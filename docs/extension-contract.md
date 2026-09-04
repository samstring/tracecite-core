# TraceCite Extension Contract

状态：当前 `feature_for_agent` 的 Living Contract。

目标：第三方无需修改或 fork TraceCite，即可通过稳定、声明式、独立版本化的契约提供领域数据与能力；Core/Runtime 内部实现、Agent Context 策略和 Host Adapter 可以持续演进，而不要求领域扩展跟随重写。

## 1. 产品边界

```text
                    Agent Host
              Pi / Codex / Cursor / MCP
                         |
                         v
              Integration / Projection
                         |
                         v
                   Evidence Runtime
                         |
                         v
                    Evidence Core
                         ^
                         |
            TraceCite Extension Protocol
                         |
                         v
             Mobile / CI / third-party
```

控制原则：

> **Extension 提供领域事实和能力；TraceCite 负责确定性的 Evidence 执行与可信边界；Agent 负责推理、sufficiency 和 stopping。**

因此 Extension 不感知当前 LLM、Token 策略、ContextPack、Seen Evidence、Context Delta、Pi/Cursor/MCP tool schema，也不能输出 root-cause ranking 或 Agent stopping policy。

## 2. 顶层协议

Extension 声明一个 `TraceCiteExtension`，而不是依赖不断增长的 `ExtensionAPI.register_xxx()` 表面：

```python
from tracecite.extension import ExtensionManifest, TraceCiteExtension

EXTENSION = TraceCiteExtension(
    manifest=ExtensionManifest(
        id="my-domain",
        version="1.0.0",
        domain="my-domain",
    ),
    capabilities=(...),
)

extension = EXTENSION
```

推荐通过 Python entry point 发布：

```toml
[project.entry-points."tracecite.extensions"]
my_domain = "my_tracecite.extension:extension"
```

顶层对象保持稳定，能力通过独立 `kind/name/version` 演进。

## 3. 当前公共 Capability 类型

公共 Contract 可以承载以下类别的能力：

- Core plugin bundle：Source / Segmenter / Preprocessor / Event transformer 等低层 domain-neutral 插件注册包；
- Agent Capability：领域只读查询或经授权的动作能力；
- Scenario Capability：领域 profile / preset / scenario resolver；

`ScenarioCapability` 在 Runtime 内部被适配为 `ScenarioServices`；Extension 不依赖该内部类型。历史 `ScenarioRuntime` 名称仅保留兼容别名，不再位于 Extension 执行链。
- Assertion Capability：领域断言；
- Report Capability：领域报告；
- 后续能力应优先新增独立版本化 Capability，而不是扩大顶层 Extension API。

每个 Capability 的执行仍受 TraceCite Runtime/Host 的预算、安全、授权和 Evidence 边界约束。

## 4. 稳定领域值对象

Extension 与 Runtime 之间使用不依赖具体 Host 的通用 Contract：

### `EvidenceRef`

领域侧 Evidence 引用。它不能绑定 Pi/Cursor/Codex 的短 ID、MCP URI 命名或某个模型格式。

### `Coverage`

表达扫描范围、返回/省略、截断、近似、missing evidence 和原因。Coverage 是机械事实，不是“证据够不够”的结论。

### `DomainEvent`

表达结构化领域事实。例如：

```text
10:30:04 /home -> HTTP 504
```

它不能携带针对当前问题的：

```text
relevance score
root-cause likelihood
token priority
stop recommendation
```

### `SourceDescriptor` / `SourceCursor` / `SourceChunk`

支持文件、stream、remote API 等 incremental source。Cursor token 对 Runtime 来说是 opaque domain token；Runtime 不解释其业务含义。

### `CapabilityResult[T]`

统一执行 envelope。执行 `status` 与 Evidence/Finding 层认识状态保持分离。

## 5. Extension 可以做什么

Extension 可以：

- 识别/解析本领域 Source；
- 把领域记录转换为结构化 DomainEvent；
- 提供领域查询能力及其 EvidenceRef/Coverage；
- 提供 Scenario / Assertion / Report 能力；
- 声明 read-only / live source / live action 等安全属性；
- 为领域数据返回稳定 identity/correlation 所需字段；
- 在 public contract 范围内提供版本 provenance。

## 6. Extension 不可以做什么

Extension 不得：

- 保存 Agent 的 RetrievalSession seen-state；
- 根据当前模型或 token budget 对 Evidence 做 model-specific 排序；
- 输出 `root_cause_confidence`、`evidence_sufficient`、`stop_recommended`；
- 决定 Agent 下一步应该查哪个实体/来源；
- 把 `no_match` 解释成真实世界不存在；
- 把 Host tool activity 伪装成 canonical Evidence；
- 自动把 Agent 结论晋升为可信 Knowledge；
- 绕过 Runtime/Host 的授权执行 live source/action；
- 让 MCP/Pi/Cursor schema 反向成为领域 Contract。

## 7. Runtime / Agent 的职责分离

TraceCite Runtime 控制的是**机械执行边界**：

- Evidence request/response；
- source/version identity；
- RetrievalSession；
- Coverage / truncation / omission；
- budget limit / provider unavailable 等 acquisition-end facts；
- deterministic aggregate/traverse；
- authorization / safety gate；
- canonical Result recovery / verification。

Agent 控制的是**调查决策**：

- Hypothesis；
- investigation direction；
- causal reasoning；
- Evidence 是否足够回答用户问题；
- final answer；
- stop decision。

即使 Runtime 报告 `new_evidence=0`、`frontier_exhausted=true` 或 `budget_limit_reached=true`，这些也只是机械事实，不自动等于“调查完成”。

## 8. Host / Integration Boundary

Pi、Codex、Cursor、MCP 或自定义 Host 可以把同一 canonical Evidence Contract 投影成各自工具表面。Host 可以记录 Tool Activity、model/context budget 和 wall time，但这些 telemetry 不进入 Extension Contract。

Agent-facing transport 可能使用 compact projection、Evidence Ledger、Context Delta 或其他可恢复编码；这些属于 `tracecite.integrations` / Host，不属于 Domain Extension。

## 9. 加载与安全

- `import tracecite` 不应自动执行第三方 Extension。
- Extension 加载是显式动作；strict 模式下无效/不兼容 Extension 应明确失败。
- Extension ID / Capability `(kind,name)` 冲突必须确定性处理，不产生半注册状态。
- live source / live action 必须通过显式授权路径。
- Extension output 与外部 Source 一样属于不可信输入，仍需 Evidence/validation boundary。

## 10. 版本与兼容

- 顶层 Extension Protocol 尽量稳定；Capability 独立版本化。
- 公共 schema/API 不兼容变化需要 migration note + tests。
- 旧 v1 -> v2 的迁移说明保留在 `docs/migrations/` 作为历史记录。
- 不为了错误的旧语义永久保留兼容层；breaking change 必须明确版本、迁移和验证范围。

## 11. 领域能力进入主包的门槛

新的通用能力只有在证明服务多个独立领域、且不引入领域语义后，才应进入主包。否则留在 Domain Extension。

主包提供机制；Extension 提供领域事实和能力。

## 12. 验收

新增/修改 Extension Contract 时至少验证：

- Core/Runtime dependency direction 不被反转；
- 无 domain-specific 默认值进入主包；
- Capability version/collision 行为确定性；
- Coverage / EvidenceRef / source identity 保持可追溯；
- 未授权 live action fail closed；
- Extension 不引入 Agent root-cause/sufficiency/stopping policy；
- `architecture*.md`、本 Contract、migration/ADR 与测试同步。

规范架构见 [architecture.md](architecture.md) / [architecture.zh-CN.md](architecture.zh-CN.md)。
