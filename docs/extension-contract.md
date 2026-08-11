# TraceCite Extension Contract v1

目标：第三方不修改、不 fork TraceCite，通过独立 Python 包提供自己的数据来源、解析、断言、报告和领域调查流程。

## 产品边界

```text
外部 Agent / CLI / MCP
          |
   TraceCite Runtime
     /          \
Core Evidence   Domain Extensions
                Mobile / CI / Third-party
```

一个 `tracecite` 发行包包含 Core、Runtime、Extension API 与通用集成；Mobile、CI 和公司能力是独立扩展包。

最重要的控制原则：

> Extension 提供能力和语义；Runtime 控制执行、预算、证据引用、验证、安全门禁和停止条件。

## v1 公共扩展面

Core `PluginAPI` 支持注册：

- Source provider
- Segmenter、声明式 format 与 detector
- Preprocessor
- Event transformer

Runtime `ExtensionAPI` 支持注册：

- Assertion type
- Report outputter
- 命名 `ScenarioRuntime`

`ScenarioRuntime` 可注入 profile、preset/子场景解析、上下文文件、插件元数据和运行时版本。领域扩展自己保存 Marker、Pattern、Knowledge、Scenario、设备及产品适配。

## 发现与加载

扩展通过 Python entry point 声明：

```toml
[project.entry-points."tracecite.extensions"]
my_domain = "my_tracecite.extension"
```

入口必须声明 `TRACECITE_EXTENSION_API = "1"`，并提供 `register(api)`。加载器校验 API 版本、记录 distribution 元数据、保证同一入口幂等；注册冲突默认失败，替换必须显式请求。

扩展加载不会发生在 `import tracecite` 时。调用方必须执行 `tracecite extension load`、为 `run` 传 `--load-extensions`，或显式调用 `load_extensions()`。

## 安全与可信度不允许扩展改写

- 默认 Runtime 禁止 live source 和 action。
- Extension 不能更改 Evidence、Result、Manifest 和 Verify 的语义。
- Evidence 必须可追溯；缺失证据必须允许结果为 `unknown`。
- Extension 不能把 Agent 结论直接晋升为可信 Knowledge。
- 插件加载失败应结构化报告；非 strict 模式下隔离单个失败。
- 运行输出必须受证据条数、上下文大小、时间和展开预算约束。

## 兼容策略

- `tracecite_core` 继续作为稳定 Core 公共 import。
- Agent-facing Runtime 只通过 `tracecite` 与 `tracecite.runtime` 暴露，不存在独立 Agent 包。
- 删除旧入口前，必须先发布迁移说明、设定版本窗口，并让 Mobile 与 CI 同时通过领域验收。

## v1 尚未声称解决

- 通用 Marker / Pattern / Knowledge semantic registry。
- Knowledge 自动成长或自动晋升。
- 扩展沙箱或进程级隔离。
- MCP、Codex Skill、Claude 等平台适配。
- Mobile 和 CI 的真实跨领域通用性证明。

这些能力必须在领域验收后按真实需求继续演进，避免先造一个过胖 Runtime。
