# TraceCite architecture

[简体中文](architecture.zh-CN.md)

Status: **Normative / Current** for the `feature_for_agent_refacotr_shell` refactor, official extensions, and Pi / Codex / Cursor / CLI / MCP / custom hosts.

> **The Agent thinks and decides; TraceCite owns evidence.**

This is the top-level living architecture contract. Long-lived decisions and transitions are recorded in ADRs/migrations. The Evidence Shell / SourceVersion refactor is defined by `docs/adr/0002-agent-evidence-shell-source-version.md`.

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
- a stable SourceVersion / SessionSourceView for one RetrievalSession;
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
4. One RetrievalSession binds one stable SourceVersion per logical source; the same session must not silently switch to newer mutable/live bytes when the original path changes.
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

## 4. SourceVersion / SessionSourceView

`SourceVersion` identifies the immutable bytes actually observed by an investigation rather than a pathname that may continue changing.

The first time one RetrievalSession accesses a logical source, Runtime resolves and binds one `SessionSourceView`. All later search/run/materialize/replay operations in that same session reuse the exact version even if the original mutable/live path changes. A conversation that keeps one RetrievalSession therefore keeps one stable evidence world for that source.

A new RetrievalSession checks the current source fingerprint only on its first access. If the fingerprint matches the latest already verified version, the new session reuses the prior snapshot/path, SHA, and line metadata. A new SourceVersion is created only when the source actually changed.

### Static sources

A source declared immutable does not require a physical copy. The original file may be the immutable source; SHA is established once and cached while the fingerprint remains unchanged.

### Potentially mutable files

On the first access from a new RetrievalSession, a cheap fingerprint decides whether an already verified version can be reused:

```text
device / file-id
inode when available
size
mtime_ns
ctime_ns
```

Unchanged fingerprint -> reuse the prior snapshot/path, SHA, and line metadata without another copy, full hash, or line recount.

Changed fingerprint -> establish a new SourceVersion. Snapshot copying calculates SHA and line count in the same sequential read. The fingerprint is only a cheap reuse key; final Evidence identity still depends on immutable bytes + SHA/version.

### Live sources

Large live sources use cooperative `live_cut` + immutable segments instead of repeatedly copying or cutting the same accumulated file within one long conversation.

```text
writer -> live.log
session first access -> live cut -> immutable segment N
writer continues -> new live.log
same session -> keep using bound immutable view
new session -> capture newer live bytes if source changed
```

Historical segments are not recopied or rehashed. The logical SourceVersion is an ordered immutable-segment manifest; each EvidencePointer still binds to an exact segment SHA and segment-local line range.

If the writer does not cooperate, the current fallback mechanically verifies append continuity at the previous capture boundary and copies only newly appended complete bytes into a new immutable segment. If continuity cannot be proven, TraceCite establishes a new immutable capture instead of treating unknown changes as append-only.

`SessionSourceView` / `SessionSourceVersionStore` are the canonical public names. The internal historical `QuestionSourceView` / `question_id` names remain compatibility aliases/fields until the persisted implementation is migrated; they do not change the session-bound semantics.

## 5. Evidence Shell / `tracecite_run`

Evidence Shell is the unified Agent-facing mechanical search-program surface. The Agent composes the program; TraceCite deterministically executes it against the current SourceVersion.

Example:

```text
search '"statusCode":500'
| search 'ts-route-service'
| where latency >= 1000
```

The implemented mechanical command surface includes:

- `all`;
- literal `search`;
- grep-like fixed/regex/invert/case-insensitive search;
- safe `regex`;
- `exclude` / `exclude-regex`;
- structured `where` comparison / contains / startswith / endswith / matches;
- `exists` / `missing`;
- `lines`;
- Host/tool-level `last` / `since` / `until` / `segmenter` scope;
- `sort` / `reverse`;
- `take` / `head` / `first` / `last` / `tail`;
- `near` / `seek`;
- `count` / `group` / `distinct` / `uniq`;
- `emit`.

Evidence Shell is not unrestricted host bash. It may read only authorized SourceVersions and TraceCite evidence/search primitives; it must not use the network, arbitrary filesystem access, shell escape, Evidence mutation, or policy bypass.

The desired small Agent-facing tool surface is:

```text
tracecite_describe
tracecite_run
tracecite_materialize
```

Existing `retrieve/search/aggregate/...` surfaces may remain canonical/compatibility entry points. Text `QueryTarget` retrieval already reduces to the Evidence Shell contract. Multi-step mechanical investigation should prefer one `tracecite_run` so intermediate outputs do not repeatedly enter model context.

## 6. Search -> Segment -> Complete Records

Ordinary Evidence Shell search prefers this order:

```text
Raw immutable SourceVersion
   -> raw physical-line candidate search
   -> candidate locator
   -> Segmenter local recovery
   -> Complete logical Record
   -> additional shell stages
   -> Evidence Budget Gate
```

A physical grep line is not final Evidence, especially for multiline log/trace formats.

For locally recoverable JsonLine, single-line RawText, FormatSegmenter records, and literal multiline FormatSegmenter records, Runtime searches raw hits first and restores only candidate Records. There is no hidden candidate-count limit.

If regex semantics may span multiple physical lines, continuation state cannot be locally proven, or time/range/pid scope requires full record semantics, Runtime may fall back to full logical-record iteration to preserve correctness.

The Agent Shell hot path no longer depends on `search_text` and does not require `matched_records.jsonl`, `hits.jsonl`, `evidence.log`, filter history, or unmatched-token summaries.

## 7. Evidence Budget Contract

Maximum Evidence transport is configured only by the user/Host, for example:

```text
max_evidence_tokens
max_evidence_bytes  # hard safety cap
```

The Agent tool schema must **not** expose parameters that allow the Agent to increase those values. Materialize/replay transport is also capped by Host/User Evidence policy rather than an Agent-controlled larger value.

If the complete matched records exceed the budget:

```text
status = too_broad
reason = MATCHED_EVIDENCE_BUDGET_EXCEEDED
refine_query = true
evidence = []
```

The Runtime may report `observed_at_least_tokens/bytes`; if it stops early after proving the bound was exceeded, it must not fabricate an exact total.

If an aggregate result itself is too large to transport, Runtime returns `AGGREGATE_OUTPUT_BUDGET_EXCEEDED` instead of dumping a large group/distinct result.

After `too_broad`, the Agent may refine literals/regexes, add search/filter/where predicates, narrow time/range/source scope, use aggregation, use near/seek around an already meaningful anchor, or otherwise choose a more selective search. It may not raise/bypass the budget, request all locators, or treat arbitrary first-N output as complete.

Explicit `first/last/head/tail/take` remains valid when subset semantics are intentionally requested; it must be marked as selection rather than completeness.

## 8. Internal MatchSet / intermediate state

`MatchSet` is an internal Runtime implementation concept, not a required public Agent object. It may be an iterator, locator array, bitmap, range set, spill file, or backend handle.

Large intermediate sets stay inside Runtime:

```text
173,320 -> 4,901 -> 331 -> 5
```

Only the final compact result crosses the model boundary. The current all-or-refine shell does not require a public ResultHandle. If real cross-call workflows later require persistent large-set reuse, a stable handle may be introduced, but it must bind SourceVersion + QueryPlan identity and never retransmit the full set.

## 9. Canonical Evidence API

The long-term canonical mechanical primitives remain:

- `retrieve`: caller-selected source/scope/predicate -> Evidence + Coverage + Provenance + novelty/repetition; text QueryTarget reduces to Evidence Shell;
- `materialize`: exact caller-selected immutable source/version range/ref;
- `replay`: deliberate reread of old immutable Evidence; novelty remains zero;
- `aggregate`: compatibility deterministic count/distinct/group; Agent text investigation should prefer Shell aggregates;
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

One RetrievalSession/context always reuses the SourceVersion first bound for a given logical source. The Host does not need to identify every user-message boundary. If one conversation maps to one RetrievalSession, the entire conversation keeps the same SourceVersion. Only a new RetrievalSession, or a future explicit refresh-source operation, may establish a newer version; silent refresh is forbidden.

## 11. Materialize / provenance / citation

Search candidates and final Evidence are separate. Exact context is materialized only when a sufficiently small candidate set needs to be read/reasoned over/cited.

Final Evidence must resolve to:

```text
source/version identity
segment/file SHA when applicable
exact line/range or equivalent locator
exact raw content
```

Once a TraceCite-managed immutable SourceVersion/segment has a SHA, Shell EvidencePointer creation, managed materialize, and replay reuse it instead of hashing the full file again. SourceVersionStore preserves both latest source state and session-bound historical views so an older immutable segment remains replayable after a newer SourceVersion is established.

A pathname that TraceCite has not frozen and that external processes may mutate still requires integrity revalidation.

## 12. Agent / Host boundary

The Host owns model/tool/context/wall-time budgets, Evidence token/byte policy, source mode, RetrievalSession/conversation identity, tool exposure, prompt, and native-tool telemetry.

The Host does not create a new SourceVersion for every user message. As long as one conversation keeps the same RetrievalSession/context, TraceCite keeps reusing its source binding. When a new conversation uses a new RetrievalSession, Runtime checks the fingerprint on first access and may reuse the existing snapshot + SHA when the original source is unchanged.

The Agent skill must teach: prefer `tracecite_run` for combined mechanical search; refine on `too_broad`; never increase user Evidence budget; do not request complete locator dumps; materialize using the returned immutable `source_path + SHA + range` only when exact evidence is needed.

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
| RetrievalSession seen/repeated/range/replay | Implemented | existing Runtime + Shell admission |
| Raw-hit candidate-first + local complete-record recovery | Implemented | `record_search.py` + `candidate_recovery.py` |
| `EvidenceShellPolicy` user/host-owned budget | Implemented | Agent request has no budget override; Pi materialize/replay also use Host budget |
| `tracecite_run` Evidence Shell | Implemented | literal/grep/regex/where/filter/sort/selection/near/seek/count/group/distinct |
| `too_broad` canonical transport status | Implemented | over-budget result exposes no Evidence body/locator dump |
| Artifact-free Agent search hot path | Implemented | no matched-record/hit/evidence-log/filter-history dependency |
| Remove high-cardinality EvidenceIndex from Agent QueryTarget | Implemented | text retrieve/search reduces to Evidence Shell |
| Session-level SourceVersion binding | Implemented | same RetrievalSession/source keeps one version; `SessionSourceView` is the canonical public name |
| Mutable fingerprint snapshot reuse | Implemented | new-session first access: unchanged -> reuse snapshot + SHA + line metadata |
| Snapshot SHA/count single pass | Implemented | copy + hash + newline count in one sequential read; no snapshot/original double count |
| LiveCut + immutable-segment SourceVersion | Implemented | freeze on one session's first access; a new session may capture newer live bytes |
| Managed materialize/replay SHA reuse | Implemented | exact range reads on immutable managed source without whole-file rehash |
| Agent skill for shell/refinement | Implemented | `.agents/skills/tracecite-investigate/SKILL.md` |
| Pi `tracecite_run` adapter | Implemented | budget/source policy comes from Host environment/product configuration |
| Public ResultHandle/MatchSet API | Deferred | current all-or-refine contract does not require a public API |
| Full regression + Native/TraceCite benchmark validation | Pending validation | run after implementation completion; not an architecture implementation gap |

## 16. Documentation / governance

Architecture-boundary changes must update both `architecture.md` and `architecture.zh-CN.md`. Incompatible architectural changes require an ADR; public schema/API changes require a migration note and tests.

Current design ADR: [ADR-0002](adr/0002-agent-evidence-shell-source-version.md).