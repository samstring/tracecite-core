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

See the [Agent integration guide](docs/agent-integration.md), [Context Engine](docs/context-engine.md), and the [normative architecture](docs/architecture.md).

## Layers

- `tracecite_core`: Source, Segmenter, Sample, Survey, Filter, Snapshot, Evidence, Manifest, Verify, and low-level Plugin SDK.
- `tracecite.runtime`: Investigation, Scenario, Assertion, Reporting, budgets, cache, safety gates, and Agent Capabilities.
- `tracecite.extension`: declarative Extension Protocol v2 and stable domain contracts.
- `tracecite.integrations`: CLI, Agent transport/projection, Evidence Ledger, and Context Engine; MCP evolves as a separate adapter project.
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

extension = EXTENSION
```

The top-level protocol stays small while capabilities are independently versioned. Current public contribution types include Core plugin bundles, Agent Capability, Assertion, Report, and Scenario Capability. See [Extension Contract v2](docs/extension-contract.md) and the [v1 to v2 migration](docs/migrations/extension-protocol-v2.md).

## Stable domain data contracts

v2 provides generic values that do not depend on a specific Agent or transport:

- `EvidenceRef`: a domain-side evidence reference independent from Agent URI/short-ID representation.
- `Coverage`: coverage, omission, truncation, and approximation metadata.
- `DomainEvent`: structured domain facts without relevance/root-cause/token-priority verdicts.
- `SourceDescriptor` / `SourceCursor` / `SourceChunk`: incremental sources including files, live streams, and remote APIs.
- `CapabilityResult[T]`: a uniform execution envelope; execution `status` remains separate from Finding `outcome`.

## Agent context and token transport

Canonical Results and immutable Evidence remain recoverable. Token reduction is implemented only as an Agent transport layer and never rewrites domain facts or canonical evidence.

The existing compact projection and Evidence Ledger are now joined by a bounded persistent Context Engine. A stateful host can give one investigation/conversation a stable context ID:

```bash
tracecite search app.log "timeout" --snapshot \
  --agent-profile stateful-index \
  --ledger-dir /tmp/tracecite-ledger \
  --context-id incident-42
```

On the first turn the Agent receives the bounded Evidence view normally. On later overlapping searches with the same context ID, Evidence URIs already seen by that context are omitted and explicit `data.context` metadata reports new/repeated counts. The complete canonical search Result is stored first in the content-addressed Ledger, so transport deduplication never destroys recoverability.

Recover several immutable refs with:

```bash
tracecite expand-many /tmp/tracecite-ledger RESULT_ID '#L120' '#L188-L190'
```

Context state is bounded transport memory, not trusted Evidence or InvestigationState. Unknown/unaddressable evidence is never silently deduplicated, and different context IDs do not share seen-state. Representative Evidence grouping remains a later optimization; it is not part of Extension Protocol v2.

## Safety and trust

- Evidence is traceable but does not automatically equal complete truth.
- `unknown`, `missing_evidence`, and Coverage gaps are first-class states.
- Agent conclusions cannot automatically promote themselves to trusted Knowledge.
- Domain Extensions cannot bypass Runtime budget, live-source/live-action, or authorization gates.
- Core does not import Runtime or domains; Runtime does not import Mobile/CI.
- `import tracecite` does not execute third-party Extensions; discovery is explicit.
- Context delta changes transport only; canonical Result/Evidence remain recoverable.

## Current status

Extension Protocol v2, declarative capability loading, stable domain contracts, Evidence Ledger, bounded cross-turn Context Delta, and the stateful CLI path are implemented and pass the Core Python 3.10–3.14 Linux/macOS matrix. The matching Mobile v2 branch and MCP v2/context integration are also validated on their own matrices; real-host and token-savings benchmarks remain separate acceptance work.

## License

MIT
