# TraceCite Architecture

Status: normative  
Scope: the TraceCite distribution, official domain extensions, and Agent/CLI/MCP host adapters

This document is the top-level architecture contract. Agent integration, extension, knowledge-governance, and validation documents must preserve these boundaries. Planned capabilities must not be presented as implemented behavior.

## 1. Product definition

TraceCite is an **evidence-driven investigation framework for external agents**:

- The Agent understands the problem, explores freely, forms hypotheses, selects tests, and interprets results.
- TraceCite records investigation state, performs deterministic data operations, enforces budgets, produces traceable Evidence, and governs Knowledge lifecycle.
- Domain Extensions provide Mobile, CI, backend, database, and other data adapters and semantics.
- Agent/CLI/MCP adapters project Runtime capabilities into host-specific surfaces; they do not define domain facts.

The governing principle is:

> Constrain conclusions, not exploration.

TraceCite is neither an embedded autonomous LLM agent nor a mandatory command funnel for every investigation.

## 2. Architectural invariants

The following constraints require an ADR, versioned migration, and validation to change:

1. Core provides generic, deterministic, reproducible Evidence mechanics and contains no device, product, company, application, or business knowledge.
2. Agents may choose any safe exploration strategy. A final Finding identifies its Hypothesis, Evidence, Coverage, limitations, and stop reason.
3. `status` is execution state; `outcome` is epistemic state. They remain separate.
4. Zero matches, incomplete Coverage, missing Evidence, and execution failure do not prove absence; they default to `unknown`.
5. Citable Evidence points to an immutable snapshot and range, or to an integrity-verified Manifest.
6. Agent conclusions cannot promote themselves to trusted Knowledge or independently verify themselves.
7. Extensions provide domain facts and capabilities; Runtime retains execution, budget, Evidence, verification, safety, stopping, and Agent-context control.
8. Core never imports Runtime or domains; Runtime never imports a concrete domain. Domain packages depend only on public TraceCite contracts.
9. Bounded, sampled, approximate, or truncated operations expose Coverage explicitly.
10. Canonical Result/Evidence is separate from Agent-facing views. Transport compression, token policy, seen state, and context deltas are not Domain Extension responsibilities.
11. The top-level Extension Protocol is kept stable; new domain features prefer independent versioned capabilities instead of new top-level `register_xxx` methods.
12. A new main-package capability should serve at least two domains; otherwise it remains in a domain extension.

## 3. Logical architecture

```text
User problem
    |
    v
Agent Host
understanding, reasoning, next-step decisions, user interaction
    |
    v
Agent / Integration Projection
CLI, MCP, Codex/Claude/ChatGPT and other hosts
    |
    v
Investigation Runtime  <---->  Knowledge Registry
state, budgets, safety, stopping       proposals, review, versions, expiry
    |
    v
Evidence Core
Source, Segmenter, Sample, Survey, Filter, Snapshot, Evidence, Manifest, Verify
    |
    v
Evidence Store
frozen inputs, filtered artifacts, events, reports, manifests

Stable TraceCite Extension Protocol
    ^
    |
Domain Extensions
Mobile / CI / Backend / Third-party
```

Extensions exchange stable contracts and capabilities with Runtime rather than Runtime implementation objects. The current implementation may internally adapt a `ScenarioCapability` to `ScenarioRuntime`; `ScenarioRuntime` is not the long-term public extension boundary.

### 3.1 Agent Host

The host turns natural language into Problem and Scope; chooses direct reads, sampling, survey, search, Scenario, or domain capabilities; creates falsifiable Hypotheses and Tests; seeks supporting and contradicting evidence; and retains `unknown` when evidence is insufficient. Agent reasoning is not independent Evidence.

### 3.2 Investigation Runtime

There is one generic investigation runtime. It:

- persists versioned `InvestigationState`;
- links Executions to Problem, Hypothesis, Test, and Finding;
- enforces budgets, safety, authorization, and stopping policy;
- invokes installed domain capabilities;
- preserves canonical results while maintaining state needed for bounded host projections.

Domains no longer define system behavior through “one Runtime per domain.” `ScenarioCapability` supplies domain profile, preset/subscenario resolution, and related hooks to the generic Runtime. The current `ScenarioRuntime` type is an internal adaptation mechanism.

### 3.3 Evidence Core

`tracecite_core` is the standard-library-only stable Evidence kernel. It resolves and freezes input, streams segmentation/sample/survey/filter operations, creates hash-addressed pointers, manages artifacts and manifests, and verifies integrity. It does not understand domain concepts such as white screens, hangs, or failed builds and does not decide root cause.

### 3.4 Knowledge Registry

The registry manages Knowledge Candidate proposal, independent-case verification, review, promotion, versioning, and expiry. See [Knowledge governance](knowledge-governance.md). Trusted Knowledge may recommend future Hypotheses, Tests, Presets, or Scenarios; it never replaces current Evidence.

### 3.5 Domain Extensions

Domain Extensions contain domain data and semantics. Mobile is an official extension, not a Core special case. The TraceCite Extension Protocol is declarative:

- `ExtensionManifest` identifies the extension, domain, version, and protocol version.
- `TraceCiteExtension` contains a Manifest and capability list.
- capabilities are independently versioned, currently including `core.plugins`, `agent.capability`, `runtime.assertion`, `runtime.report`, and `runtime.scenario`.
- stable domain values include `EvidenceRef`, `Coverage`, `DomainEvent`, `SourceDescriptor`, `SourceCursor`, `SourceChunk`, and `CapabilityResult`.

A DomainEvent describes facts. It does not contain question-specific relevance, token priority, or root-cause verdicts. See the [Extension contract](extension-contract.md).

## 4. Investigation model

| Concept | Meaning | Required relation |
|---|---|---|
| Problem | The user's actual question, not necessarily a query string | Scope |
| Scope | Source, subject, time, permission, and budget boundaries | Problem |
| Observation | Observable fact without causal interpretation | Source or Evidence |
| DomainEvent | Structured domain fact supplied by an Extension | EvidenceRef / Source |
| Hypothesis | Falsifiable statement | Problem |
| Test | Concrete plan to evaluate a Hypothesis | Hypothesis |
| Strategy | Execution method used by a Test | Test |
| Evidence | Reviewable, addressable evidence | Test, source, digest |
| Coverage | Coverage, omission, sampling, approximation, and truncation | Test / Evidence / Capability |
| Finding | `supported`, `contradicted`, or `unknown` judgment | Evidence, Coverage |
| Knowledge Candidate | Reusable proposal extracted from a Finding | Investigation, Evidence |
| Knowledge | Independently validated and reviewed versioned knowledge | Candidate, review record |

DomainEvent/Observation and Finding stay separate. “`/home` returned HTTP 504 at 10:30:04” is a fact; “the 504 caused the white screen” remains a Hypothesis/Finding requiring evidence.

## 5. Generic investigation protocol

```text
Problem + Scope
      |
      v
Orient -----> Explore
                 |
                 v
             Hypothesis
                 |
                 v
               Test
                 |
                 v
       Evidence + Coverage
                 |
                 v
              Finding
                 |
                 v
             Stop reason
                 |
                 +----> optional Knowledge Candidate -> Review -> Knowledge
```

### 5.1 Required steps

A deliverable investigation must define Problem and Scope, create at least one falsifiable Hypothesis, define a Test including possible contradiction, inspect Evidence and Coverage, create a bounded Finding, and record a stop reason. Orient and Explore are cognitive requirements, not mandatory commands. Small static input may be read directly; large or unfamiliar input should use bounded tools.

### 5.2 Conditional strategies

| Strategy | Use when | Not required when |
|---|---|---|
| `probe` | Multiple/large sources, unknown format or time coverage | Small known input |
| `sample/peek` | A small amount of raw context is useful | A strong anchor already exists |
| `survey` | Input is unfamiliar and lacks a reliable first query | Error code, stack, request ID, or event is known |
| `search` / `grep` | A Test has a temporary literal/regex predicate | A domain capability yields better evidence |
| `preset` | A versioned reusable filter exists | One-off query |
| `expand` | A pointer lacks context | Existing evidence is sufficient |
| Scenario | Reproduction, assertions, regression, or deliverable artifact is needed | Exploration has not converged |
| `verify` | A final result depends on a Scenario Manifest | No Scenario result is cited |

### 5.3 Adaptive routing

```text
small, static, safe full read
    -> direct read -> freeze key Evidence as needed

known error code, stack, time, or request ID
    -> Hypothesis -> search/domain capability -> expand

large or unfamiliar input
    -> probe -> optional sample/survey -> competing Hypotheses -> separate Tests
```

Survey and DomainEvents produce observations; they do not automatically select root cause.

## 6. Strategy, Preset, Scenario, and Knowledge

```text
Hypothesis
└── Test
    └── Strategy
        ├── direct read / sample / survey
        ├── grep / search
        ├── preset
        ├── extension capability
        └── Scenario

Knowledge
└── recommends Hypotheses, Tests, Presets, or Scenarios within applicability
```

A Scenario is a repeatable test recipe, not a domain Runtime. Extensions may provide domain parsing/context via `ScenarioCapability`; the generic Runtime owns execution, budgets, Evidence, and safety.

## 7. InvestigationState contract (v1 implemented)

`InvestigationState` is the versioned cross-tool investigation document. It records Problem, Scope, Observation, Hypothesis, Test, Execution, Finding, stop reason, Knowledge Candidate, and reusable SourceSession state. Its persisted schema version is independent from the Extension Protocol version.

Tools remain independently callable and opt into bounded recording when an investigation path is supplied. Bounded read-only Summary, Timeline, and Compare views support recovery and audit without replaying raw Evidence. See [Investigation summary](investigation-summary.md) and [Timeline/compare](investigation-compare.md).

## 8. Context and execution budgets

Progressive disclosure is a base strategy:

```text
metadata -> bounded sample/survey -> EvidencePointer -> on-demand expand -> full Artifact
```

Canonical Evidence and Results remain complete and recoverable. Agent-facing projections may compress them but must retain required Coverage, truncation signals, and recovery paths. Runtime/Integration provides budgets, Agent profiles, compact projection, Evidence Ledger, `expand-many`, bounded Seen Evidence, and persistent cross-turn Context Delta. The Context Engine stores transport memory separately from InvestigationState and applies delta only after the canonical Result is recoverable. See [Context Engine](context-engine.md).

Representative Evidence grouping and semantic compaction remain later Runtime/Integration optimizations and do not enter the Extension Protocol.

Token reduction must never hide missing Evidence, approximation, parsing failure, or Coverage gaps.

## 9. Knowledge lifecycle

```text
Observation / DomainEvent
  -> Evidence-backed Finding
  -> Knowledge Candidate
  -> Independent validation
  -> Review
  -> Versioned Knowledge
```

An Agent cannot self-promote Knowledge. See [Knowledge governance](knowledge-governance.md).

## 10. Extensibility

The main package supplies mechanisms; domains supply facts and semantics:

| Main-package public contract | Domain examples |
|---|---|
| TraceCite Extension Protocol | Mobile, CI, Backend Extension |
| Core Plugin Capability | Source, Segmenter, Preprocessor, Event Transformer bundles |
| Agent Capability | device queries, CI status queries, domain read/action tools |
| Scenario Capability | Mobile/CI profile, preset, scenario resolver |
| Assertion / Report Capability | domain assertions and reporting |
| DomainEvent / EvidenceRef / Coverage | Mobile crash/network, CI build/test facts |

`ScenarioRuntime` is a current internal Runtime adapter, not a long-term public Extension capability. Concepts interpretable only by one domain remain in that extension; only cross-domain invariants enter the main package.

## 11. Implementation status

| Capability | Status |
|---|---|
| Source, Segmenter, Filter, Snapshot, Evidence, Manifest, Verify | implemented |
| `probe`, `sample/peek`, `survey`, `search`, `expand`, `run`, `verify` | implemented |
| InvestigationState, budgets, SourceSession, Summary, Timeline, Compare | implemented |
| Knowledge Governance and explicit migration | implemented |
| Agent profile, compact projection, Evidence Ledger, `expand-many` | implemented |
| Agent Capability Registry and live safety gates | implemented |
| Declarative Extension Protocol and internal Scenario adaptation | implemented |
| Mobile Extension integration | implemented |
| Context Engine: Seen Evidence, cross-turn dedupe, Context Delta | implemented |
| Representative Evidence grouping / semantic compaction | planned |
| MCP adapter on Runtime/Context APIs | implemented |
| Mobile device and CI cross-domain validation | partially implemented: automated Mobile real-log/matrix validation exists; real-device and a separate CI-domain extension validation remain |

The contract → Context Engine → Mobile → MCP migration sequence is complete on the refactor branches. Remaining validation priorities are real Agent-host/token benchmarks, real-device Mobile acceptance, and a second independent domain such as CI before generalizing additional domain concepts into the main package.

## 12. Architecture evolution and maintenance

### 12.1 Architectural changes

The following require synchronized updates to this document and its Chinese counterpart: dependency direction; public investigation concepts or state transitions; Extension Protocol or capability versioning; Canonical Result / Agent View, token, safety, snapshot, integrity, and trust boundaries; and implementation-status changes.

### 12.2 Maintenance requirements

1. Architecture changes update `architecture.md` and `architecture.zh-CN.md` in the same PR.
2. Incompatible or long-lived trade-offs require an ADR.
3. Schema or public API changes require version strategy, migration guidance, and tests.
4. Domain-boundary changes ultimately require at least two domain cases; otherwise they remain domain capabilities.
5. Keep the top-level Extension Protocol stable; prefer optional independently versioned capabilities over expanding the top-level API.
