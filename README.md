# TraceCite

**English** | [简体中文](README.zh-CN.md)

**A bounded, recoverable, provenance-aware Evidence Runtime for AI agents.**

TraceCite helps coding and debugging agents investigate large logs, support bundles, traces, crash reports, and other diagnostic artifacts without repeatedly pushing whole raw inputs into the model context.

TraceCite does not reason for the agent and does not decide the root cause. TraceCite owns **evidence acquisition, immutable identity, coverage, deduplication/replay, bounded projection, recoverable context, and citation integrity**. The agent owns **hypotheses, causal reasoning, evidence sufficiency, the final conclusion, and when to stop**.

> Current validated agent baseline: `feature_for_agent`, containing the validated CA258 implementation. The package remains `0.1.0` Alpha.

## What problem does TraceCite solve?

The hard part is not that an agent cannot run `grep`. The recurring problems are that:

- evidence can range from MB to GB and broad reads amplify context/cache cost;
- the same evidence is repeatedly returned by different queries;
- provenance is easy to lose across files, entities, and time windows;
- `no match`, truncation, or incomplete coverage can be mistaken for real-world absence;
- an agent can find enough evidence early and still continue confirmatory searches;
- aggressive compression is unsafe if the original evidence cannot be recovered and verified.

TraceCite inserts a deterministic Evidence Runtime between raw artifacts and the agent:

```text
Raw Sources
    |
    v
Evidence Core
source/version identity · snapshot · provenance · verify
    |
    v
Evidence Runtime
retrieve · materialize · replay · aggregate · traverse
RetrievalSession · bounded selection · coverage · identity safety
    |
    v
Integration / Host
Pi · Codex · Cursor · CLI · MCP/custom host
    |
    v
Agent
hypothesis · causal reasoning · sufficiency · final answer · stop
```

![TraceCite architecture](architecture.svg)

## Why use it?

| Capability | What TraceCite provides | Why it matters to an agent |
|---|---|---|
| Bounded evidence | Retrieval/search returns an explicitly bounded evidence view | Large files do not need a broad full-file read |
| Provenance | Source/version, line/range, SHA-256, and Manifest identity | Material claims remain reviewable against the source |
| Session-aware dedup | Already-seen evidence bodies are not resent while current-query relevance is preserved | Less repeated context across turns |
| Materialize / replay | Exact context expansion and deliberate re-reading of old evidence | Dedup never means evidence becomes unrecoverable |
| Coverage / uncertainty | Truncation, missing evidence, source change, and bounded unknowns are explicit | A local view is not silently presented as global truth |
| Identity safety | Mechanical correlation constraints and safe identity keys | Reduces accidental entity/timeline collapse |
| Deterministic aggregation/traversal | Count/distinct/group and caller-scoped traversal | Mechanical work stays outside model reasoning |
| Agent-owned reasoning | Runtime does not emit root-cause likelihood or stop recommendations | Host/model choice remains independent from evidence semantics |
| Recoverable compression | Canonical Result/Ledger preserves recovery paths | Context reduction does not sacrifice auditability |

## Install and basic usage

```bash
python -m pip install tracecite

tracecite probe ./logs --glob "*.log" --recursive
tracecite search app.log "timeout|OOM" --regex --snapshot
tracecite expand .tracecite/snapshots/app.log 120 --before 5 --after 10
tracecite verify .tracecite/runs/<run-id>/manifest.json
```

TraceCite requires Python 3.10+. Linux and macOS are currently supported; Windows is not currently supported. The default package has no runtime dependency outside the Python standard library.

## Agent usage: install once, activate only when used

TraceCite is intended to be installed once at user/global scope and reused across repositories. Do **not** copy a TraceCite investigation rule into every project.

When an AI coding agent is performing the TraceCite setup, it should:

1. install TraceCite itself;
2. install the canonical `tracecite-investigate` skill globally, preferably by copying or symlinking `.agents/skills/tracecite-investigate/` to `~/.agents/skills/tracecite-investigate/`;
3. append the conditional rule below to the host's global/user instructions without overwriting existing instructions;
4. avoid adding repository-local TraceCite rules unless the user explicitly requests repository-specific policy.

`~/.agents/skills/` is the preferred shared user-level skill location because current Codex, Cursor, and Pi releases all discover Agent Skills there.

### TraceCite investigation mode

Install the following as a **global** agent rule:

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

The skill name is shared; explicit invocation syntax differs by host:

| Host | Global skill | Global rule | Explicit skill invocation |
|---|---|---|---|
| Codex | `~/.agents/skills/tracecite-investigate/` | append to `~/.codex/AGENTS.md` | `$tracecite-investigate` |
| Cursor | `~/.agents/skills/tracecite-investigate/` | add as a User Rule in **Customize -> Rules** | `/tracecite-investigate` |
| Pi | `~/.agents/skills/tracecite-investigate/` | append to `~/.pi/agent/AGENTS.md` | `/skill:tracecite-investigate` |

The `tracecite-investigate` skill is intentionally explicit-only on hosts that support that control. Having TraceCite installed must not make ordinary debugging tasks automatically enter TraceCite mode.

See [Global agent setup](docs/agent-global-setup.md) for the installation contract and [Agent integration](docs/agent-integration.md) for host/runtime details.

### Evidence-use pattern while TraceCite mode is active

Codex, Cursor, Pi, or another host can expose the canonical Evidence API directly or call the TraceCite CLI through shell tools. A common large-input pattern is:

```bash
tracecite probe ./logs --glob "*.log" --recursive
tracecite search app.log "<discriminator>" --snapshot \
  --agent-profile stateful-index \
  --ledger-dir .tracecite/ledger \
  --context-id incident-42

tracecite expand-many .tracecite/ledger RESULT_ID '#L120' '#L188-L190'
```

The operating rule is: **name one unresolved material claim and one discriminator that can change it, fetch the minimum evidence needed, and do not reopen a closed claim merely for reassurance.**

The repository's `.pi/`, `.cursor/`, and `.agents/` files remain development, compatibility, and validation assets. In particular, the formal Pi A/B harness still uses the repository-local Pi skill and adapter so historical benchmark conditions stay reproducible. Those repository files are not a recommendation to install TraceCite policy separately into every application repository.

## Measured comparisons

The following are paired Native-vs-TraceCite measurements under the same model conditions. They are observed benchmark results, not a promise of a fixed saving on every model or incident.

### Four public root-cause cases, two repeats

Cases: containerd #6772 plus three Kubernetes cases; bounded Pi prompt; MiniMax M3; eight paired outputs.

| Metric | Native | TraceCite | TraceCite delta |
|---|---:|---:|---:|
| Pass | 6 / 8 | 6 / 8 | equal |
| Concept recall | 78.1% | 87.5% | +9.4 pp |
| Evidence marker recall | 93.8% | 90.6% | -3.1 pp |
| Input tokens | 543,333 | 341,232 | **-37.2%** |
| Output tokens | 89,533 | 52,644 | **-41.2%** |
| Cache-read tokens | 23,973,873 | 5,991,938 | **-75.0%** |
| Model calls | 530 | 195 | **-63.2%** |
| Tool calls | 477 | 357 | **-25.2%** |
| Input + output + cache | 24,606,739 | 6,385,814 | **-74.0%** |

Workflow run: `33620265562`.

### MB-scale public evidence, two repeats

Longhorn #7843 (~17.8 MB model-visible original evidence) plus Harvester #6253 (~7.7 MB); exact CA258 agent/skill/runtime baseline with benchmark-only case/workflow additions; MiniMax M3; four paired outputs.

| Metric | Native | TraceCite | TraceCite delta |
|---|---:|---:|---:|
| Pass | 2 / 4 | 2 / 4 | equal |
| Concept recall | 87.5% | 87.5% | equal |
| Evidence marker recall | 75.0% | 75.0% | equal |
| Input tokens | 494,553 | 289,824 | **-41.4%** |
| Output tokens | 32,836 | 34,194 | +4.1% |
| Cache-read tokens | 13,193,560 | 3,078,682 | **-76.7%** |
| Model calls | 276 | 83 | **-69.9%** |
| Tool calls | 193 | 196 | +1.6% |
| Input + output | 527,389 | 324,018 | **-38.6%** |
| Input + output + cache | 13,720,949 | 3,402,700 | **-75.2%** |

Workflow run: `33638574962`.

The table preserves official scorer output. Manual review found one Longhorn gmi1 TraceCite answer that expressed the gold ordering as “old Unpublish happens after new Publish”; the regex scorer did not recognize that reverse wording, so no manual score correction is applied here. Full data, validity rules, and caveats are in [Benchmark results](docs/benchmark-results.md).

## Architecture

The top-level boundary is intentionally simple:

> **The agent thinks and decides; TraceCite owns evidence.**

```text
                         Domain Extensions
                     Mobile / CI / third-party
                               |
                               v
Raw source -> Evidence Core -> Evidence Runtime -> Integrations -> Agent Host
              |                 |                 |              |
              |                 |                 |              +-- Pi
              |                 |                 |              +-- Codex
              |                 |                 |              +-- Cursor
              |                 |                 |              +-- MCP/custom
              |                 |                 |
              |                 |                 +-- projection / ledger / context
              |                 |
              |                 +-- RetrievalSession
              |                 +-- bounded evidence selection
              |                 +-- identity/correlation safety
              |                 +-- aggregate / traverse
              |                 +-- optional InvestigationState
              |
              +-- source/version identity
              +-- snapshot / provenance / manifest / verify

Agent owns: hypothesis -> causal reasoning -> sufficiency -> answer -> stop
```

### Canonical Evidence API

Long-term semantics converge on six mechanical primitives:

- `retrieve`: caller-selected scope/predicate -> Evidence + Coverage + Provenance + novelty.
- `materialize`: exact context for immutable evidence/ranges.
- `replay`: deliberate re-read of already-seen evidence without pretending it is new.
- `aggregate`: deterministic count/distinct/group operations.
- `traverse`: mechanical traversal under caller-selected seed/scope/limits.
- `verify`: source/version, Manifest, and evidence-integrity checks.

CLI/adapter surfaces such as `search`, `expand`, and `expand-many` are convenience wrappers; they do not own separate causal or stopping semantics.

See [docs/architecture.md](docs/architecture.md) for the normative architecture.

## Documentation

See [docs/README.md](docs/README.md) for the current documentation map.

- `architecture*.md`: normative current architecture.
- `agent-integration*.md`: Pi / Codex / Cursor / CLI / host integration.
- `agent-global-setup.md`: global skill/rule installation and activation boundary.
- `benchmark-results*.md`: current formal agent A/B measurements.
- `context-engine*.md`: cross-turn evidence delta and recovery.
- `extension-contract.md`: domain extension contract.
- `knowledge-governance*.md`: knowledge lifecycle.
- `adr/` and `migrations/`: historical decisions and migration records; intentionally archival, not current-status pages.

## License

MIT
