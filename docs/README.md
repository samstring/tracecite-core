# TraceCite documentation map

Status: current documentation index for `feature_for_agent` after the validated CA258 merge (2026-09-02).

TraceCite documentation is split into **living contracts** and **archival history**. Living contracts describe the current implementation and must stay synchronized with code. ADRs and migrations intentionally describe historical decisions/transitions and should not be rewritten to look current.

## Living documentation

| Document | Purpose | Status |
|---|---|---|
| [`../README.md`](../README.md) / [`../README.zh-CN.md`](../README.zh-CN.md) | Project overview, advantages, global Agent setup, benchmark summary, architecture | Current |
| [`architecture.md`](architecture.md) / [`architecture.zh-CN.md`](architecture.zh-CN.md) | Normative architecture and ownership boundaries | **Normative / Current** |
| [`agent-global-setup.md`](agent-global-setup.md) / [`agent-global-setup.zh-CN.md`](agent-global-setup.zh-CN.md) | Global skill/rule installation, host locations, and TraceCite activation boundary | Current |
| [`agent-integration.md`](agent-integration.md) / [`agent-integration.zh-CN.md`](agent-integration.zh-CN.md) | Agent host integration, Pi/Codex/Cursor recipes, Evidence API semantics | Current |
| [`benchmark-results.md`](benchmark-results.md) / [`benchmark-results.zh-CN.md`](benchmark-results.zh-CN.md) | Validated paired Agent A/B measurements and caveats | Current |
| [`context-engine.md`](context-engine.md) / [`context-engine.zh-CN.md`](context-engine.zh-CN.md) | Cross-turn evidence delta, Ledger recovery, context transport | Current |
| [`extension-contract.md`](extension-contract.md) | Extension Protocol and domain capability contract | Current |
| [`knowledge-governance.md`](knowledge-governance.md) / [`knowledge-governance.zh-CN.md`](knowledge-governance.zh-CN.md) | Knowledge candidate/review/version lifecycle | Current |
| [`investigation-summary.md`](investigation-summary.md) / [`investigation-summary.zh-CN.md`](investigation-summary.zh-CN.md) | Investigation state summary semantics | Current |
| [`investigation-compare.md`](investigation-compare.md) / [`investigation-compare.zh-CN.md`](investigation-compare.zh-CN.md) | Investigation timeline/compare semantics | Current |
| [`PROJECT_GUARDRAILS.md`](PROJECT_GUARDRAILS.md) | Hard product/evidence boundary guardrails | Current |
| [`architecture-governance.md`](architecture-governance.md) | Architecture change governance | Current |
| [`validation-checklist.md`](validation-checklist.md) | Release/change validation gates | Current |
| [`adr-agent-runtime-semantic-boundary.zh-CN.md`](adr-agent-runtime-semantic-boundary.zh-CN.md) | Accepted semantic-boundary decision record | Accepted ADR |

## Archival documentation

These are intentionally historical and are not current-status pages:

- [`adr/`](adr/): architecture decision records.
- [`migrations/`](migrations/): schema/API/behavior migration notes.

When a historical document conflicts with a living contract, use this precedence:

```text
PROJECT_GUARDRAILS
    -> architecture.md / architecture.zh-CN.md
    -> current integration/contract docs
    -> accepted ADRs
    -> migrations / historical records
```

## Removed obsolete process documents

After CA258 became the validated `feature_for_agent` baseline, the following process-only documents were removed from the living tree because their goals are implemented/superseded and their wording referred to old experiment branches:

- `evidence-intelligence-experiment.zh-CN.md`
- `evidence-intelligence-work-progress-handoff.zh-CN.md`
- `evidence-runtime-refactor-plan.zh-CN.md`
- `evidence-runtime-architecture.zh-CN.md`

Implemented runtime contracts from the old target-architecture document are now part of the normative `architecture*.md` files. Git history remains the source for the old experiment/handoff material.

## Documentation maintenance rule

A code change must update living docs in the same change when it changes any of:

- dependency direction or layer ownership;
- canonical Evidence API/semantics;
- RetrievalSession or evidence identity/coverage behavior;
- Agent/Host integration or tool surface;
- Context/Ledger/recovery semantics;
- extension or knowledge trust boundaries;
- benchmark status presented as current evidence;
- supported platforms/version/status.

Do not put temporary experiment progress or handoff notes back into the living documentation set. Use issues, branches, benchmark artifacts, or ADRs for that history.
