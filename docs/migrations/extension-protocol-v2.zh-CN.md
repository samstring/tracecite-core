# Extension Protocol v1 -> v2 迁移

Extension Protocol v2 用声明式 `TraceCiteExtension` + 独立版本 Capability，替代 v1 的可变 `ExtensionAPI.register_xxx()`。

## 迁移前：v1

```python
from tracecite.extension import ExtensionAPI
from tracecite.runtime import ScenarioRuntime

TRACECITE_EXTENSION_API = "1"
MY_RUNTIME = ScenarioRuntime(
    load_profile=load_profile,
    resolve_scenario_pattern=resolve_pattern,
)


def register(api: ExtensionAPI) -> None:
    register_core_plugins(api)
    api.register_capability(MY_SPEC, execute_my_tool)
    api.register_runtime("my-domain", MY_RUNTIME)
```

```toml
[project.entry-points."tracecite.extensions"]
my_domain = "my_tracecite.extension"
```

## 迁移后：v2

```python
from tracecite.extension import (
    AgentCapability,
    CorePluginCapability,
    ExtensionManifest,
    ScenarioCapability,
    TraceCiteExtension,
)

EXTENSION = TraceCiteExtension(
    manifest=ExtensionManifest(
        id="my-domain",
        version="2.0.0",
        domain="my-domain",
    ),
    capabilities=(
        CorePluginCapability(
            name="my-domain.core",
            register=register_core_plugins,
        ),
        AgentCapability(
            spec=MY_SPEC,
            executor=execute_my_tool,
        ),
        ScenarioCapability(
            name="my-domain",
            load_profile=load_profile,
            resolve_scenario_pattern=resolve_pattern,
        ),
    ),
)


def extension() -> TraceCiteExtension:
    return EXTENSION
```

```toml
[project.entry-points."tracecite.extensions"]
my_domain = "my_tracecite.extension:extension"
```

## 对照表

| v1 | v2 |
|---|---|
| `TRACECITE_EXTENSION_API = "1"` | `ExtensionManifest(protocol_version="2")`（默认） |
| `register(api)` | `extension() -> TraceCiteExtension` |
| `api.register_capability(spec, executor)` | `AgentCapability(spec, executor)` |
| `api.register_assertion_type(name, fn)` | `AssertionCapability(name, fn)` |
| `api.register_report_outputter(name, fn)` | `ReportCapability(name, fn)` |
| `api.register_runtime(name, ScenarioRuntime(...))` | `ScenarioCapability(name, ...)` |
| Source/Segmenter 等低层注册 | `CorePluginCapability(name, registrar)`，内部接收 `PluginAPI` |

## 行为变化

- v2 声明式协议不提供 replace。重复 Extension ID 或 `(kind, name)` Capability 确定性失败。
- `ScenarioRuntime` 不再是领域扩展公共依赖；Runtime 可以内部构造它作为过渡适配。
- Capability 独立版本化；只升级一种能力不要求整个扩展同时升级。
- Extension 不控制 Agent context/token 策略。
- `DomainEvent` 只描述事实，不能携带 relevance、root cause 或 Finding 结论。
- `CapabilityResult.status` 只表示执行状态；Investigation 的 `outcome` 仍独立。

## 迁移清单

1. 从扩展入口删除 `ExtensionAPI` 和公共 `ScenarioRuntime` 依赖。
2. 把每个注册动作转换成声明式 Capability。
3. 已经干净的低层 `PluginAPI` Source/Segmenter/Preprocessor/Event Transformer 注册逻辑可以保留为 registrar。
4. 把领域 Scenario callback 放入 `ScenarioCapability`。
5. entry point 改为 `module:extension`，或直接导出 `EXTENSION`。
6. 更新测试：显式加载 Extension，并验证安装后的 Capability。
7. 跑完整领域离线 fixture 与安全测试。
8. 领域通过后再删除 v1 专用兼容代码。

## Context / Token 功能

迁移过程中不要把 Seen Evidence、Context Delta、token limit、模型名称或 MCP 细节塞进 Domain Extension。这些能力属于 Runtime/Integration；v2 的目的之一就是让领域扩展以后不再因为 Agent 上下文策略变化而频繁修改。
