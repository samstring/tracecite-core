# Integrating an External Agent with TraceCite

**English** | [简体中文](agent-integration.zh-CN.md)

This guide is for Codex, Claude, ChatGPT, custom agents, or any Agent Host that can call CLI/Python tools.

TraceCite is an **Evidence/Context Gateway**, not an embedded LLM agent. Domain Extensions declare capabilities through Extension Protocol v2; Agent Hosts consume the generic Runtime and Integration surfaces and do not need Mobile/CI implementation details.

## 0. Positioning: a gateway, not a grep replacement

TraceCite controls what enters Agent context while preserving complete auditable results on disk:

```text
raw source
  -> frozen/canonical evidence
  -> bounded Agent projection
  -> Agent
```

Compared with `grep | head`, TraceCite adds reproducible EvidencePointers, Coverage, explicit `unknown`, integrity checks, and cross-tool InvestigationState. Canonical JSON is not guaranteed to be cheaper than skilled grep; context efficiency comes from Agent profiles, compact projection, the Evidence Ledger, batch expansion, and later Runtime Context Engine work.

Recommended current transport:

```bash
tracecite search app.log "pattern" --no-snapshot \
  --agent-profile agent --ledger-dir /tmp/ledger --lightweight
```

Agent profiles bound evidence count, line length, and output size without changing the canonical Result.

## 1. Prerequisites

- Python 3.10+.
- Install `tracecite`.
- Read permission for inputs and write permission for the TraceCite working directory.
- Domain capabilities are supplied by separate Extension packages such as `tracecite-mobile`.
- Third-party Extensions are loaded explicitly; `import tracecite` does not execute them.

```bash
python -m pip install tracecite
tracecite --version
```

## 2. Agent tool surface

| Tool | Agent question | Epistemic role |
|---|---|---|
| `probe` | What sources, formats, and ranges exist? | `not_assessed` |
| `sample` / `peek` | What does a small amount of raw context look like? | `not_assessed` |
| `survey` | What bounded observations exist in unfamiliar input? | `not_assessed` |
| `search` | What Evidence matches this predicate? | matches may support; zero matches can remain `unknown` |
| `expand` / `expand-many` | What happened around key Evidence? | proves only returned context |
| `run` | Does a Scenario assertion hold under current Coverage? | assertion/coverage dependent |
| `verify` | Is a Manifest/Artifact still intact? | integrity judgment |
| `investigation` | Create/update/summarize/compare/stop an investigation | coordination, not Evidence |
| `extension` | Explicitly load/view domain extensions | no diagnosis |

Use `tracecite <command> --help` for exact arguments.

Extension Protocol v2 uses declarative `TraceCiteExtension` objects. Hosts should not call domain extension registries directly. After explicit loading, domain `AgentCapability` entries enter the generic capability surface and `ScenarioCapability` is consumed by Runtime.

## 3. Recommended investigation loop

```text
probe
  |
strong anchor? ---- yes -> Hypothesis
  | no
  -> sample/peek or survey
  -> competing Hypotheses
  |
search / domain capability
  |
inspect status + outcome + coverage + missing_evidence
  |
expand / expand-many key Evidence
  |
Finding: supported / contradicted / unknown
  |
record stop reason
  |
if reproducibility is needed: run Scenario -> verify Manifest
```

### Step 1: probe input

```bash
tracecite probe ./logs --glob "*.log" --recursive
```

Read source metadata, size, digest, segmenter, and time range before deciding what to search. Do not push an entire directory into model context.

### Step 2: orient on unfamiliar input

```bash
tracecite sample app.log --strategy head-tail --count 10 --max-chars 8000 --snapshot
tracecite survey app.log --snapshot --max-templates 20 --samples-per-template 2
```

Sample and Survey create observations, not root-cause findings. Inspect Coverage and omission/parsing signals.

### Step 3: search one explicit hypothesis

```bash
tracecite search app.log "network timeout" --snapshot --last 10m
```

Use `--regex` only when needed. Search freezes the source by default, so evidence ranges and digests target an immutable copy.

Compact Agent projection:

```bash
tracecite search app.log "timeout" --snapshot --compact
tracecite search app.log "timeout" --snapshot --max-output-chars 12000
```

Compact/output budgets change only the Agent-facing projection, never the canonical Result, cache, InvestigationState, snapshot, or Artifact.

Evidence Ledger:

```bash
tracecite search app.log "timeout" --snapshot \
  --ledger-dir /tmp/tracecite-ledger
```

Ledger entries are content-addressed and revalidated before expansion.

### Choose one Agent transport profile per investigation

| Profile | Host | Transport |
|---|---|---|
| `portable-json` | any Host | columnar JSON |
| `strict-json` | JSON-only Host | columnar JSON |
| `stateful-index` | session history + batch tools | Ledger id + columnar JSON + read-history optimization |
| `frame` | explicit TCF support | Ledger id + TCF frame |

Profiles are Integration/Host concerns, not domain-extension concerns.

### Step 4: expand key evidence

```bash
tracecite expand SNAPSHOT_PATH START_LINE \
  --end-line END_LINE --before 5 --after 10 \
  --expected-sha256 SHA256
```

Prefer batch expansion for multiple references:

```bash
tracecite expand-many /tmp/tracecite-ledger RESULT_ID \
  '#L120' '#L188-L190' --before 3 --after 3 \
  --agent-profile stateful-index
```

`expand-many` verifies Ledger and snapshot digests and merges overlapping/adjacent windows within one call. Later Context Engine work extends seen-evidence and cross-turn window deduplication; those features remain Runtime concerns.

### Step 5: record the investigation and prepare reproducibility

InvestigationState stores Problem, Scope, Hypothesis, Test, Execution, Finding, Coverage, and stop reason. Summary/Timeline/Compare are bounded coordination views; they do not read raw Evidence bodies or diagnose automatically.

### Step 6: execute and verify a Scenario

```bash
tracecite run scenario.json
tracecite verify .tracecite/runs/<run-id>/manifest.json
```

A Scenario is a repeatable test recipe. Extension Protocol v2 `ScenarioCapability` supplies domain parsing/context while the generic Runtime retains execution, budget, safety, and Evidence control.

## 4. Result JSON contract

Normal tools return a versioned Result envelope. The primary distinction is:

```text
status  = did execution succeed?
outcome = what does Evidence support?
```

Agents inspect:

- `evidence`
- `coverage`
- `missing_evidence`
- `warnings`
- `verification`
- `error`

If an Agent projection is truncated it must expose recovery information; a truncated view is not the complete canonical Result.

## 5. EvidencePointer contract

Final claims should cite reviewable Evidence with digest/range. Use `expand` for context rather than treating a changing live source as the same immutable Evidence.

Extensions may use stable `EvidenceRef` values to describe domain facts. Agent short IDs or full URIs are Runtime/Integration representations, not domain contracts.

## 6. CLI exit codes

- `0`: structured execution completed, including valid zero-match/partial results.
- `1`: structured execution error.
- `2`: CLI argument error.

Exit codes never replace `status`, `outcome`, and Coverage interpretation.

## 7. Python API

Python Hosts should depend on public `tracecite`, `tracecite.runtime`, and `tracecite.extension` symbols rather than domain-private modules or Runtime registries.

Extension v2 discovery:

```python
from tracecite.extension import load_extensions, list_extensions

load_extensions(strict=True)
print(list_extensions())
```

Current host helpers may resolve installed scenario adapters for Scenario execution; that bridge is not a new domain dependency direction.

## 8. Domain extensions

A v2 Extension declares `ExtensionManifest + capabilities` through `TraceCiteExtension`. See [Extension Contract v2](extension-contract.md).

Domain extensions should provide domain source/parsing/event facts, bounded Agent query/action capabilities with safety declarations, Scenario/Assertion/Report semantics, and EvidenceRef/Coverage.

They should not provide LLM-specific ContextPack, token ranking, Seen Evidence state, MCP schemas, root-cause verdicts, or automatic Knowledge promotion.

See the [v1 to v2 migration](migrations/extension-protocol-v2.md).

## 9. Agent safety and judgment rules

1. Evidence does not automatically equal complete truth.
2. `status=ok` does not mean `outcome=supported`.
3. Zero matches, Coverage gaps, and missing evidence do not prove absence.
4. Sample/Survey/DomainEvent does not automatically become a Finding.
5. Stop citing Evidence when snapshot/Manifest integrity fails.
6. Do not enable live sources/actions without authorization.
7. Load third-party Extensions explicitly.
8. Agent conclusions cannot self-verify or automatically promote Knowledge.
9. InvestigationState is coordination metadata, not raw Evidence.
10. Final reports distinguish hypothesis, support, contradiction, unknown, and missing evidence.

## 10. Copyable test prompt

```text
Use TraceCite to investigate the specified input. TraceCite is an Evidence tool, not a conclusion generator.

1. Define Problem and Scope.
2. For large/unknown input, probe first; use sample/survey only when orientation is needed.
3. Write a falsifiable Hypothesis and possible contradicting observation.
4. Use search or an explicitly loaded domain capability for bounded Evidence.
5. Check status, outcome, coverage, and missing_evidence.
6. Expand key Evidence and verify digests.
7. Return supported/contradicted only when Evidence + Coverage justify it; otherwise return unknown.
8. Record a stop reason and the next safe query.
```

## 11. Minimum acceptance criteria

- [ ] `probe -> search -> expand` completes one traceable investigation.
- [ ] Result schema is parsed rather than inferred from prose.
- [ ] `status`, `outcome`, Coverage, and missing evidence are distinguished.
- [ ] Evidence digest/Manifest verification works.
- [ ] InvestigationState records Hypothesis/Test/Finding/stop reason.
- [ ] Extension Protocol v2 extensions can be explicitly loaded and domain capability invoked through the generic surface.
- [ ] Host does not depend directly on domain-private Runtime/registry code.
- [ ] Agent context/token strategy is not written into the domain contract.
