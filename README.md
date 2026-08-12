# TraceCite

**Extensible evidence runtime for AI debugging agents.**

Give an agent large, changing logs without putting all of those logs into its
context. TraceCite freezes inputs, returns bounded evidence pointers, verifies
their provenance, and lets domain packages add investigation capabilities
without modifying TraceCite itself.

```text
Raw data -> Core evidence -> Runtime tools -> Your Agent
                                  ^
                                  |
                       Domain extensions
                  Mobile / CI / third-party
```

TraceCite is infrastructure **for** Codex, Claude, ChatGPT, or a custom agent.
It does not embed another LLM agent.

## Install

```bash
pip install tracecite
```

The package has no runtime dependencies outside the Python standard library.

## Agent-facing tools

```bash
tracecite probe ./logs --glob "*.log" --recursive
tracecite search app.log "timeout|OOM" --regex --snapshot
tracecite expand .tracecite/snapshots/app.log 120 --before 5 --after 10
tracecite verify .tracecite/runs/<run-id>/manifest.json
tracecite run scenario.json
```

Every command returns deterministic JSON. `status` describes whether execution
succeeded; `outcome` separately describes what the evidence supports. A valid
zero-match search is not an execution error and does not prove absence.

Before connecting Codex, Claude, or another host, read the
[external Agent integration guide](docs/agent-integration.md). It includes the
tool loop, Result JSON contract, exit codes, safety rules, and a reusable test
prompt.

The lower-level evidence CLI remains available as `tracecite-core`.

## Stable kernel, public extension boundary

One main distribution contains four logical layers:

- `tracecite_core`: evidence, source, segment, transform, snapshot, manifest,
  verification, and the low-level plugin SDK.
- `tracecite.runtime`: scenario, assertion, reporting, result schema, budgets,
  stop/safety gates, and agent-facing tools.
- `tracecite.extension`: the versioned third-party registration contract.
- `tracecite.integrations`: CLI now; MCP and agent-platform adapters later.

Domain semantics do not belong in the main package. The official
`tracecite-mobile` project is an extension and a contract dogfood project.

## Build an extension without forking TraceCite

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

Loading third-party code is explicit:

```bash
tracecite extension load
tracecite run scenario.json --runtime my-domain --load-extensions
```

Importing `tracecite` alone never executes installed extension registration
code. Registration conflicts fail by default, API versions are checked, and
the default Runtime does not grant live-source or action capabilities.

See [the extension contract](docs/extension-contract.md) and the
[pending domain-validation checklist](docs/validation-checklist.md). Agent
knowledge uses the separate
[proposal, verification, and promotion lifecycle](docs/knowledge-governance.md).

## Design principles

- Evidence is traceable, not automatically complete or true.
- `unknown` and `missing_evidence` are first-class results.
- Agent conclusions never promote themselves into trusted knowledge.
- Extensions add capabilities and semantics; Runtime retains execution,
  evidence, verification, budget, and safety control.
- Core never imports Runtime or domain packages; Runtime never imports domains.

## Status

The internal Runtime consolidation and compatibility layer are implemented.
Mobile and CI cross-domain acceptance is intentionally pending; MCP, Codex
Skill, and other agent-platform adapters follow only after that contract is
validated.

## License

MIT
