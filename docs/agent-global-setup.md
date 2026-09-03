# Global agent setup

TraceCite is a cross-project Evidence Runtime. Installing TraceCite should configure the agent once at user scope; it should not require copying investigation rules into every repository.

The activation boundary is equally important: merely having TraceCite installed must not change unrelated coding or debugging tasks. TraceCite investigation mode becomes active only while the current task actually uses TraceCite tools or TraceCite skills.

## Install contract for coding agents

When an AI coding agent is asked to install or configure TraceCite for general use:

1. Install the TraceCite package/CLI as requested.
2. Install the canonical `tracecite-investigate` skill at user scope, preferably by copying or symlinking this repository's `.agents/skills/tracecite-investigate/` directory to `~/.agents/skills/tracecite-investigate/`.
3. Add the global rule below to the host's user-level/global instruction mechanism. Preserve existing user instructions; append or merge rather than overwrite.
4. Do **not** add a TraceCite rule to the current repository unless the user explicitly asks for repository-local policy.
5. Do **not** activate TraceCite investigation mode merely because the task involves logs, debugging, incidents, traces, or root-cause analysis. Activation requires actual TraceCite tool/skill use.

`~/.agents/skills/` is the preferred shared skill location because current Codex, Cursor, and Pi releases all discover user-level Agent Skills there.

## Canonical global rule

Add this rule to the agent's global instructions:

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

The skill name is canonical; invocation syntax differs by host. Codex can explicitly invoke it as `$tracecite-investigate`, Cursor as `/tracecite-investigate`, and Pi as `/skill:tracecite-investigate`.

## Host-specific global locations

| Host | Global skill | Global rule/instructions |
|---|---|---|
| Codex | `~/.agents/skills/tracecite-investigate/` | append the rule to `~/.codex/AGENTS.md` |
| Cursor | `~/.agents/skills/tracecite-investigate/` | add it as a User Rule in **Customize -> Rules** (or an equivalent user-level rule mechanism) |
| Pi | `~/.agents/skills/tracecite-investigate/` | append the rule to `~/.pi/agent/AGENTS.md` |
| Other Agent-Skills hosts | host user-level Agent Skills directory | host user-level/global instructions |

Prefer user scope over repository scope. For remote/cloud agents that do not receive local user-level skill directories, install the same skill and rule into the remote worker image or the host's remote user configuration rather than copying them into arbitrary application repositories.

## Why the rule and skill are separate

The global rule is intentionally short. It defines **when** TraceCite mode is active and the bounded investigation behavior expected while active.

The `tracecite-investigate` skill defines the detailed Evidence API, provenance, Coverage, replay/materialization, trust, and evidence-boundary semantics. Keeping the detailed workflow in a skill preserves progressive disclosure and keeps unrelated tasks free of TraceCite-specific context.

For Codex/OpenAI-compatible hosts, the skill metadata disables implicit invocation. Cursor-specific skill metadata also marks the skill explicit-only. Other hosts should treat the conservative skill description and this global activation rule as the boundary: do not auto-select TraceCite for ordinary debugging.

## Repository files are source/validation assets

This repository still contains `.agents/`, `.pi/`, and `.cursor/` files for development, validation, and host compatibility. Their presence in this repository is not a recommendation to copy those directories into every target project.

Production/general-use setup is:

```text
install TraceCite globally
        +
install tracecite-investigate globally
        +
append one conditional global rule
        ->
activate only when TraceCite is actually used
```
