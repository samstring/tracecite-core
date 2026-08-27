# TraceCite

**面向 AI 调试 Agent 的可扩展 Evidence Runtime。**

TraceCite 面向大体量、持续变化的数据，提供有界、可验证、可追溯的 Evidence。它不是内置 LLM 的自治 Agent；外部 Agent 负责推理，TraceCite 负责确定性数据处理、调查状态、预算、安全、Coverage 和 Evidence 完整性。

```text
原始数据 -> Evidence Core -> Investigation Runtime -> Agent / CLI / MCP
                    ^               ^
                    |               |
               Core plugins   Extension Protocol v2
                                  |
                           Mobile / CI / 第三方
```

## 安装与使用

```bash
pip install tracecite

tracecite probe ./logs --glob "*.log" --recursive
tracecite search app.log "timeout|OOM" --regex --snapshot
tracecite expand .tracecite/snapshots/app.log 120 --before 5 --after 10
tracecite verify .tracecite/runs/<run-id>/manifest.json
tracecite run scenario.json
```

Python 3.10+，支持 Linux 和 macOS。当前 Windows 不在支持范围，因为原子状态锁依赖 POSIX `flock`。主包除 Python 标准库外无运行时依赖。

所有核心命令返回确定性 JSON。`status` 表示执行是否成功，`outcome` 表示 Evidence 支持的认识状态；零命中不是“问题不存在”的证明。

外部 Agent 接入见[Agent 接入指南](docs/agent-integration.zh-CN.md)，跨轮上下文见[Context Engine](docs/context-engine.zh-CN.md)，顶层约束见[规范架构](docs/architecture.zh-CN.md)。

## 分层

- `tracecite_core`：Source、Segmenter、Sample、Survey、Filter、Snapshot、Evidence、Manifest、Verify 与低层 Plugin SDK。
- `tracecite.runtime`：Investigation、Scenario、Assertion、Reporting、预算、缓存、安全门禁和 Agent Capability。
- `tracecite.extension`：声明式 Extension Protocol v2 与稳定领域 Contract。
- `tracecite.integrations`：CLI、Agent-facing transport/projection、Evidence Ledger 与 Context Engine；MCP 作为独立适配项目演进。
- `tracecite.knowledge`：Knowledge Candidate、独立验证、审核、版本与失效。

领域语义不进入 Core/Runtime。`tracecite-mobile` 是独立官方领域扩展，也是公共 Contract 的真实验证项目。

## Extension Protocol v2

v2 不再要求领域扩展接收一个不断增长的 `ExtensionAPI.register_xxx()`。扩展声明自己是谁、具备什么能力：

```toml
[project.entry-points."tracecite.extensions"]
my_domain = "my_tracecite.extension:extension"
```

```python
from tracecite.extension import (
    ExtensionManifest,
    ScenarioCapability,
    TraceCiteExtension,
)

EXTENSION = TraceCiteExtension(
    manifest=ExtensionManifest(
        id="my-domain",
        version="1.0.0",
        domain="my-domain",
    ),
    capabilities=(
        ScenarioCapability(
            name="my-domain",
            load_profile=load_profile,
            resolve_scenario_pattern=resolve_pattern,
        ),
    ),
)

extension = EXTENSION
```

顶层协议保持很小，能力独立版本化。当前公共能力包括 Core plugin bundle、Agent Capability、Assertion、Report 和 Scenario Capability。完整规则见[Extension Contract v2](docs/extension-contract.md)，v1 迁移见[迁移说明](docs/migrations/extension-protocol-v2.zh-CN.md)。

## 稳定领域数据 Contract

v2 提供一组不依赖具体 Agent/Transport 的通用值对象：

- `EvidenceRef`：领域侧 Evidence 引用，不绑定 Agent URI/短 ID。
- `Coverage`：覆盖、遗漏、截断和近似信息。
- `DomainEvent`：结构化领域事实，不包含 relevance/root cause/token priority。
- `SourceDescriptor` / `SourceCursor` / `SourceChunk`：支持文件、live stream、远程 API 等增量 Source。
- `CapabilityResult[T]`：统一执行 envelope；执行 `status` 与 Finding `outcome` 分离。

## Agent Context 与 Token 传输

Canonical Result 和不可变 Evidence 始终保持可恢复。省 Token 只发生在 Agent transport 层，不会改写领域事实或 canonical Evidence。

现有 compact projection 和 Evidence Ledger 现在已经接入有界、可持久化的 Context Engine。有状态 Host 可以给一次调查/会话提供稳定的 context ID：

```bash
tracecite search app.log "timeout" --snapshot \
  --agent-profile stateful-index \
  --ledger-dir /tmp/tracecite-ledger \
  --context-id incident-42
```

第一轮正常返回有界 Evidence；后续同一 `context_id` 的重叠 search 会省略该 context 已经见过的 Evidence URI，并在 `data.context` 中明确给出新 Evidence、重复 Evidence、revision 和 state pruning 信息。完整 canonical search Result 会先进入内容寻址 Ledger，因此跨轮去重不会破坏恢复能力。

需要一次恢复多条不可变 Evidence 时：

```bash
tracecite expand-many /tmp/tracecite-ledger RESULT_ID '#L120' '#L188-L190'
```

Context state 是有界的传输记忆，不是可信 Evidence，也不替代 InvestigationState。没有稳定 URI 的 Evidence 不会被静默去重；不同 context ID 不共享 seen-state。代表性 Evidence grouping 仍属于后续优化，不进入 Extension Protocol v2。

## 安全与可信度

- Evidence 可追溯，但不自动等于完整事实或真相。
- `unknown`、`missing_evidence` 和 Coverage 缺口是一等状态。
- Agent 结论不能自动晋升为可信 Knowledge。
- Domain Extension 不能绕过 Runtime 的预算、live-source/live-action 和 authorization gate。
- Core 不导入 Runtime 或领域；Runtime 不导入 Mobile/CI。
- `import tracecite` 不自动执行第三方 Extension；加载是显式动作。
- Context Delta 只改变传输视图；canonical Result/Evidence 始终可恢复。

## 当前状态

Extension Protocol v2、声明式 Capability 加载、稳定领域 Contract、Evidence Ledger、有界跨轮 Context Delta 与 stateful CLI 路径已经实现，并通过 Core Python 3.10–3.14 Linux/macOS 全矩阵。匹配的 Mobile v2 分支和 MCP v2/context 集成也已经分别通过各自 CI；真实 Agent Host 验收与 Token 节省 benchmark 仍作为独立验收项。

## License

MIT
