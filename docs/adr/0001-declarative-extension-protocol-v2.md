# 0001: Declarative Extension Protocol v2

- Status: accepted
- Date: 2026-08-27
- Owners: TraceCite maintainers
- Supersedes: Extension Protocol v1 registration model
- Superseded by:

## Context

Extension Protocol v1 passed a mutable `ExtensionAPI` into third-party code. Domain packages called methods such as `register_runtime`, `register_capability`, `register_assertion_type`, and `register_report_outputter`. This was convenient while the surface was small, but it coupled every domain package to the Runtime's current registry shape.

The `feature_for_agent` line already introduced Agent Capability, budget/safety controls, Agent projections, an Evidence Ledger, SourceSession, and a separate MCP adapter. Planned context-efficiency work adds Seen Evidence, cross-turn deduplication, representative evidence selection, context deltas, and stronger stop/budget policy. Continuing to add `register_xxx` methods would make Mobile, CI, and future domains change whenever Runtime or host integration evolves.

The same problem existed around named `ScenarioRuntime`: it exposed a Runtime implementation object as a domain extension contract, encouraging one domain runtime per extension even though architecture requires one generic Investigation Runtime.

## Decision

Adopt Extension Protocol v2 as a declarative, capability-based boundary.

1. A domain entry point yields one `TraceCiteExtension` containing an `ExtensionManifest` and a sequence of independently versioned capabilities.
2. The top-level extension protocol remains intentionally small. New functionality should normally add an optional capability kind/version instead of a new top-level registration method.
3. Stable cross-domain values include `EvidenceRef`, `Coverage`, `DomainEvent`, `SourceDescriptor`, `SourceCursor`, `SourceChunk`, and `CapabilityResult`.
4. `ScenarioCapability` replaces `ScenarioRuntime` as the public domain contract. Runtime may adapt it to the current `ScenarioRuntime` internally while that executor is retained.
5. Low-level `tracecite_core.PluginAPI` remains a separate protocol. A domain extension can bundle low-level registrations through `CorePluginCapability` without inheriting the Core plugin API as its top-level extension API.
6. Agent-context concerns remain outside Extension Protocol: token policy, Seen Evidence, Context Delta, AgentView, MCP schemas, and host-specific ranking are Runtime/Integration concerns.
7. `DomainEvent` records domain facts only. Relevance, ranking, root-cause verdicts, and epistemic Finding outcomes remain investigation concerns.

## Alternatives considered

### Keep v1 and add more `register_xxx` methods

Rejected because every new Runtime capability would expand a shared mutable API and increase migration pressure on all domains.

### Make token/context optimization an Extension capability

Rejected because context relevance depends on the current investigation and host. It would duplicate policy across Mobile, CI, and other domains and couple them to model/platform changes.

### Expose a new `ScenarioRuntimeV2`

Rejected because it preserves the one-runtime-per-domain pattern. Scenario behavior is better represented as domain capabilities consumed by one generic Runtime.

### Rewrite the entire Scenario executor immediately

Rejected for this change. The public boundary is changed now, while an internal adapter preserves the tested Scenario executor. This contains migration risk without retaining the old public dependency.

## Consequences

Positive:

- Domain packages can survive Runtime/context/MCP evolution with fewer public API migrations.
- Capabilities can evolve independently.
- Domain facts, canonical evidence, investigation decisions, and Agent transport become clearer layers.
- Source Cursor and DomainEvent contracts create stable seams for live/remote sources and structured domain events.

Costs and risks:

- v1 `ExtensionAPI`, `TRACECITE_EXTENSION_API`, and `register(api)` entry points are breaking changes for domain extensions.
- Mobile must migrate once to declarative contributions.
- Current internal `ScenarioRuntime` remains temporarily as an implementation adapter and must not re-emerge as a public dependency.
- `CorePluginCapability` temporarily bridges the older low-level PluginAPI registration model; the two protocols must remain independently versioned.

## Migration and validation

- Extension Protocol version is `2`.
- Capability kinds have independent integer versions.
- Core contract tests cover declarative loading, idempotence, collision behavior, capability installation, DomainEvent/EvidenceRef, Coverage, SourceCursor/SourceChunk, and execution-status separation.
- The full Core CI matrix must pass on Python 3.10–3.14 and macOS/Linux before downstream migration.
- `tracecite-mobile` migrates after Core contract/document/test stabilization and becomes the first real domain validation.
- `tracecite-mcp` migrates last and must depend on public Runtime/Context interfaces rather than extension registries.
- CI remains the second target domain for validating that main-package abstractions are not Mobile-specific.

Rollback is branch-level until the v2 migration is accepted into the `feature_for_agent` line; v1 compatibility is not intended to remain as a parallel long-term architecture.

## Documentation updates

This decision updates:

- `docs/architecture.md`
- `docs/architecture.zh-CN.md`
- `docs/extension-contract.md`
- `README.md`
- `README.zh-CN.md`
- `docs/agent-integration.md`
- `docs/agent-integration.zh-CN.md`
- `docs/migrations/extension-protocol-v2.md`
- `docs/migrations/extension-protocol-v2.zh-CN.md`
- downstream Mobile and MCP documentation during their migration stages.
