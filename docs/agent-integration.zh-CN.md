# 外部 Agent 接入 TraceCite

[English](agent-integration.md) | **简体中文**

状态：`feature_for_agent` / CA258 基线的当前 Host 接入契约。

TraceCite 是 **Evidence Runtime**，不是自治调查 Agent。Host 把确定性的 TraceCite Evidence 能力暴露给外部 Agent；Agent 负责假设、调查顺序、因果推理、证据是否足够、最终答案和停止时机。

对于日常使用，TraceCite 应当在 user/global scope 安装一次。Investigation workflow 不应该变成每个仓库都默认生效的 debugging rule。完整约定见 [全局 Agent 安装](agent-global-setup.zh-CN.md)。

## 1. Host Contract

```text
raw evidence
    -> TraceCite Core/Runtime
    -> bounded Evidence + Coverage + Provenance
    -> host adapter
    -> Agent
```

Host 可以拥有 tool telemetry、model/context budget、native tool access 和 policy prompt，但 Host telemetry 不是 canonical Evidence。

TraceCite 负责：

- source/version 和 evidence identity；
- provenance 与精确 materialization；
- Coverage、truncation、omission、missing-evidence、source-change 等机械事实；
- RetrievalSession 的 seen/repeated/covered-range memory；
- 显式 replay；
- 确定性的 aggregate/traverse；
- bounded evidence projection 与恢复路径；
- 完整性验证。

TraceCite **不负责**：

- Hypothesis 或因果结论；
- root-cause likelihood / ranking；
- evidence sufficiency；
- 下一步应该调查什么；
- 建议 Agent 停止。

## 2. Canonical Evidence 语义

长期 Evidence API 收敛为六类机械原语：

| 原语 | 语义 |
|---|---|
| `retrieve` | Caller 指定 target/scope/predicate -> Evidence + Coverage + Provenance + novelty |
| `materialize` | 精确展开不可变 source/version range |
| `replay` | 显式重读已经见过的 Evidence，不把它伪装成“新证据” |
| `aggregate` | 确定性的 count/distinct/group 等操作 |
| `traverse` | 在 caller 指定 seed/scope/limit 下做机械遍历 |
| `verify` | integrity/source-version/Manifest/Evidence 验证 |

CLI/Host 可以暴露 `probe`、`search`、`expand`、`expand-many` 等便利名字；这些 wrapper 不拥有第二套 Evidence 或 stopping 语义。

## 3. Activation 与 Evidence 使用规则

TraceCite investigation mode 是条件触发的：只有当前任务实际使用 TraceCite tool 或 TraceCite skill 时才启用。不要仅仅因为任务涉及 debugging、log、trace、incident 或 root-cause analysis 就自动启用 TraceCite。

TraceCite mode 启用后：

1. TraceCite Evidence 工作使用 `tracecite-investigate` skill。
2. Incident 事实只能来自 supplied artifacts，除非用户明确授权外部来源。
3. 每次继续 retrieval 前，先明确一个未闭合的 material claim，以及会改变它的 discriminator。
4. 优先获取能支持/反驳该 claim 的最小代表性证据。
5. Material factual claim 尽量引用精确 materialized line/range。
6. Search match 是 Observation，不自动等于 causal proof。
7. No-match 是 retrieval fact，不自动等于真实世界不存在。
8. Truncation、missing evidence、Coverage 不完整、source change 必须显式保留。
9. 复用已知 ref/range；真的需要重新考虑旧证据时使用 replay。
10. 当证据已经足够支持用户要求的 root cause 或其他结论时，直接回答，不继续做确认性搜索。
11. 是否足够、何时停止由 Agent 决定，不由 TraceCite Runtime 决定。

建立这个 activation boundary 的全局 Rule 见 [全局 Agent 安装](agent-global-setup.zh-CN.md)。

## 4. 共享的全局 Skill

本仓库 canonical reusable skill source：

```text
.agents/skills/tracecite-investigate/SKILL.md
```

日常本地使用建议安装到：

```text
~/.agents/skills/tracecite-investigate/SKILL.md
```

当前 Codex、Cursor、Pi 都会发现 `~/.agents/skills/` 下的 user-level skills，因此优先使用这一个共享位置，而不是为每个 Host、每个项目维护一份重复副本。

在 Host 支持 invocation policy 时，这个 skill 应当 explicit-only。它不能变成一个只要看到 debugging 任务就自动启用的通用 skill。

## 5. Codex / OpenAI-compatible Agent

用户级 Codex 配置建议：

- 把共享 skill 安装到 `~/.agents/skills/tracecite-investigate/`；
- 把 canonical 条件触发 Rule 追加到 `~/.codex/AGENTS.md`；
- 保留用户原有 global instructions，不要整文件覆盖；
- 真正使用 TraceCite 时显式调用 `$tracecite-investigate`。

仓库根目录的 `AGENTS.md` 只约束 TraceCite 仓库开发，不是用户级 TraceCite investigation policy。

Codex 可以直接通过 shell 调 TraceCite CLI：

```bash
tracecite probe ./logs --glob "*.log" --recursive
tracecite search app.log "<discriminator>" --snapshot \
  --agent-profile stateful-index \
  --ledger-dir .tracecite/ledger \
  --context-id incident-42
tracecite expand-many .tracecite/ledger RESULT_ID '#L120' '#L188-L190'
```

输入很小、已经有界时直接 read 仍然合理；TraceCite 主要解决 evidence volume、provenance、重复上下文和跨 source correlation 带来的成本与可信问题。

## 6. Cursor

用户级 Cursor 配置建议：

- 把共享 skill 安装到 `~/.agents/skills/tracecite-investigate/`；
- 在 `Customize -> Rules` 中把 canonical 条件触发 Rule 添加成 Cursor **User Rule**（或等价 user-level rule 机制）；
- 真正使用 TraceCite 时显式调用 `/tracecite-investigate`。

本仓库有意不再提供 `.cursor/rules/*.mdc` 形式的 TraceCite investigation rule。`.cursor/README.md` 明确记录这个边界，避免以后重新引入 project-level relevance 自动触发。

Cursor 与 Codex 使用同一套 CLI/Runtime 语义，不创建 Cursor 专属的 Evidence / Coverage / correctness 模型。

## 7. Pi

用户级 Pi 配置建议：

- 把共享 skill 安装到 `~/.agents/skills/tracecite-investigate/`；
- 把 canonical 条件触发 Rule 追加到 `~/.pi/agent/AGENTS.md`；
- 真正使用 TraceCite 时显式调用 `/skill:tracecite-investigate`。

### 已验证 Benchmark 方法

仓库正式 Pi A/B 为了复现性，继续保留历史 repository-local setup：

- `.pi/skills/tracecite/SKILL.md`；
- `benchmarks/agent-investigation/pi_tracecite_extension.ts`；
- TraceCite arm 只暴露 `tracecite_search` 和 `tracecite_expand`；
- bounded system prompt。

已验证 Base Prompt：

```text
You are a coding agent investigating supplied runtime evidence. Keep the investigation bounded. Once the root cause is sufficiently supported, answer immediately instead of performing confirmatory searches. Cite exact evidence lines for material factual claims.
```

TraceCite 追加：

```text
Follow the user's explicit request to use TraceCite. All runtime-evidence content must be obtained through TraceCite tools; do not use native file-access tools for the evidence.
```

仓库内 benchmark 复现方式：

```bash
BASE_PROMPT='You are a coding agent investigating supplied runtime evidence. Keep the investigation bounded. Once the root cause is sufficiently supported, answer immediately instead of performing confirmatory searches. Cite exact evidence lines for material factual claims.'
TRACE_PROMPT="$BASE_PROMPT Follow the user's explicit request to use TraceCite. All runtime-evidence content must be obtained through TraceCite tools; do not use native file-access tools for the evidence."

pi \
  --extension ./benchmarks/agent-investigation/pi_tracecite_extension.ts \
  --tools tracecite_search,tracecite_expand \
  --no-skills --skill ./.pi/skills/tracecite/SKILL.md \
  --no-prompt-templates --no-context-files \
  --system-prompt "$TRACE_PROMPT" \
  "用 tracecite 分析这个问题。${QUESTION}"
```

这个 benchmark setup 是验证 fixture，不是推荐的日常全局安装布局。生产 Pi Host 可以把同样的 canonical Evidence 语义包装成自己的 adapter。

## 8. CLI transport 与 Context Engine

一次性调用：

```bash
tracecite search app.log "timeout" --snapshot
```

有状态 Host 建议把 Ledger 与稳定的 host-owned context ID 配对：

```bash
tracecite search app.log "timeout" --snapshot \
  --agent-profile stateful-index \
  --ledger-dir .tracecite/ledger \
  --context-id incident-42
```

Canonical Result 必须先可通过 Ledger 恢复，再允许 Context Delta 省略本轮已经见过的 Evidence body。省略必须显式，并保持恢复入口。

从 Ledger 一次恢复多条 exact range：

```bash
tracecite expand-many .tracecite/ledger RESULT_ID '#L120' '#L188-L190'
```

详见 [Context Engine](context-engine.zh-CN.md)。

## 9. Result 解释

执行状态和认识状态必须分开：

```text
status  = operation 是否成功执行?
outcome = 返回 Evidence 对命题支持什么?
```

Agent 必须同时检查 Coverage / warnings / missing-evidence，不能因为一次成功的 zero-match 就推出全局不存在。

## 10. Extension

Domain Extension 通过公开 TraceCite contract 提供领域事实/能力；不得拥有 model-specific token policy、seen-evidence state、root-cause conclusion 或 Agent stopping policy。

详见 [Extension Contract](extension-contract.md)。

## 11. Agent Host Benchmark

评估 Agent Host 时：

- paired 条件使用相同 base prompt/model；
- 记录准确 model/tool/usage；
- task result 与 run validity 分开；
- Provider 429/quota/outage 不当成产品失败；
- 先评 answer quality/Evidence boundary，再评效率；
- 保留 raw scorer output，并记录 scorer limitation。

当前正式结果见 [Agent 对比数据](benchmark-results.zh-CN.md)。
