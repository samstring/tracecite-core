# TraceCite architecture

[简体中文](architecture.zh-CN.md)

Status: **Normative / Current** for the `feature_for_agent_refacotr_shell` refactor, official extensions, and Pi / Codex / Cursor / CLI / MCP / custom hosts.

> **The Agent thinks and decides; TraceCite owns evidence.**

This is the top-level living architecture contract. Long-lived decisions and transitions are recorded in ADRs/migrations. The Evidence Shell / SourceVersion refactor is defined by `docs/adr/0002-agent-evidence-shell-source-version.zh-CN.md`.

## 1. Product boundary

The Agent owns:

- problem/scope interpretation;
- hypotheses and investigation direction;
- the search expression / Evidence Shell program;
- causal reasoning and competing explanations;
- evidence sufficiency;
- final answer, qualification, and stop decision.

TraceCite owns deterministic evidence mechanics:

- source/version and evidence identity;
- acquisition, snapshot/freeze, provenance, Coverage, and integrity;
- a stable SourceVersion / QuestionSourceView for one user question;
- RetrievalSession seen/repeated/covered-range memory;
- mechanical Evidence Shell execution and intermediate-result isolation;
- enforcement of user-configured Evidence transport budgets;
- exact materialization and explicit replay;
- deterministic aggregation and caller-scoped traversal;
- optional InvestigationState coordination metadata;
- extension/trust contracts.

TraceCite Runtime must not expose `root_cause_confidence`, `evidence_sufficient`, `next_best_query`, or `stop_recommended` as runtime truth.

## 2. Architecture invariants

1. Core is generic/deterministic and contains no device/product/company/application/domain knowledge.
2. Core does not import Runtime or concrete domain packages; Runtime may depend on Core.
3. Extensions depend only on public TraceCite contracts and contribute domain facts/capabilities, not Agent reasoning policy.
4. One user question is bound to one stable SourceVersion; an investigation must not silently switch to newer live bytes.
5. A search hit is not Evidence; the Segmenter first restores the complete logical record.
6. Evidence transport token/byte budgets are **User/Host Policy**. The Agent cannot raise, bypass, or dynamically override them.
7. An ordinary Evidence Shell search either fits the complete matched-record payload inside the configured budget or returns `too_broad`; first-N must not masquerade as completeness.
8. Oversized match sets must never enter model context through complete locator/EvidenceIndex dumps.
9. Shell intermediate data and internal MatchSets stay outside the model boundary; only final compact results and explicit materialized Evidence cross it.
10. Canonical Evidence/Result remains provenance-preserving and recoverable.
11. `status` (execution/transport) and epistemic `outcome` remain separate. `too_broad` is a transport fact, not an epistemic conclusion.
12. Zero matches, incomplete Coverage, missing evidence, source changes, and provider failure do not prove real-world absence.
13. RetrievalSession owns only mechanical evidence-session memory; never hypotheses/root cause/sufficiency/stopping.
14. SHA is established once per TraceCite-managed immutable SourceVersion/segment and then reused.
15. Efficiency is accepted only after correctness/support/provenance/recoverability remain acceptable.

## 3. Logical architecture

```text
                                  Domain Extensions
                              Mobile / CI / third-party
                                        |
                                        v
Raw Sources -> SourceVersion -> Evidence Runtime -> Integrations -> Agent Host
               |               |                  |              |
               |               |                  |              +-- Pi
               |               |                  |              +-- Codex
               |               |                  |              +-- Cursor
               |               |                  |              +-- MCP/custom
               |               |                  |
               |               |                  +-- compact projection / Context
               |               |
               |               +-- Evidence Shell / QueryPlan
               |               +-- internal MatchSet / intermediate rows
               |               +-- user Evidence budget gate
               |               +-- RetrievalSession
               |               +-- materialize / replay / aggregate / traverse
               |
               +-- immutable file / snapshot / live segments
               +-- SHA / manifest / line metadata / provenance

Agent owns: query program -> hypothesis -> causal reasoning -> sufficiency -> answer -> stop
```

## 4. SourceVersion / QuestionSourceView

`SourceVersion` identifies the immutable bytes actually observed by an investigation rather than a pathname that may continue changing.

At the start of one user question, the Host/Runtime resolves one `QuestionSourceView`; all search/run/materialize/replay operations in that investigation reuse it.

### Static sources

A source declared immutable does not require a physical copy. The original file may be the immutable source; SHA is established once and cached.

### Potentially mutable files

At a later user question, a cheap fingerprint first decides whether an already verified version can be reused:

```text
device / file-id
inode when available
size
mtime_ns
optional ctime/provider revision
```

Unchanged fingerprint -> reuse prior snapshot/path, SHA, line/index metadata.

Changed fingerprint -> establish a new SourceVersion. The fingerprint is only a cheap reuse key; final Evidence identity still depends on immutable bytes + SHA/version.

### Live sources

Large live sources should use cooperative `live_cut` + immutable segments rather than copying the full accumulated file for every question.

```text
writer -> live.log
question boundary -> live cut -> immutable segment N
writer continues -> new live.log
```

Historical segments are not recopied or rehashed. A logical SourceVersion may be a manifest of immutable segments.

Fallback order when cooperative cut is unavailable: CoW clone/reflink -> a bounded byte view for a provably append-only source -> full-copy snapshot.

## 5. Evidence Shell / `tracecite_run`

Evidence Shell is the unified Agent-facing mechanical search-program surface. The Agent composes the program; TraceCite deterministically executes it against the current SourceVersion.

Example:

```text
search '"statusCode":500'
| search 'ts-route-service'
| where latency >= 1000
```

Capability families include:

- literal / grep-like search;
- regex;
- time/range/source scope;
- structured-field predicates;
- filter/exclude;
- aggregate/count/group/distinct;
- sort/top/take/first/last;
- seek/near/range navigation;
- generic search backends registered later through capability plumbing.

Evidence Shell is not unrestricted host bash by default. It may read only authorized SourceVersions and registered evidence/search primitives; it must not use the network, arbitrary filesystem access, shell escape, Evidence mutation, or policy bypass.

The desired small Agent-facing tool surface is:

```text
tracecite_describe
tracecite_run
tracecite_materialize
```

Existing `retrieve/search/aggregate/...` surfaces may remain canonical/compatibility entry points, but multi-step mechanical investigation should prefer one `tracecite_run` so intermediate tool outputs do not repeatedly enter model context.

## 6. Search -> Segment -> Complete Records

The first shell stage yields raw hit locators. The Segmenter defines complete logical-record boundaries.

```text
Raw SourceVersion
   -> search hits
   -> Segmenter
   -> Complete Records
   -> Evidence Budget Gate
```

A physical grep line is not final Evidence, especially for multiline log/trace formats.

During migration, the shell may reuse legacy `search_text` to preserve regex/time/fold/segmenter semantics. The target Agent hot path streams Records directly and no longer requires `matched_records.jsonl`, `hits.jsonl`, `evidence.log`, or filter history.

## 7. Evidence Budget Contract

Maximum Evidence transport is configured only by the user/Host, for example:

```text
max_evidence_tokens
max_evidence_bytes  # hard safety cap
```

The Agent tool schema must **not** expose parameters that allow the Agent to increase those values.

If the complete matched records exceed the budget:

```text
status = too_broad
reason = MATCHED_EVIDENCE_BUDGET_EXCEEDED
refine_query = true
evidence = []
```

The Runtime may report `observed_at_least_tokens/bytes`; if it stops early after proving the bound was exceeded, it must not fabricate an exact total.

After `too_broad`, the Agent may refine literals/regexes, add predicates, narrow time/range/source scope, use aggregation, or otherwise choose a more selective search. It may not raise/bypass the budget, request all locators, or treat arbitrary first-N output as complete.

Explicit `first/last/top/take/sample` remains valid when the user actually requests selection semantics; it must be marked as selection rather than completeness.

## 8. Internal MatchSet / intermediate state

`MatchSet` is an internal Runtime implementation concept; the Agent does not need to understand it. It may be a locator array, bitmap, range set, lazy iterator, spill file, or backend handle.

Large intermediate sets stay inside Runtime:

```text
173,320 -> 4,901 -> 331 -> 5
```

Only the final compact result crosses the model boundary. If a large set must survive across tool calls, a stable `result_handle` may reference it; the handle must bind SourceVersion and QueryPlan identity rather than retransmitting the full set.

## 9. Canonical Evidence API

The long-term canonical mechanical primitives remain:

- `retrieve`: caller-selected source/scope/predicate -> Evidence + Coverage + Provenance + novelty/repetition;
- `materialize`: exact caller-selected immutable source/version range/ref;
- `replay`: deliberate reread of old immutable Evidence; novelty remains zero;
- `aggregate`: deterministic caller-selected count/distinct/group;
- `traverse`: deterministic traversal under caller-selected seed/scope/direction/limits;
- `verify`: integrity/source-version/Manifest/exact-Evidence verification.

`tracecite_run` is the Agent program surface for composing search/mechanical operations; it does not create a second Evidence identity or session model.

## 10. RetrievalSession: single mechanical Evidence-memory owner

RetrievalSession owns seen Evidence identities, covered immutable ranges, source observations/generations, recent operations, request fingerprints, and repeated/replay facts.

Required repeated-Evidence behavior:

```text
query A -> body E
query B -> same E again

new_evidence = 0
repeated_evidence > 0
matched_existing_evidence = [E ref]
```

A `too_broad` search has not admitted Evidence to the Agent; internally scanned rows therefore must not be added to `seen_evidence` or Coverage.

## 11. Materialize / provenance / citation

Search candidates and final Evidence are separate. Exact context is materialized only when a sufficiently small candidate set needs to be read/reasoned over/cited.

Final Evidence must resolve to:

```text
source/version identity
segment/file SHA when applicable
exact line/range or equivalent locator
exact raw content
```

Once a TraceCite-managed immutable SourceVersion already has a SHA, downstream search/materialize/bridge operations should reuse it instead of hashing the full file again. A pathname that TraceCite has not frozen and that external processes may mutate still requires integrity revalidation.

## 12. Agent / Host boundary

The Host owns model/tool/context/wall-time budgets, Evidence token policy, tool exposure, prompt, and native-tool telemetry.

The Agent skill must teach: prefer `tracecite_run` for combined mechanical search; refine on `too_broad`; never increase user Evidence budget; do not request complete locator dumps; materialize only when exact evidence is needed.

Repository Agent instruction source: `.agents/skills/tracecite-investigate/SKILL.md`.

## 13. Context, correctness, benchmark validity

TraceCite's token objective is not to compress a giant payload after it has already been prepared for the Agent. Low-value intermediate large results should never cross the model boundary in the first place.

Efficiency is evaluated only after correctness/support/provenance/recoverability gates. Formal Agent benchmarks separate `task_result` from `run_validity`; provider 429/quota/outage/harness failure is infrastructure-invalid.

## 14. Dependency direction

```text
tracecite_core
     ^
     |
tracecite.runtime
     ^
     |
+----+------------------+
|                       |
tracecite.extension   tracecite.integrations
|                       |
Domain Extensions     CLI / Pi / Codex / Cursor / MCP/custom
```

No domain package may become a required dependency of Core or Runtime.

## 15. Implementation status

| Capability | Status | Current refactor branch |
|---|---|---|
| Existing SourceVersion identity (`sha256/cursor/generation/mutable`) | Implemented | `evidence_identity.py` |
| RetrievalSession seen/repeated/range/replay | Implemented | existing Runtime |
| Candidate-first literal scanner/local recovery | Implemented | existing Runtime internal |
| `EvidenceShellPolicy` user/host-owned budget | First version implemented | Agent request has no budget override |
| `tracecite_run` Evidence Shell | First version implemented | literal/regex/filter/where/count/group/distinct/explicit selection; expanding toward all existing search capabilities |
| `too_broad` canonical transport status | First version implemented | over-budget result exposes no Evidence body/locator dump |
| Pi `tracecite_run` adapter | First version implemented | budget comes from Host environment/product configuration |
| Agent skill for shell/refinement | Updated | `.agents/skills/tracecite-investigate/SKILL.md` |
| Remove `matched_records.jsonl` / legacy artifacts from Agent search hot path | In progress | shell first stage temporarily reuses `search_text` for semantic compatibility |
| Remove high-cardinality EvidenceIndex from Agent query path | In progress | new shell does not build EvidenceIndex; legacy retrieve compatibility remains to migrate |
| Question-level SourceVersion cache / fingerprint reuse | Planned | architecture/ADR fixed; implementation pending |
| LiveCut + immutable-segment SourceVersion | Planned for Agent Runtime | Core already contains `live_cut.py` / `segment_store.py` foundations |
| SHA/count full-file pass consolidation/caching | Planned | bridge now prefers `data.source_sha256`; full SourceVersion cache pending |

## 16. Documentation / governance

Architecture-boundary changes must update both `architecture.md` and `architecture.zh-CN.md`. Incompatible architectural changes require an ADR; public schema/API changes require a migration note and tests.

Current design ADR: [ADR-0002](adr/0002-agent-evidence-shell-source-version.zh-CN.md).
