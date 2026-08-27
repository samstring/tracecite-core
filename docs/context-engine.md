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

## 4. Delta and gain-aware transport semantics

For each search Result the delta projection records:

- context schema/id/revision;
- number of newly returned Evidence items;
- number of repeated citable Evidence items omitted from this turn;
- number of unidentified Evidence items that could not be safely deduplicated;
- bounded seen-state size and pruning status.

A repeated Result may therefore have `outcome=supported` with an empty Agent-facing Evidence delta. This does not mean the canonical Result contains no Evidence; it means the cited Evidence has already been delivered to this Agent context. The Ledger `result_id` remains the recovery path.

Seen-state always advances after a valid projection, but the delta is shown only when it is strictly smaller than the ordinary Agent view in the **final selected transport**. Columnar JSON is compared as compact JSON; TCF `frame` is compared after frame rendering. If delta metadata would cost more than the Evidence it removes, the Agent receives the ordinary view while the private seen-state still advances.

This makes Context optimization monotonic with respect to model-visible transport size: enabling Context must not make a compatible turn larger merely to announce a tiny omission.

## 5. CLI and transport selection

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

A text-frame-capable host may use the more compact TCF transport:

```bash
tracecite search app.log "timeout" --snapshot \
  --agent-profile frame \
  --ledger-dir /tmp/tracecite-ledger \
  --context-id incident-42
```

Capability-based `auto` selection prefers `frame` only when the host explicitly declares `stateful_history`, `batch_expand`, and `text_frame`; otherwise it falls back to `stateful-index` for capable stateful JSON hosts, then to the normal Agent JSON profile. A host that does not declare `text_frame` never receives TCF unexpectedly.

Recover immutable evidence from a stored canonical Result:

```bash
tracecite expand-many /tmp/tracecite-ledger RESULT_ID '#L120' '#L188-L190'
```

`--context-id` without `--ledger-dir` fails with a machine-readable error. Existing Evidence/line/output budgets apply to both the ordinary and delta projections before the smaller final transport is selected.

## 6. MCP and other hosts

A stateful host may map its conversation, investigation, task, or another stable host-owned identifier to the Context Engine. The identifier represents transport memory only. It must not be treated as user identity, Evidence, or authorization.

TraceCite MCP uses optional `context_id` on `tracecite_search`. It stores state below the server-owned `TRACECITE_MCP_STATE_DIR` and exposes `tracecite_expand_many` for recovery. Models cannot choose the server state root.

MCP or another structured host should not claim `text_frame` merely because frame is smaller. The host must explicitly support parsing/forwarding TCF. JSON remains the safe fallback.

## 7. Public transport evidence

The public benchmark under `benchmarks/agent-investigation/` currently exercises a 14.5 MB Kubernetes kubelet log and an 84 KB real Flutter/iOS crash report. Fixed-query smoke tests show that frame materially reduces TraceCite encoding overhead and that frame + Context preserves newly introduced Evidence while suppressing already-seen Evidence.

Those tests measure transport characters, not complete Agent reasoning or provider token usage. They must not be presented as proof that TraceCite beats `rg` in total investigation tokens. The model-level benchmark scorer and host protocol exist for that separate claim.

## 8. What Context Engine does not do

The current implementation does not:

- change canonical Result schemas or EvidencePointer semantics;
- infer semantic relevance or root cause;
- treat previous Agent conclusions as Evidence;
- merge InvestigationState with transport state;
- automatically promote Knowledge;
- perform fuzzy/embedding deduplication;
- select representative Evidence groups.

Representative grouping and richer context budgeting can be added later at the Runtime/Integration layer without changing Extension Protocol v2.

## 9. Trust invariant

> Saving tokens must never make missing, truncated, approximate, or unrecoverable evidence look complete.

Context Delta therefore keeps canonical Results recoverable and exposes the fact that evidence was omitted because it was previously seen. Domain Extensions remain unaware of Agent transport state.
