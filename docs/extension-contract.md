# TraceCite Extension Contract

目标：第三方不修改、不 fork TraceCite，通过稳定、声明式、可独立版本化的契约提供领域数据、语义与能力；Runtime 内部实现、Agent 上下文策略和宿主适配可以持续演进，而无需反复修改领域扩展。

## 1. 产品边界

```text
Agent / CLI / MCP
       |
Integration / Agent Projection
       |
Investigation Runtime
       |
Evidence Core
       ^
       |
TraceCite Extension Protocol
       |
Mobile / CI / Backend / Third-party
```

最重要的控制原则：

> Extension 提供领域事实和能力；Runtime 控制执行、预算、Evidence、验证、安全、停止和 Agent Context。

Extension 不感知当前 LLM、Token 策略、ContextPack、Seen Evidence、Context Delta 或 MCP tool schema。

## 2. 顶层协议

当前 Extension Protocol 不把可变的 `ExtensionAPI.register_xxx()` 注册表面作为公共入口。扩展声明一个 `TraceCiteExtension`：

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


def extension() -> TraceCiteExtension:
    return EXTENSION
```

推荐 entry point：

```toml
[project.entry-points."tracecite.extensions"]
my_domain = "my_tracecite.extension:extension"
```

加载仍然是显式动作；仅 `import tracecite` 不执行第三方代码。Host 通过 `load_extensions()` 或相应 CLI 动作加载已安装扩展。

使用者不需要选择 V1/V2 接入模式；新的领域扩展统一使用当前声明式 Extension Contract。

## 3. ExtensionManifest

`ExtensionManifest` 只描述稳定身份：

- `id`：全局扩展 ID。
- `version`：扩展发行版本。
- `domain`：领域标识。
- `description`：可选说明。
- `protocol_version`：机器兼容性字段，当前值为 `2`。

`protocol_version` 用于加载和兼容校验，不代表对外存在多套可选接入模式。Manifest 不保存 Runtime 实现、Agent profile、Token 预算或领域数据。

## 4. Capability 模型

顶层协议保持极小；新增能力优先增加独立版本 Capability，而不是修改 `TraceCiteExtension`。

当前 Capability Contract：

| kind | v | 用途 |
|---|---:|---|
| `core.plugins` | 1 | 打包低层 `PluginAPI` 注册：Source、Segmenter、Format、Detector、Preprocessor、Event Transformer |
| `agent.capability` | 1 | 暴露有界 query/action，并复用 Runtime safety gate |
| `runtime.assertion` | 1 | 领域 Assertion |
| `runtime.report` | 1 | 领域 Reporter |
| `runtime.scenario` | 1 | profile、preset/subscenario resolver、context files 等 Scenario 领域能力 |

Capability 版本独立于 Extension Protocol。未来只升级某个 Capability 时，不要求其他能力同时升级。

同一个扩展内 `(kind, name)` 不允许重复。注册冲突默认失败；当前协议不提供隐式 replace 行为。

## 5. Scenario 边界

当前公共边界使用 `ScenarioCapability`：

```text
Domain Extension
  -> ScenarioCapability
  -> Generic Investigation Runtime
```

当前实现内部仍可把 `ScenarioCapability` 适配成 `ScenarioRuntime`，用于复用现有 Scenario 执行器；这是实现细节，不是新的公共依赖。领域扩展不得导入或持有 Runtime 内部 registry 来改变执行控制权。

## 6. 稳定领域值对象

### EvidenceRef

领域侧对 Evidence 的稳定引用。它描述 source、范围、摘要和有限 metadata，但不绑定 Agent 看到的短 ID 或 URI 表示。

```text
Extension: EvidenceRef
Core/Store: canonical pointer / digest
Agent View: E17 等短引用
```

因此未来 Agent transport 改变不会要求领域扩展迁移。

### Coverage

所有有界、抽样、近似、截断或不完整能力都应显式返回 Coverage。通用字段包括：

- `complete`
- `scanned`
- `returned`
- `omitted`
- `truncated`
- `reasons`
- `details`

领域特有 Coverage 可以进入 `details`，但不能静默省略不完整性。

### DomainEvent

`DomainEvent` 描述结构化领域事实：

```python
DomainEvent(
    type="mobile.network.request_failed",
    timestamp="...",
    severity="error",
    attributes={"status": 504, "endpoint": "/home"},
    evidence=(ref,),
)
```

Event 可以包含 `type`、`timestamp`、`severity`、`attributes`、`evidence`。

它**不能**把以下内容伪装成事实：

- 当前问题的 relevance/rank。
- token priority。
- root cause。
- `supported` / `contradicted` Finding。

这些属于 Runtime/Agent 调查阶段。

### SourceDescriptor / SourceCursor / SourceChunk

通用 Source 不限定为本地文件：

- `SourceDescriptor` 描述逻辑 source。
- `SourceCursor` 是领域拥有的 opaque progress token。
- `SourceChunk` 返回 records、`next_cursor` 与 Coverage。

Cursor 可以映射为文件 byte/line offset、live segment、远程 continuation token、数据库 `(timestamp,id)` 等。Runtime 不解析 token 语义，只将其交还给对应 capability。

### CapabilityResult[T]

领域 capability 推荐使用统一执行 envelope：

```python
CapabilityResult(
    status="ok",
    value=...,
    evidence=(...),
    coverage=Coverage(...),
    diagnostics=(...),
)
```

`status` 只表示执行成功/失败。它不能替代 Investigation 的 epistemic `outcome`。

## 7. 低层 Core PluginAPI

`tracecite_core.PluginAPI` 仍是低层 Evidence Core 的公共插件协议，当前版本独立维护。Domain Extension 若需要打包 Source/Segmenter/Preprocessor/Event Transformer 注册，可通过 `CorePluginCapability` 提供 registrar，由主包在安装扩展时传入 `PluginAPI`。

这样 Core Plugin 与 Domain Extension 顶层协议解耦：一个协议升级不强制另一个整体升级。

## 8. Agent Capability 与安全

`AgentCapability` 复用 `CapabilitySpec` 和 Runtime registry。领域只声明：

- dotted name
- `query` / `action`
- description / input schema
- `read` / `live_source` / `live_action`
- 是否需要显式 authorization
- deterministic executor

Runtime 继续拥有 safety gate。Extension 不能绕过 live-source/live-action 授权。

## 9. 发现、加载与失败隔离

- `tracecite.extensions` entry point 返回 `TraceCiteExtension`，或返回/导出 `extension()` / `EXTENSION`。
- loader 校验顶层机器协议版本和 Capability version。
- 同一 entry point 默认幂等。
- `strict=True` 时加载失败终止；非 strict 模式结构化记录单个失败。
- Distribution 名称和版本属于加载 provenance，不写入领域事实。
- 导入主包不会自动发现或执行扩展。

## 10. 不允许扩展改写的语义

Extension 不能：

- 修改 Canonical Evidence、Result、Manifest、Verify 的语义。
- 把 Agent 推理文本作为独立 Evidence。
- 把 Agent Finding 自动晋升为 Knowledge。
- 静默隐藏 Coverage 缺口。
- 控制 Runtime 的 token/context 策略。
- 为某个 Agent 平台生成专属结果并作为 canonical domain output。
- 绕过预算、live safety 或 authorization gate。

## 11. Context / Token 边界

Context 优化属于 Runtime/Integration：

```text
Canonical Result / Evidence
        |
Runtime Context Engine
  dedupe / seen / group / delta / budget
        |
Agent Projection
        |
Host
```

因此以下概念不会加入 Extension Protocol：

- ContextPack / AgentView
- Seen Evidence
- Context Delta
- token estimate / model tokenizer
- Agent profile
- MCP tool surface
- stop hint based on context gain

Domain Extension 只需提供足够结构化、可追溯的事实和 capability；Runtime 可以在不改变 Extension 的情况下迭代这些策略。

## 12. 版本与兼容策略

- 对外只有一套 TraceCite Extension Contract，不要求使用者选择 V1/V2 模式。
- `protocol_version` 仍作为机器兼容性字段维护，当前值为 `2`。
- Capability 各自独立版本。
- 不兼容的顶层协议变化必须新增 ADR、迁移说明、测试和领域验收。
- 新能力优先作为新的可选 Capability；不要为了一个新功能增加新的顶层 `register_xxx`。
- Persisted Investigation/Knowledge/Manifest schema 的版本与 Extension Protocol 相互独立。

旧版 `ExtensionAPI` / `TRACECITE_EXTENSION_API = "1"` / `register(api)` 已废弃，不是当前接入选项。历史迁移记录保留在 [Extension protocol migration](migrations/extension-protocol-v2.zh-CN.md)，仅用于维护旧代码和理解演进历史。

## 13. 当前状态

Core 已实现声明式 Extension Contract、Capability version 校验、显式 loader，以及到现有 Scenario/Assertion/Reporter/Agent Capability registry 的内部适配。

Mobile 已通过同一声明式 Extension Contract 接入。MCP 只接 Runtime/Context 公共接口，不直接依赖 Extension 内部 registry。
