# TraceCite

**An extensible Evidence Runtime for AI debugging agents.**

TraceCite handles large, changing data through bounded, verifiable, traceable Evidence. It is not an embedded autonomous LLM agent: external agents reason, while TraceCite owns deterministic data operations, investigation state, budgets, safety, Coverage, and evidence integrity.

```text
raw data -> Evidence Core -> Investigation Runtime -> Agent / CLI / MCP
                 ^                 ^
                 |                 |
            Core plugins    Extension Protocol v2
                                 |
                          Mobile / CI / third-party
```

## Install and use

```bash
pip install tracecite

tracecite probe ./logs --glob "*.log" --recursive
tracecite search app.log "timeout|OOM" --regex --snapshot
tracecite expand .tracecite/snapshots/app.log 120 --before 5 --after 10
tracecite verify .tracecite/runs/<run-id>/manifest.json
tracecite run scenario.json
```

TraceCite requires Python 3.10+ and supports Linux and macOS. Windows is not currently supported because atomic state locking relies on POSIX `flock`. The main package has no runtime dependencies outside the Python standard library.

Core commands return deterministic JSON. `status` reports execution state while `outcome` reports epistemic state supported by Evidence; zero matches do not prove that a problem did not happen.

See the [Agent integration guide](docs/agent-integration.md) and the [normative architecture](docs/architecture.md).

## Layers

- `tracecite_core`: Source, Segmenter, Sample, Survey, Filter, Snapshot, Evidence, Manifest, Verify, and low-level Plugin SDK.
- `tracecite.runtime`: Investigation, Scenario, Assertion, Reporting, budgets, cache, safety gates, and Agent Capabilities.
- `tracecite.extension`: declarative Extension Protocol v2 and stable domain contracts.
- `tracecite.integrations`: CLI plus Agent-facing transport/projection; MCP evolves as a separate adapter project.
- `tracecite.knowledge`: Knowledge Candidate, independent validation, review, versioning, and expiry.

Domain semantics do not enter Core or Runtime. `tracecite-mobile` is a separate official domain extension and a real validation consumer of the public contracts.

## Extension Protocol v2

v2 no longer requires domain packages to receive an ever-growing `ExtensionAPI.register_xxx()` surface. An extension declares its identity and capabilities:

```toml
[project.entry-points."tracecite.extensions"]
my_domain = "my_tracecite.extension:extension"
```

```python
from tracecite.extension import (
    ExtensionManifest,
    ScenarioCapability,
    TraceCiteExtension,
)

EXTENSION = TraceCiteExtension(
    manifest=ExtensionManifest(
        id="my-domain",
        version="1.0.0",
        domain="my-domain",
    ),
    capabilities=(
        ScenarioCapability(
            name="my-domain",
            load_profile=load_profile,
            resolve_scenario_pattern=resolve_pattern,
        ),
    ),
)


def extension() -> TraceCiteExtension:
    return EXTENSION
```

The top-level protocol stays small while capabilities are independently versioned. Current public contribution types include Core plugin bundles, Agent Capability, Assertion, Report, and Scenario Capability. See [Extension Contract v2](docs/extension-contract.md) and the [v1 to v2 migration](docs/migrations/extension-protocol-v2.md).

## Stable domain data contracts

v2 provides generic values that do not depend on a specific Agent or transport:

- `EvidenceRef`: a domain-side evidence reference independent from Agent URI/short-ID representation.
- `Coverage`: coverage, omission, truncation, and approximation metadata.
- `DomainEvent`: structured domain facts without relevance/root-cause/token-priority verdicts.
- `SourceDescriptor` / `SourceCursor` / `SourceChunk`: incremental sources including files, live streams, and remote APIs.
- `CapabilityResult[T]`: a uniform execution envelope; execution `status` remains separate from Finding `outcome`.

## Agent context principle

Canonical Results and full Evidence remain recoverable; Agent-facing views may be compressed. Agent profiles, compact projection, Evidence Ledger, and `expand-many` already exist.

Seen Evidence, cross-turn deduplication, Context Delta, representative Evidence grouping, and token/context budgets belong to Runtime/Integration and **do not enter the Domain Extension API**. That boundary allows Context Engine, MCP, or model-platform changes without forcing Mobile/CI rewrites.

## Safety and trust

- Evidence is traceable but does not automatically equal complete truth.
- `unknown`, `missing_evidence`, and Coverage gaps are first-class states.
- Agent conclusions cannot automatically promote themselves to trusted Knowledge.
- Domain Extensions cannot bypass Runtime budget, live-source/live-action, or authorization gates.
- Core does not import Runtime or domains; Runtime does not import Mobile/CI.
- `import tracecite` does not execute third-party Extensions; discovery is explicit.

## Current status

Core Extension Protocol v2 contracts, declarative loading, capability-version checks, and adaptation to current Runtime registries are implemented and pass the Core matrix. Mobile v2 migration, the stronger Context Engine, and MCP v2 integration continue in that order; incomplete phases are not presented as implemented.

## License

MIT
