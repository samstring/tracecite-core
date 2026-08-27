# TraceCite Context Engine

Status: implemented Agent transport capability  
Scope: `tracecite.integrations`, CLI adapters, MCP/other stateful Agent hosts

The Context Engine reduces repeated Agent-tool payload while preserving TraceCite's evidence and trust invariants. It is not a domain extension API, not an InvestigationState replacement, and not a cache of model conclusions.

## 1. Boundary

```text
Canonical Runtime Result
        |
        +----> Evidence Ledger (complete, content-addressed)
        |
        v
Context Engine
seen Evidence identities per Agent context
        |
        v
Agent-facing Context Delta
```

The canonical Result is produced first. When a Ledger is configured, the complete canonical search Result is stored before any Context Delta projection. Context processing only changes what the Agent host receives on that turn.

## 2. Evidence identity

The first implementation deduplicates citable search Evidence by immutable Evidence URI. If an Evidence item has no URI, the engine keeps returning it rather than guessing an identity and silently dropping data.

The engine does not deduplicate by label, text similarity, line content, domain event type, or model judgment.

## 3. Context state

Each context has independent bounded transport state:

```json
{
  "schema_version": 1,
  "context_id": "incident-42",
  "revision": 3,
  "seen_evidence": ["evidence://sha256/...#L120"],
  "seen_results": ["<sha256-result-id>"]
}
```

Default bounds are 4096 Evidence identities and 512 Result IDs. When a bound is exceeded, the oldest transport memory is pruned and `state_pruned` / `context_state_pruned` metadata is exposed. Pruning may cause old Evidence to be shown again; it never causes unseen Evidence to be hidden.

Context state is atomically persisted. Context IDs are restricted to a safe identifier form and cannot perform path traversal.

## 4. Delta semantics

For each search Result the Agent-facing projection reports:

- context schema/id/revision;
- number of newly returned Evidence items;
- number of repeated citable Evidence items omitted from this turn;
- number of unidentified Evidence items that could not be safely deduplicated;
- bounded seen-state size and pruning status.

A repeated Result may therefore have `outcome=supported` with an empty Agent-facing Evidence delta. This does not mean the canonical Result contains no Evidence; it means the cited Evidence has already been delivered to this Agent context. The Ledger `result_id` remains the recovery path.

## 5. CLI

The normal CLI path is unchanged when no context ID is supplied.

```bash
tracecite search app.log "timeout" --snapshot
```

Stateful delta transport is explicit and requires a Ledger:

```bash
tracecite search app.log "timeout" --snapshot \
  --agent-profile stateful-index \
  --ledger-dir /tmp/tracecite-ledger \
  --context-id incident-42
```

Recover immutable evidence from a stored canonical Result:

```bash
tracecite expand-many /tmp/tracecite-ledger RESULT_ID '#L120' '#L188-L190'
```

`--context-id` without `--ledger-dir` fails with a machine-readable error. Context delta is applied before the existing compact transport projection so existing token budgets still apply to the smaller delta.

## 6. MCP and other hosts

A stateful host may map its conversation, investigation, task, or another stable host-owned identifier to the Context Engine. The identifier represents transport memory only. It must not be treated as user identity, Evidence, or authorization.

TraceCite MCP uses optional `context_id` on `tracecite_search`. It stores state below the server-owned `TRACECITE_MCP_STATE_DIR` and exposes `tracecite_expand_many` for recovery. Models cannot choose the server state root.

## 7. What Context Engine does not do

The current implementation does not:

- change canonical Result schemas or EvidencePointer semantics;
- infer semantic relevance or root cause;
- treat previous Agent conclusions as Evidence;
- merge InvestigationState with transport state;
- automatically promote Knowledge;
- perform fuzzy/embedding deduplication;
- select representative Evidence groups.

Representative grouping and richer context budgeting can be added later at the Runtime/Integration layer without changing Extension Protocol v2.

## 8. Trust invariant

> Saving tokens must never make missing, truncated, approximate, or unrecoverable evidence look complete.

Context Delta therefore keeps canonical Results recoverable and exposes the fact that evidence was omitted because it was previously seen. Domain Extensions remain unaware of Agent transport state.
