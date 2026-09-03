# 全局 Agent 安装

[English](agent-global-setup.md) | **简体中文**

TraceCite 是跨项目复用的 Evidence Runtime。安装 TraceCite 时，应当在用户级别把 Agent 配置一次，而不是把 investigation rule 复制到每个仓库。

同样重要的是触发边界：**仅仅安装了 TraceCite，不应该改变无关的 coding/debugging 任务。** 只有当前任务实际使用 TraceCite tool 或 TraceCite skill 时，才进入 TraceCite investigation mode。

## 给安装 Agent 的约定

当 Codex、Cursor、Pi 或其他 Coding Agent 被要求“安装/配置 TraceCite 供全局使用”时：

1. 按用户要求安装 TraceCite package/CLI。
2. 把 canonical `tracecite-investigate` skill 安装到用户级别。优先把本仓库的 `.agents/skills/tracecite-investigate/` 复制或 symlink 到 `~/.agents/skills/tracecite-investigate/`。
3. 把下面的全局规则追加到当前 Host 的 user/global instructions；保留已有规则，不要整文件覆盖。
4. 除非用户明确要求 project-local policy，否则不要往当前项目写 TraceCite rule。
5. 不要因为任务涉及 log、debugging、incident、trace 或 root-cause analysis 就自动选择 TraceCite；必须是当前任务实际使用 TraceCite tool/skill 才触发。

优先使用 `~/.agents/skills/`，因为当前 Codex、Cursor、Pi 都会发现这个用户级 Agent Skills 目录。

## Canonical 全局规则

把下面这段放到 Agent 的全局 instructions：

```md
## TraceCite investigation mode

Only while performing a task that uses TraceCite tools or TraceCite skills.
Do not apply this mode to unrelated tasks, and do not select TraceCite solely because a task is a debugging or investigation task.

- Use the `tracecite-investigate` skill for TraceCite evidence work.
- Keep retrieval bounded.
- Before each new retrieval, identify the unresolved material claim and the discriminator that could change it.
- Once evidence sufficiently supports the root cause or other conclusion required by the user, answer without confirmatory searches.
- Cite exact materialized evidence ranges for material factual claims and separate observations from inferences.
```

Skill 名称保持一致，但 Host 的显式调用语法不同：Codex 使用 `$tracecite-investigate`，Cursor 使用 `/tracecite-investigate`，Pi 使用 `/skill:tracecite-investigate`。

## 各 Host 的全局位置

| Host | 全局 Skill | 全局 Rule / Instructions |
|---|---|---|
| Codex | `~/.agents/skills/tracecite-investigate/` | 追加到 `~/.codex/AGENTS.md` |
| Cursor | `~/.agents/skills/tracecite-investigate/` | 在 **Customize -> Rules** 中添加 User Rule（或等价的 user-level rule 机制） |
| Pi | `~/.agents/skills/tracecite-investigate/` | 追加到 `~/.pi/agent/AGENTS.md` |
| 其他支持 Agent Skills 的 Host | Host 的 user-level Agent Skills 目录 | Host 的 user/global instructions |

优先 user scope，不要默认使用 repository scope。对于不会继承本机 `~/.agents/skills/` 的 Cloud Agent / remote worker，应当把同一份 skill 和 rule 装到远端 worker image 或远端用户配置中，而不是随意写进业务仓库。

## 为什么 Rule 和 Skill 分开

Global rule 故意保持很短，只负责两件事：**什么时候进入 TraceCite 模式**，以及进入后必须遵守的 bounded investigation 行为。

`tracecite-investigate` skill 承载详细的 Evidence API、provenance、Coverage、replay/materialize、trust boundary 等语义。这样可以利用 progressive disclosure，让普通任务不携带 TraceCite 的详细上下文。

在支持显式调用控制的 Host 上，这个 skill 默认关闭 implicit invocation。其他 Host 也应当把 skill 的保守 description 与上面的 global activation rule 当成边界：普通 debugging 不要自动选 TraceCite。

## 仓库里的文件是什么

本仓库仍然保留 `.agents/`、`.pi/`、`.cursor/` 文件，用于开发、验证、兼容性测试和 benchmark 复现。它们存在于 TraceCite 仓库，不等于推荐把这些目录复制进每个业务项目。

生产/日常使用应该是：

```text
全局安装 TraceCite
        +
全局安装 tracecite-investigate
        +
追加一条条件触发的全局 Rule
        ->
只有实际使用 TraceCite 时才启用 investigation mode
```
