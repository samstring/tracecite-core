# TraceCite

**面向 AI 调试 Agent 的可扩展证据运行时。**

TraceCite 让 Agent 分析大体量、持续变化的日志，而不必把全部原始日志塞进上下文。它会冻结输入、返回有预算的证据引用、校验证据来源，并允许第三方在不修改 TraceCite 源码的情况下增加领域能力。

```text
原始数据 -> Core 证据层 -> Runtime 工具层 -> 外部 Agent
                               ^
                               |
                         领域扩展包
                    Mobile / CI / 第三方
```

TraceCite 是给 Codex、Claude、ChatGPT 或自研 Agent 使用的基础设施，内部不再套一层 LLM Agent。

## 安装与使用

```bash
pip install tracecite

tracecite probe ./logs --glob "*.log" --recursive
tracecite search app.log "timeout|OOM" --regex --snapshot
tracecite expand .tracecite/snapshots/app.log 120 --before 5 --after 10
tracecite verify .tracecite/runs/<run-id>/manifest.json
tracecite run scenario.json
```

所有命令返回确定性的 JSON。`status` 表示执行是否成功，`outcome` 单独表示证据支持什么。零命中是合法结果，不等于“问题没有发生”。

准备让 Codex、Claude 或其他自研 Agent 直接测试时，请先阅读[外部 Agent 接入指南](docs/agent-integration.zh-CN.md)。其中包含调用顺序、Result JSON、退出码、安全规则和可复制的测试 Prompt。

低层证据命令仍可通过 `tracecite-core` 使用。

## 一个主项目，清晰的逻辑边界

- `tracecite_core`：Source、Segment、Transform、Evidence、Snapshot、Manifest、Verify 与底层 Plugin SDK。
- `tracecite.runtime`：Scenario、Assertion、Reporting、Result schema、预算、安全门禁和 Agent 工具。
- `tracecite.extension`：有版本的第三方扩展契约。
- `tracecite.integrations`：目前提供 CLI；MCP、Codex Skill 等适配器后续再接。

领域语义不进入主包。`tracecite-mobile` 是独立的官方扩展，也是 Extension API 的真实验证项目。

## 不改主库，增加自己的能力

第三方包只依赖一个公开发行包：

```toml
[project]
name = "my-company-tracecite"
dependencies = ["tracecite>=0.1,<0.2"]

[project.entry-points."tracecite.extensions"]
my_domain = "my_tracecite.extension"
```

```python
from tracecite.extension import ExtensionAPI
from tracecite.runtime import ScenarioRuntime

TRACECITE_EXTENSION_API = "1"
MY_RUNTIME = ScenarioRuntime(
    load_profile=load_profile,
    resolve_scenario_pattern=resolve_pattern,
)

def register(api: ExtensionAPI) -> None:
    api.register_runtime("my-domain", MY_RUNTIME)
```

加载第三方代码是显式动作：

```bash
tracecite extension load
tracecite run scenario.json --runtime my-domain --load-extensions
```

仅仅 `import tracecite` 不会执行第三方注册代码。API 版本会校验，注册冲突默认失败，默认 Runtime 不授权 live source 和 action。

详细约束见[扩展契约](docs/extension-contract.md)；第 7 步暂未执行，执行前问题与验收流程见[领域验证清单](docs/validation-checklist.md)。Agent 知识写入遵循独立的[提案、验证与晋升流程](docs/knowledge-governance.zh-CN.md)。

## 核心原则

- Evidence 可追溯，但不自动等于完整事实或真相。
- `unknown` 和 `missing_evidence` 是一等结果。
- Agent 自己生成的结论不能自动晋升为可信 Knowledge。
- Extension 提供能力和领域语义；Runtime 保留执行、预算、验证和安全控制权。
- Core 不导入 Runtime 或领域；Runtime 不导入 Mobile/CI。

## 当前状态

主项目 Runtime 合并与旧 API 兼容层已实现。Mobile/CI 双领域验收仍有意保留为待执行步骤；通过前不推进 MCP、Codex Skill 或其他 Agent 平台接入。

## License

MIT
