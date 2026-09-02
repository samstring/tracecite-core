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

## Agent usage

### Pi: validated bounded setup

The repository's paired Pi A/B runs use `.pi/skills/tracecite/SKILL.md` and expose only `tracecite_search` / `tracecite_expand` through the Pi extension. The validated bounded system prompt is:

```text
You are a coding agent investigating supplied runtime evidence. Keep the investigation bounded. Once the root cause is sufficiently supported, answer immediately instead of performing confirmatory searches. Cite exact evidence lines for material factual claims.
```

The TraceCite arm appends:

```text
Follow the user's explicit request to use TraceCite. All runtime-evidence content must be obtained through TraceCite tools; do not use native file-access tools for the evidence.
```

Repository-local reproduction pattern:

```bash
BASE_PROMPT='You are a coding agent investigating supplied runtime evidence. Keep the investigation bounded. Once the root cause is sufficiently supported, answer immediately instead of performing confirmatory searches. Cite exact evidence lines for material factual claims.'
TRACE_PROMPT="$BASE_PROMPT Follow the user's explicit request to use TraceCite. All runtime-evidence content must be obtained through TraceCite tools; do not use native file-access tools for the evidence."

pi \
  --extension ./benchmarks/agent-investigation/pi_tracecite_extension.ts \
  --tools tracecite_search,tracecite_expand \
  --no-skills --skill ./.pi/skills/tracecite/SKILL.md \
  --no-prompt-templates --no-context-files \
  --system-prompt "$TRACE_PROMPT" \
  "Use TraceCite to investigate this problem: ${QUESTION}"
```

The extension path above is the adapter currently used by this repository's validation harness. `.pi/skills/tracecite/SKILL.md` is the evidence-use/stopping contract. A production host can expose the same canonical evidence semantics through its own tool adapter.

### Codex: recommended repository setup

Stable repository-wide constraints live in root `AGENTS.md`. The reusable investigation workflow lives at:

```text
.agents/skills/tracecite-investigate/SKILL.md
```

Recommended request:

```text
Use $tracecite-investigate to investigate <problem> from the supplied evidence.
Keep retrieval bounded. Cite exact materialized evidence for material factual claims.
Do not fill evidence gaps with external knowledge; qualify unsupported parts explicitly.
```

Codex can call the TraceCite CLI through shell tools. For large evidence, a useful pattern is:

```bash
tracecite probe ./logs --glob "*.log" --recursive
tracecite search app.log "<discriminator>" --snapshot \
  --agent-profile stateful-index \
  --ledger-dir .tracecite/ledger \
  --context-id incident-42

tracecite expand-many .tracecite/ledger RESULT_ID '#L120' '#L188-L190'
```

The operating rule is: **name one discriminator that can change the current material claim, fetch the minimum evidence needed for it, and do not reopen a closed claim merely for reassurance.**

### Cursor: recommended Project Rule setup

This repository ships:

```text
.cursor/rules/tracecite-investigation.mdc
```

It is a version-controlled project rule for log/trace/support-bundle/root-cause investigation. Let Cursor apply it by relevance or explicitly reference the rule in Agent. Cursor still invokes the same TraceCite CLI through shell tools; it does not define a second evidence model.

Recommended request:

```text
Use the TraceCite investigation rule for this incident.
Investigate only from the supplied evidence, keep retrieval bounded,
and cite exact evidence ranges for the causal claims in the final answer.
```

Pi, Codex, and Cursor differ only in host/prompt/tool adapters. **Evidence, Coverage, Provenance, RetrievalSession, and recovery semantics remain shared.** See [Agent integration](docs/agent-integration.md).

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
- `benchmark-results*.md`: current formal agent A/B measurements.
- `context-engine*.md`: cross-turn evidence delta and recovery.
- `extension-contract.md`: domain extension contract.
- `knowledge-governance*.md`: knowledge lifecycle.
- `adr/` and `migrations/`: historical decisions and migration records; intentionally archival, not current-status pages.

## License

MIT
