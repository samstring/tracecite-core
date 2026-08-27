# Extension Protocol v1 -> v2 Migration

Extension Protocol v2 replaces the mutable `ExtensionAPI.register_xxx()` model with a declarative `TraceCiteExtension` containing independently versioned capabilities.

## Before: v1

```python
from tracecite.extension import ExtensionAPI
from tracecite.runtime import ScenarioRuntime

TRACECITE_EXTENSION_API = "1"
MY_RUNTIME = ScenarioRuntime(
    load_profile=load_profile,
    resolve_scenario_pattern=resolve_pattern,
)


def register(api: ExtensionAPI) -> None:
    register_core_plugins(api)
    api.register_capability(MY_SPEC, execute_my_tool)
    api.register_runtime("my-domain", MY_RUNTIME)
```

```toml
[project.entry-points."tracecite.extensions"]
my_domain = "my_tracecite.extension"
```

## After: v2

```python
from tracecite.extension import (
    AgentCapability,
    CorePluginCapability,
    ExtensionManifest,
    ScenarioCapability,
    TraceCiteExtension,
)

EXTENSION = TraceCiteExtension(
    manifest=ExtensionManifest(
        id="my-domain",
        version="2.0.0",
        domain="my-domain",
    ),
    capabilities=(
        CorePluginCapability(
            name="my-domain.core",
            register=register_core_plugins,
        ),
        AgentCapability(
            spec=MY_SPEC,
            executor=execute_my_tool,
        ),
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

```toml
[project.entry-points."tracecite.extensions"]
my_domain = "my_tracecite.extension:extension"
```

## Mapping

| v1 | v2 |
|---|---|
| `TRACECITE_EXTENSION_API = "1"` | `ExtensionManifest(protocol_version="2")` (default) |
| `register(api)` | `extension() -> TraceCiteExtension` |
| `api.register_capability(spec, executor)` | `AgentCapability(spec, executor)` |
| `api.register_assertion_type(name, fn)` | `AssertionCapability(name, fn)` |
| `api.register_report_outputter(name, fn)` | `ReportCapability(name, fn)` |
| `api.register_runtime(name, ScenarioRuntime(...))` | `ScenarioCapability(name, ...)` |
| low-level Source/Segmenter/etc registration | `CorePluginCapability(name, registrar)` using `PluginAPI` internally |

## Important behavior changes

- There is no replace flag in the v2 declarative protocol. Duplicate extension IDs or `(kind, name)` capabilities fail deterministically.
- `ScenarioRuntime` is no longer a public extension dependency. Runtime may construct one internally as an adapter.
- Capabilities have independent versions; upgrading one capability kind does not require all extension capabilities to change.
- Extension code does not control Agent context/token policy.
- `DomainEvent` is factual and must not contain relevance, root-cause, or Finding verdicts.
- `CapabilityResult.status` is execution status only; Investigation `outcome` remains separate.

## Migration checklist

1. Replace imports of `ExtensionAPI` and public `ScenarioRuntime` from the extension entry point.
2. Convert each registration to one declarative capability object.
3. Keep low-level `PluginAPI` registration code as a registrar if it already cleanly registers Source/Segmenter/Preprocessor/Event Transformer functionality.
4. Move runtime callback fields into `ScenarioCapability`.
5. Change the package entry point to `module:extension` (or export `EXTENSION`).
6. Update tests to load the extension explicitly and inspect installed capabilities.
7. Run the domain's full offline fixtures and safety tests.
8. Only after the domain passes should any v1-only compatibility code be deleted.

## Context/token work

Do not add Seen Evidence, Context Delta, token limits, model names, or MCP details to the domain extension during this migration. Those features belong to Runtime/Integration and are intentionally isolated from the v2 extension boundary.
