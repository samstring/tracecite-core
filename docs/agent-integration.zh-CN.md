# 外部 Agent 接入 TraceCite

[English](agent-integration.md) | **简体中文**

本文面向 Codex、Claude、ChatGPT、自研 Agent 或任何可调用 CLI/Python Tool 的 Agent Host。

TraceCite 是 **Evidence/Context Gateway**，不是内置 LLM Agent。Domain Extension 通过 Extension Protocol v2 声明能力；Agent 只消费通用 Runtime 和 Integration 暴露的工具，不需要理解 Mobile/CI 的内部实现。

## 0. 定位：网关，不是 grep 替代品

TraceCite 控制什么进入 Agent 上下文，同时把完整可审计结果留在磁盘：

```text
raw source
  -> frozen/canonical evidence
  -> bounded Agent projection
  -> Agent
```

相对 `grep | head`，TraceCite 的优势是可复现 EvidencePointer、Coverage、`unknown` 语义、完整性校验和跨工具 InvestigationState。Canonical JSON 不保证比熟练 grep 更省 token；省上下文依赖 Agent profile、compact projection、Ledger、批量展开，以及后续 Runtime Context Engine。

当前推荐：

```bash
tracecite search app.log "pattern" --no-snapshot \
  --agent-profile agent --ledger-dir /tmp/ledger --lightweight
```

Agent profile 默认限制 evidence 数、单行字符和输出字符。完整 canonical Result 不因投影而改变。

## 1. 接入前提

- Python 3.10+。
- 安装 `tracecite`。
- 对输入有只读权限，对 TraceCite 工作目录有写权限。
- 领域能力通过独立 Extension 包提供，例如 `tracecite-mobile`。
- 第三方 Extension 必须显式加载；`import tracecite` 不自动执行它们。

```bash
python -m pip install tracecite
tracecite --version
```

## 2. Agent 工具表面

| 工具 | Agent 要回答的问题 | 认识语义 |
|---|---|---|
| `probe` | 输入有哪些 source、格式和范围？ | `not_assessed` |
| `sample` / `peek` | 少量原始语境是什么？ | `not_assessed` |
| `survey` | 陌生输入有哪些有界观察？ | `not_assessed` |
| `search` | 当前谓词有哪些 Evidence？ | 命中可 `supported`；零命中仍可能 `unknown` |
| `expand` / `expand-many` | 关键 Evidence 前后发生什么？ | 只证明返回上下文 |
| `run` | Scenario 断言在当前 Coverage 下是否成立？ | 由断言和覆盖决定 |
| `verify` | Manifest/Artifact 是否完整？ | 完整性判断 |
| `investigation` | 创建/更新/摘要/比较/结束调查 | 状态协调，不替代 Evidence |
| `extension` | 显式加载/查看领域扩展 | 不产生诊断结论 |

准确参数以 `tracecite <command> --help` 为准。

Extension Protocol v2 采用声明式 `TraceCiteExtension`。Agent Host 不应直接调用 Extension 内部 registry；显式加载后，领域 `AgentCapability` 进入通用 capability surface，`ScenarioCapability` 被 Runtime 消费。

## 3. 推荐调查循环

```text
probe
  |
有明确锚点？ ---- yes -> Hypothesis
  | no
  -> sample/peek 或 survey
  -> 竞争 Hypothesis
  |
search / domain capability
  |
检查 status + outcome + coverage + missing_evidence
  |
expand / expand-many 关键 Evidence
  |
Finding: supported / contradicted / unknown
  |
记录 stop reason
  |
需要复现时 run Scenario -> verify Manifest
```

### 第一步：探测输入

```bash
tracecite probe ./logs --glob "*.log" --recursive
```

先读 source 元数据、大小、哈希、segmenter 和时间范围，不要把完整目录送入模型。

### 第二步：概览陌生输入

```bash
tracecite sample app.log --strategy head-tail --count 10 --max-chars 8000 --snapshot
tracecite survey app.log --snapshot --max-templates 20 --samples-per-template 2
```

Sample/Survey 只能产生 Observation，不能自动判断根因。必须检查 Coverage 和省略/解析信号。

### 第三步：搜索一个明确假设

```bash
tracecite search app.log "network timeout" --snapshot --last 10m
```

需要正则时显式使用 `--regex`。`search` 默认冻结 source；Evidence 行号和摘要指向冻结副本。

Agent 紧凑投影：

```bash
tracecite search app.log "timeout" --snapshot --compact
tracecite search app.log "timeout" --snapshot --max-output-chars 12000
```

`--compact` 和输出预算只改变 Agent-facing projection，不修改 canonical Result、缓存、InvestigationState、snapshot 或 Artifact。

使用 Evidence Ledger：

```bash
tracecite search app.log "timeout" --snapshot \
  --ledger-dir /tmp/tracecite-ledger
```

Ledger 内容寻址且展开前重新校验摘要。

### 为一次分析选择一个 Agent 传输 Profile

| Profile | 适用 Host | 传输 |
|---|---|---|
| `portable-json` | 任意 Host | 列式 JSON |
| `strict-json` | 强制 JSON Host | 列式 JSON |
| `stateful-index` | 有会话历史与批量工具 | Ledger id + 列式 JSON + 已读历史优化 |
| `frame` | 明确支持 TCF | Ledger id + TCF frame |

不要为了领域扩展改变 profile；profile 是 Integration/Host concern。

### 第四步：展开关键证据

```bash
tracecite expand SNAPSHOT_PATH START_LINE \
  --end-line END_LINE --before 5 --after 10 \
  --expected-sha256 SHA256
```

多条 Evidence 优先：

```bash
tracecite expand-many /tmp/tracecite-ledger RESULT_ID \
  '#L120' '#L188-L190' --before 3 --after 3 \
  --agent-profile stateful-index
```

`expand-many` 会验证 Ledger 和 snapshot 摘要，并合并同次调用中重叠/相邻窗口。后续 Context Engine 会继续扩展跨轮 Seen Evidence 和窗口去重，但这些能力属于 Runtime，不属于 Domain Extension。

### 第五步：记录调查并执行/复验 Scenario

InvestigationState 保存 Problem、Scope、Hypothesis、Test、Execution、Finding、Coverage 和 stop reason。Summary/Timeline/Compare 是有界协调视图，不读取 Evidence 正文，也不会自动诊断。

### 第六步：执行及复验 Scenario

```bash
tracecite run scenario.json
tracecite verify .tracecite/runs/<run-id>/manifest.json
```

Scenario 是测试配方。Extension Protocol v2 的 `ScenarioCapability` 提供领域解析能力；通用 Runtime 保留执行、预算、安全和 Evidence 控制。

## 4. Result JSON 契约

正常工具调用使用版本化 Result envelope。关键原则：

```text
status  = 执行是否成功
outcome = Evidence 对命题支持什么
```

Agent 必须检查：

- `evidence`
- `coverage`
- `missing_evidence`
- `warnings`
- `verification`
- `error`

有界 Agent projection 发生截断时必须显式暴露恢复信息；不能把被截断的视图当成完整 canonical Result。

## 5. EvidencePointer 契约

最终引用应使用可复查 Evidence 指针及摘要/范围；需要上下文时调用 `expand`，不要绕过摘要检查直接把变化中的 live source 当成同一 Evidence。

Extension 内部可以使用稳定的 `EvidenceRef` 描述领域事实；Agent-facing 短 ID 或完整 URI 是 Runtime/Integration 的表示，不是领域 Contract。

## 6. CLI 退出码

- `0`：结构化执行完成，包括 `ok`、合法零命中或部分结果。
- `1`：结构化执行错误。
- `2`：CLI 参数错误。

退出码不能替代 `status/outcome/coverage` 判断。

## 7. Python API

Python Host 应依赖 `tracecite` / `tracecite.runtime` / `tracecite.extension` 的公开符号，不导入领域包的内部模块或 Runtime registry。

领域扩展的 v2 入口：

```python
from tracecite.extension import load_extensions, list_extensions

load_extensions(strict=True)
print(list_extensions())
```

如果 Host 需要 Scenario，当前可通过公开 host helper 解析已安装的 scenario adapter；这只是当前集成桥，不应成为新的领域依赖方向。

## 8. 领域扩展

v2 扩展通过 `TraceCiteExtension` 声明 `ExtensionManifest + capabilities`。完整开发规则见 [Extension Contract v2](extension-contract.md)。

领域扩展应该提供：

- Source/解析/Event 等领域事实能力。
- Agent query/action capability 及安全声明。
- Scenario/Assertion/Report 等领域能力。
- EvidenceRef 与 Coverage。

领域扩展不应该提供：

- LLM-specific ContextPack。
- token 排序策略。
- Seen Evidence 状态。
- MCP tool schema。
- root-cause 结论或自动 Knowledge promotion。

v1 扩展迁移见 [迁移说明](migrations/extension-protocol-v2.zh-CN.md)。

## 9. Agent 安全与判断规则

1. Evidence 不自动等于完整 Truth。
2. `status=ok` 不等于 `outcome=supported`。
3. 零命中、Coverage 缺口和 missing evidence 不能证明事件不存在。
4. Sample/Survey/DomainEvent 不自动成为 Finding。
5. Snapshot/Manifest 摘要失败时停止引用对应 Evidence。
6. 未授权不启用 live source 或 live action。
7. 第三方 Extension 仅显式加载。
8. Agent 结论不能自我验证或自动晋升 Knowledge。
9. InvestigationState 是协调元数据，不是原始 Evidence。
10. 最终报告区分 hypothesis、support、contradiction、unknown 和 missing evidence。

## 10. 可复制的测试 Prompt

```text
你要使用 TraceCite 调查指定输入。TraceCite 是 Evidence 工具，不是结论生成器。

1. 先定义 Problem 和 Scope。
2. 输入未知或很大时先 probe；必要时用 sample/survey 建立语境。
3. 写出可证伪 Hypothesis，并说明可能的反证。
4. 使用 search 或已加载的领域 capability 获取有界 Evidence。
5. 检查 status、outcome、coverage、missing_evidence。
6. 对关键 Evidence 使用 expand/expand-many 并校验摘要。
7. 只有 Evidence + Coverage 足够时形成 supported/contradicted；否则保持 unknown。
8. 记录 stop reason，并给出下一步安全查询。
```

## 11. 最小验收标准

- [ ] 能用 `probe -> search -> expand` 完成一次可追溯调查。
- [ ] 能解析 Result schema，而不是从人类文案猜状态。
- [ ] 能区分 `status`、`outcome`、Coverage 和 missing evidence。
- [ ] 能验证 Evidence digest/Manifest。
- [ ] 能使用 InvestigationState 保存 Hypothesis/Test/Finding/stop reason。
- [ ] 能显式加载 Extension Protocol v2 扩展，并通过通用 capability surface 调用领域能力。
- [ ] 不直接依赖 Domain Extension 内部 Runtime/registry。
- [ ] 不把 Agent context/token 策略写回领域 Contract。
