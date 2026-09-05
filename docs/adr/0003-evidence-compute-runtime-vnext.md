# 0003: Evidence Compute Runtime vNext

- Status: proposed
- Date: 2026-09-05
- Owners: TraceCite maintainers
- Supersedes:
- Superseded by:

## Context

Native-vs-TraceCite investigation runs show that the remaining gap is not mainly Evidence discovery. Native shell/Python can keep a large amount of mechanical scan/filter/group/compare work inside one process, while TraceCite still exposes too many mechanical boundaries to the Agent. Those extra model/tool rounds increase context replay, provider request pressure, and wall time.

TraceCite already has foundations that must remain authoritative: Segmenter complete-Record recovery, RetrievalSession-bound SessionSourceView / SourceVersion, Evidence identity and provenance, Host-owned transport policy, materialize/replay, and bounded Agent transport.

The full design, adversarial review, implementation stages, Native comparison, transport rules, 7-minute benchmark protocol, and anti-overfitting firewall are maintained in `docs/design/tracecite-vnext-evidence-compute-plan.zh-CN.md`.

## Decision

Evolve incrementally toward an **Evidence Compute Runtime** while preserving the existing Evidence foundation and Agent/Runtime semantic boundary.

1. Evidence Shell remains supported but becomes a compatibility frontend rather than the long-term capability boundary.
2. Introduce an internal Evidence Plan representation for deterministic mechanical computation; IR nodes may describe filtering, bounded aggregate, sort/top-K, and later caller-selected window/join/contrast primitives, but never causal conclusions, hypothesis ranking, sufficiency, or stopping.
3. The first implementation slice provides a small caller-owned batch analysis surface: the Agent chooses several bounded mechanical aggregate programs over one source; Runtime keeps them behind one tool boundary and fuses compatible scans/structured parsing where safe.
4. Shared execution must bind one SessionSourceView / SourceVersion and preserve Segmenter/Record semantics. If fusion is unsafe, Runtime may use canonical fallback internally without adding another Agent/model boundary.
5. Large intermediate RecordSets remain Runtime-side. Agent-visible outputs are bounded scalar/aggregate/top-K results, explicit coverage, stable identities, and explicitly materialized Evidence when requested.
6. Host/User owns compute/transport/materialization policy. The Agent cannot raise transport budgets or turn an unbounded result into a hidden first-N result.
7. Derived-result lineage must remain compact. It should normally be recoverable from SourceVersion + normalized plan + coverage/result identity rather than a full high-cardinality list of member Evidence IDs.
8. Future ResultHandles, if added, are session-scoped, immutable, bounded/evictable optimizations rather than a new canonical evidence store.
9. A pure Program/UDF escape hatch remains a possible target, but is deferred until paired evidence shows fixed mechanical operators are still the dominant flexibility bottleneck.
10. TraceCite Runtime and Skill must not encode investigation strategy. Caller-selected time windows/contrasts may be executed mechanically, but rules such as when to perform a causal contrast or when to stop remain Agent-owned.

## Alternatives considered

### Keep extending Evidence Shell only

Rejected as the long-term architecture. It risks turning TraceCite into a partial Unix reimplementation and does not directly solve the main problem: too many model boundaries for multi-step mechanical analysis.

### Use native shell/Python only

Retained as the strongest competing design and benchmark baseline. Native has better unrestricted local programmability, but does not automatically provide TraceCite's SourceVersion, provenance, replay, Host budget, or bounded model transport. vNext is justified only if paired runs demonstrate that those guarantees do not impose worse time/answer quality and do reduce model context pressure.

### Implement a full UDF VM/WASM environment immediately

Deferred. It adds language, sandboxing, optimizer and security complexity before proving that a smaller batch/shared-scan compute layer is worthwhile.

### Add automatic RCA/diagnostic planning

Rejected. That violates the project boundary: Agent owns hypotheses, causal reasoning, sufficiency, and stopping.

### Preserve complete derived lineage as member Evidence IDs

Rejected because it recreates the high-cardinality EvidenceIndex problem under another name. Deterministic compact lineage/recomputation is preferred.

## Consequences

Positive:

- multiple already-chosen mechanical analyses can cross one Agent/tool boundary;
- compatible JSONL/Record work can share scans and parsing;
- intermediate evidence scale becomes less coupled to model context size;
- existing SourceVersion/Evidence/provenance guarantees are preserved;
- the architecture gains a path toward Native-like evidence computation without exposing OS shell capabilities;
- public tool count can remain small while Runtime-side work per call increases.

Costs and risks:

- IR/execution planning introduces a new semantic-equivalence surface;
- optimizer/fast-path bugs can diverge from canonical behavior and require parity tests;
- tool schema and Skill text themselves consume context and must remain compact;
- over-compression can hide qualitative details unless exact Evidence stays recoverable;
- result handles/cache, if introduced, need strict lifecycle and SourceVersion keys;
- Core cannot universally rewrite model conversation history; Host-dependent checkpoint compaction must not be claimed as a portable Core guarantee;
- Native remains the unrestricted flexibility ceiling and may still win some workloads.

## Migration and validation

The migration is incremental.

Phase 1/2 first slice:

1. add minimal deterministic batch compute structures over current Evidence program semantics;
2. expose a bounded list of named aggregate analyses over one logical source;
3. fuse compatible JSONL scans/JSON decoding;
4. keep canonical fallback inside the same Agent boundary;
5. add equivalence tests against independent canonical calls;
6. expose one compact MCP `tracecite_analyze` tool;
7. remove causal/stopping investigation coaching from the TraceCite Skill.

Deferred until measurements justify them:

- general Program/UDF VM;
- autonomous planning;
- arbitrary joins/correlation engine;
- public persistent ResultHandle API;
- automatic Host history replacement.

Validation gates:

- Core/MCP regression suites must pass before benchmark use;
- RCA paired Agent timeout is 420 seconds per arm;
- final correctness is manually reviewed, not decided by gold/regex scorer;
- TraceCite must use less model context/token load, must not be slower than Native on a valid paired run, and must not produce a worse answer;
- material provider 429/overload requires classification and rerun when it can dominate the result;
- benchmark-driven product changes must remain generic and must not contain current case/service/fault/OTel/JVM/memory-specific logic.

If the narrow compute slice cannot satisfy these gates, the design must be reconsidered rather than expanded merely to justify vNext.

## Documentation updates

The detailed proposal and adversarial self-review are maintained in:

- `docs/design/tracecite-vnext-evidence-compute-plan.zh-CN.md`

When this ADR is accepted after implementation/benchmark validation, the proven architecture will be folded into the living architecture documents. Until then this ADR remains `proposed` and the current accepted architecture remains authoritative.
