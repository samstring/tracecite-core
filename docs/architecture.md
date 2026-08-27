# TraceCite Architecture

Status: normative  
Scope: the TraceCite distribution, official domain extensions, and Agent/CLI/MCP host adapters

This document is the top-level architecture contract. Agent integration, extension, knowledge-governance, and validation documents must preserve its boundaries. Planned capabilities are explicitly distinguished from implemented behavior.

## 1. Product definition

TraceCite is an **evidence-driven investigation framework for external agents**:

- The Agent understands the problem, explores freely, forms hypotheses, selects tests, and interprets results.
- TraceCite records investigation state, performs deterministic data operations, enforces budgets, produces traceable evidence, and governs the knowledge lifecycle.
- Domain extensions provide Mobile, CI, backend, database, and other adapters and semantics.

The governing principle is:

> Constrain conclusions, not exploration.

TraceCite is neither an embedded autonomous LLM agent nor a mandatory command funnel for every investigation.

## 2. Architectural invariants

1. Core provides generic, deterministic, reproducible evidence mechanics and contains no device, product, company, application, or business knowledge.
2. Agents may choose any safe exploration strategy. A final Finding must identify its Hypothesis, Evidence, Coverage, limitations, and stop reason.
3. `status` is execution state; `outcome` is epistemic state. They remain separate.
4. Zero matches, incomplete coverage, missing evidence, and execution failures do not prove absence; they default to `unknown`.
5. Citable Evidence points to an immutable snapshot and line range, or to an integrity-verified Manifest.
6. Agent conclusions cannot promote themselves to trusted Knowledge or independently verify themselves.
7. Extensions provide capabilities and semantics; Runtime retains execution, budget, evidence, verification, safety, and stopping control.
8. Core never imports Runtime or domains; Runtime never imports a concrete domain. Domain packages depend only on public TraceCite APIs.
9. Bounded, sampled, approximate, or truncated results expose Coverage explicitly.
10. A new main-package capability should serve at least two domains; otherwise it remains in a domain extension.

## 3. Logical architecture

```text
User problem
    |
Agent Host
understanding, reasoning, decisions, user interaction
    |
Investigation Runtime  <---->  Knowledge Registry
state, budgets, relations          proposals, review, versions, expiry
    |
Evidence Core
Source, Segmenter, Sample, Survey, Filter, Snapshot, Evidence, Manifest, Verify
    |
Evidence Store
frozen inputs, filtered artifacts, events, reports, manifests

Domain Extensions register Source, Segmenter, Preprocessor, Event Transformer,
Assertion, Reporter, Preset, and Scenario Runtime capabilities through public contracts.
```

### Agent Host

Turns a natural-language request into a Problem and Scope; chooses direct reading, sampling, survey, search, Scenario, or domain tools; creates falsifiable Hypotheses and Tests; and retains `unknown` when evidence is insufficient. Agent reasoning is not independent evidence.

### Investigation Runtime

Relates tool calls to the Problem, Hypotheses, and Tests while enforcing budget, safety, and stopping policy. The Runtime now provides a versioned first-class `InvestigationState`; tool calls remain independently callable and opt into bounded execution recording when given an investigation path.

### Evidence Core

`tracecite_core` is the standard-library-only stable kernel for resolving and freezing inputs, streaming segmentation, sampling/survey/filter operations, hash-addressed evidence, run artifacts, manifests, and integrity verification. It does not understand domain concepts or diagnose causes.

### Knowledge Registry

Manages proposals, independent-case verification, review, promotion, versioning, and expiry. See [Knowledge governance](knowledge-governance.md). Trusted Knowledge may recommend future Hypotheses, Tests, Presets, or Scenarios; it never replaces current Evidence.

### Domain Extensions

Contain domain data and semantics. Mobile is an extension, not a Core special case. The same contracts support CI, backend, network, database, and security investigations. See the [Extension contract](extension-contract.md).

## 4. Investigation model

| Concept | Meaning | Required relation |
|---|---|---|
| Problem | The user's actual question, not necessarily a query string | Scope |
| Scope | Sources, subjects, time, authorization, and budgets | Problem |
| Observation | A fact without causal interpretation | source or Evidence |
| Hypothesis | A falsifiable proposition | Problem |
| Test | A plan to evaluate one Hypothesis | Hypothesis |
| Strategy | How a Test is executed | Test |
| Evidence | Reviewable, addressable support | Test, source, digest |
| Coverage | Scope, omissions, sampling, approximation, and truncation | Test or Evidence |
| Finding | `supported`, `contradicted`, or `unknown` for a Hypothesis | Evidence, Coverage |
| Knowledge Candidate | A reusable proposal derived from a Finding | Investigation, Evidence |
| Knowledge | Independently verified, reviewed, versioned guidance | Candidate, review |

An Observation such as “HTTP 504 occurred at 10:30:04” must remain distinct from the causal Hypothesis “HTTP 504 caused the blank screen.”

## 5. General investigation protocol

The protocol defines required questions and artifacts, not a fixed command sequence:

```text
Problem + Scope
      -> Orient / Explore
      -> Hypothesis
      -> Test
      -> Evidence + Coverage
      -> Finding
      -> Stop reason
      -> optional Knowledge Candidate -> Review -> Knowledge
```

A deliverable investigation must:

1. Define the Problem and Scope, including sources, time, authorization, budgets, and stop conditions.
2. State at least one falsifiable Hypothesis. A user description is an investigation target, not automatically a log query or conclusion.
3. Define at least one Test, including expected and contradicting observations and its Strategy.
4. Inspect supporting and contradicting Evidence together with Coverage, parsing gaps, approximation, and truncation.
5. Produce a scoped Finding of `supported`, `contradicted`, or `unknown`.
6. Record why work stopped: resolved, evidence exhausted, budget reached, new authorization needed, or input missing.

Orient and Explore are required cognitive activities but do not mandate a TraceCite command. An Agent may read a small immutable input directly; large or unfamiliar inputs should use bounded tools.

### Conditional strategies

| Strategy | Use when |
|---|---|
| `probe` | Multiple/large inputs or unknown format/time coverage |
| `sample/peek` | Raw context is useful without frequency bias; optional bounded observation |
| `survey` | Input is unfamiliar and no defensible first query exists |
| `search` / `grep` | A Test has an ad-hoc literal or regex predicate |
| `preset` | A versioned reusable filter exists |
| `expand` | A pointer needs bounded context |
| Scenario | Reproduction, assertions, regression, or deliverables are needed |
| `verify` | A final result relies on a Scenario manifest |

Adaptive routing:

```text
small, static input       -> direct exploration -> freeze final evidence as needed
clear technical anchor   -> Hypothesis -> search/domain tool -> expand
large/unfamiliar input   -> probe -> optional sample/survey -> competing Hypotheses -> separate Tests
```

Survey produces bounded descriptive Observations, never a root-cause decision.

`sample`/`peek` is an optional free-observation strategy when raw context is
useful or a frequency-oriented survey could bias the first view.  It is not a
mandatory funnel stage.  Core sampling defaults to an immutable snapshot and
returns SHA-256 plus line-addressable pointers through Runtime; `head-tail`
and deterministic `uniform` selection are bounded by hard record and
character caps.  Time scopes (`last`, `since`, `until`) and segmenter
compatibility are reported in Coverage.  Any scope exclusion, sampling
omission, character clipping, or withheld item is explicit, and the result
always uses `outcome=not_assessed`.

## 6. Strategy, Preset, Scenario, and Knowledge

```text
Hypothesis
└── Test
    └── Strategy
        ├── direct read / sample / survey
        ├── grep: ad-hoc query
        ├── preset: versioned filter component
        ├── extension tool: domain data operation
        └── Scenario: reproducible end-to-end test recipe

Knowledge recommends Hypotheses, Tests, Presets, or Scenarios under explicit applicability conditions.
```

When `grep` and `preset` coexist, a Scenario may combine them; the current implementation uses OR. The run preserves one canonical `filter` provenance object containing the mode, resolved component patterns, Preset name and version/source/hash metadata (with an explicit `unknown` version when unavailable), and bounded per-hit `matched_by` component IDs; the historical top-level final `pattern` remains for compatibility. If a domain scenario resolver replaces the already-combined expression, the resolved `scenario:<name>` expression is the sole effective matcher while preset/grep remain provenance inputs. Core-only calls without declared components use the reserved `pattern` fallback and mark it explicitly. A Preset match is an observation, not a diagnosis.

## 7. InvestigationState contract (implemented v1)

Runtime provides a versioned, serializable investigation state containing:

```text
schema_version, investigation_id, problem, scope, observations,
hypotheses, tests, executions, findings, stop_reason, knowledge_candidates
```

Each Hypothesis links to supporting and contradicting Evidence. Each Test records intent, expected and contradicting observations, Strategy, execution IDs, and its own declared Coverage; `latest_execution_id` is only a navigation hint and never replaces aggregate Test Coverage. Each bounded Execution records operation status/outcome, parameters, Evidence pointers/references, artifact pointers, verification/run metadata, and Coverage; it deliberately omits the AgentResult `data` payload and raw log bodies and exposes recording omission/truncation flags. Findings transition an open Hypothesis to `supported`, `contradicted`, or `unknown`; a `supported` Finding must include supporting Evidence and a `contradicted` Finding must include contradicting Evidence, while `unknown` may omit either. `stop_reason` transitions an active investigation to `completed`.

`InvestigationStore` persists one document with the standard Core atomic JSON writer and lock. The public Python API is `InvestigationStore`, `create_investigation`, `load_investigation`, and `attach_investigation_result`. Existing tools preserve their result envelopes and accept optional `investigation_path`, `hypothesis_id`, and `test_id` keywords.

An investigation may declare a versioned optional `BudgetPolicy` with positive
limits for executions, searches/queries, recorded Evidence pointers, requested
and returned `expand` characters, and elapsed seconds. Linked tools reserve
limits under the InvestigationState lock before expensive work, finalize with
measured usage, and return structured `BudgetExhausted` without executing when a
limit is unavailable. Usage and remaining counters are persisted; exhausted
investigations record a `budget_exhausted` stop reason. Evidence-pointer
reservations use each operation's bounded worst case (for example, the search
result cap; scenario `run` uses the same public evidence cap before invoking an
extension), so a hard pointer limit can conservatively refuse a call before
scanning or execution rather than allowing post-execution overrun.
Snapshot-disabled raw context reserves no immutable pointers.

The linked deterministic cache is deliberately conservative. Only snapshot,
read-only `probe` and `search` calls without explicit output side effects may be
cached. Keys include operation, canonical parameters, source SHA-256/snapshot,
segmenter identity, result schema, and cache tool version. Cache hits still
record a fresh Investigation Execution. Entries are bounded, atomic, and
discarded when source or artifact paths disappear or hashes change. `survey`,
`sample`, `expand`, `verify`, `run`, extensions, live sources/actions, errors,
and no-snapshot/output-side-effect calls bypass cache explicitly.

Runtime also exposes a versioned, read-only Investigation completeness summary.
It reports bounded counts, unresolved IDs, coverage/recording gaps, stop state,
and domain-neutral suggested action categories without copying claims, evidence
bodies, or raw tool data. The summary is advisory coordination metadata, not a
mandatory funnel, diagnosis, or proof that an investigation is exhaustive.
Bounded read-only timeline and structural-compare views support audit and resume
without replaying raw evidence. They expose IDs, control timestamps, statuses,
counts, coverage/omission signals, budget deltas, and links only; a delta is not
an anomaly or Finding. See [Investigation summary](investigation-summary.md) and
[timeline/structural comparison](investigation-compare.md).

The optional, explicit `InvestigationStore.propose_knowledge_candidate()` operation
bridges one eligible `supported` Finding to a separate
`KnowledgeGovernanceStore`. Eligibility requires supporting Evidence and at least
one related Test; `unknown` and `contradicted` Findings are rejected. The
candidate payload carries the investigation and source revision, hypothesis
claim/outcome, caller-supplied applicability and exclusions, supporting and
contradicting refs, Coverage/limitations, and Test strategies/recipes. The
InvestigationState stores only candidate ID, Finding ID, store link, and latest
status metadata. Proposal is written first and the link second, so a failed
proposal cannot claim a link; repeating the operation for a Finding is
idempotent when the normalized payload and stable proposal identity match;
parameter drift is a conflict. Supporting and contradicting refs use the
immutable `evidence://sha256/<64-hex-digest>#L<start>[-L<end>]` pointer form.
The link's status is a creation-time snapshot: review/promotion does not
silently rewrite InvestigationState, and hosts must explicitly refresh it when
they need current candidate status.

## 8. Context and execution budgets

Progressive disclosure is the primary context-management strategy:

```text
metadata -> bounded sample/survey -> EvidencePointer -> lazy expand -> full Artifact
```

- Direct reading is allowed when tool overhead exceeds a small input.
- Large or changing inputs return metadata, statistics, and pointers rather than full text.
- Deterministic operations may cache by input digest and parameters.
- Large bodies live in Artifacts; AgentResult remains bounded.
- Agent adapters may expose an opt-in compact projection, but must preserve
  losslessly reconstructable evidence identities, epistemic status, essential
  coverage/truncation signals, and a recovery Artifact whenever inline evidence
  is omitted. The canonical Runtime Result and stored Artifacts remain unchanged.
- Agent adapters may keep canonical Results in a content-addressed Evidence
  Ledger and expose only a verified result identifier. Ledger entries are
  immutable, batch expansion revalidates source digests, and missing or
  truncated refs remain explicit coverage rather than silent omission.
- Conversation adapters may compact a tool result only after the model has
  observed it, while retaining the newest result and a deterministic recovery
  path. History compaction is a transport optimization, not evidence deletion.
- Compact projections may use declared-once columnar rows and shared merged
  contexts. Every evidence identity must still map deterministically to its
  exact selected line range and immutable source.
- Agent transport profiles are selected per analysis run and live only in
  ``tracecite.integrations``. A profile may alter transport encoding and
  consumed-history compaction, but must not alter canonical Result semantics,
  select another Agent, or introduce a Core-to-Integration dependency.
- InvestigationState stores decisions, not duplicated raw logs.
- Every Test links to a Hypothesis to prevent aimless query chains.
- Budget exhaustion is a stop reason, never permission to hide truncation or missing evidence.

## 9. Knowledge lifecycle

```text
Observation -> evidence-backed Finding -> Candidate -> independent cases
            -> different reviewer -> Approved Knowledge -> revalidation/expiry
```

Knowledge records applicability and exclusions, a falsifiable claim, supporting and contradicting evidence, test recipes, source versions, review status, and expiry conditions. It narrows future exploration but never skips current Tests and Evidence.

The governance store uses schema v2 with an explicit v1 migration and locked
read-modify-write operations. Promoted knowledge is usable only while its
validity evaluates to `current`; stale, expired, and superseded records remain
auditable but are not silently trusted. Revalidation requires an independent
review. Semantic changes create a linked replacement version; proposing that
replacement does not invalidate already promoted knowledge before the new
version itself is verified and promoted.

## 10. Extensibility rule

The main package owns stable mechanics; domain packages own semantics:

| Public main-package capability | Domain example |
|---|---|
| Source Provider | APM, CI artifact, database result |
| Segmenter / Format | logcat, syslog, build log |
| Preprocessor | symbolication, redaction, archive extraction |
| Event Transformer | crash, request, page, build-stage event |
| Assertion / Reporter | domain threshold and report |
| ScenarioRuntime | Mobile, CI, Backend runtime |
| Skill / Knowledge Pack | methods, Presets, Scenarios, reviewed knowledge |

A concept that only one domain can interpret remains in that extension. Only cross-domain evidence, lifecycle, budget, and protocol invariants belong in the main package.

## 11. Implementation status

| Capability | Status |
|---|---|
| Source, Segmenter, Filter, Snapshot, Evidence, Manifest, Verify | Implemented |
| `probe`, `survey`, `search`, `expand`, `run`, `verify` | Implemented |
| Scenario, Assertion, Reporting, Extension API | Implemented |
| Candidate Knowledge proposal, verification, and promotion | Foundational API implemented |
| Skill investigation and safety guidance | Implemented as textual protocol |
| Versioned `InvestigationState` | Implemented v1 with atomic locked persistence |
| Investigation-level BudgetPolicy and deterministic cache | Implemented for linked tools with reservation/finalization and conservative probe/search cache |
| Structured Hypothesis/Test/execution relations | Implemented with ID and cross-link validation |
| Generic `sample/peek` | Implemented: bounded snapshot-first head/tail and deterministic uniform sampling |
| User-supplied regex resource gate | Implemented across filtering, segmentation, preprocessing, and assertions with structural bounds and rejection of known catastrophic-backtracking shapes |
| Preset component provenance and per-hit `matched_by` | Implemented: bounded OR components, deterministic hit IDs, and run/manifest metadata |
| Investigation-to-Candidate integration | Implemented as an explicit, idempotent bridge with pointer-only state links |
| Advisory Investigation completeness summary | Implemented v1 as a bounded read-only view |
| Investigation timeline and structural comparison | Implemented v1 as bounded read-only views |
| Knowledge locking, validity, revalidation, and supersession | Implemented in governance schema v2 with v1 migration |
| Mobile public-extension and PlatformBackend offline contract | Partially implemented: offline fixtures pass; real-device acceptance remains pending |
| CI domain acceptance | Pending |

Evolution should prioritize protocol state and cross-domain validation rather than adding domain knowledge or mandatory search steps to Core.

## 12. Architecture evolution

The following are architecture changes and must update this document and its Chinese counterpart in the same change:

- dependency direction between layers or packages;
- public concepts or transitions for Problem, Hypothesis, Test, Evidence, Finding, or Knowledge;
- public AgentResult, Evidence, Manifest, Investigation, or Knowledge schema semantics;
- required investigation steps, `status/outcome`, Coverage, or stopping rules;
- extension capabilities, loading, authorization, or trust boundaries;
- Preset, Scenario, or Knowledge responsibilities and lifecycle;
- token, snapshot, integrity, security, or trust semantics;
- any change to the implementation-status table.

Incompatible or long-lived trade-off decisions require an ADR in `docs/adr/`, including context, decision, alternatives, consequences, and migration. Public API/schema changes require versioning, migration documentation, and tests. A main-package boundary change requires evidence from at least two domains; otherwise it remains in an extension.

Reviews must also check whether the [Agent integration guide](agent-integration.md), [Extension contract](extension-contract.md), [Knowledge governance](knowledge-governance.md), and [validation checklist](validation-checklist.md) need corresponding updates. See the [ADR process](adr/README.md) and [schema/API migration notes](migrations/README.md).
