# TraceCite repository instructions

## Project boundaries

- This repository publishes the main `tracecite` distribution.
- `tracecite_core` is the stable, Python-standard-library-only evidence layer.
- `tracecite.runtime` may depend on `tracecite_core`; Core must never import Runtime.
- `tracecite.extension` exposes public extension contracts and may depend on Core/Runtime public APIs.
- `tracecite.integrations` adapts TraceCite to CLI and Agent hosts.
- Keep device, product, company, application, and domain knowledge out of this repository. Mobile, CI, and third-party projects are extensions that depend only on public TraceCite contracts.
- Preserve evidence and run schema semantics unless a migration is documented and tested.
- Treat `docs/architecture.md` and `docs/architecture.zh-CN.md` as the normative architecture contract.
- Any change to dependency direction, canonical Evidence semantics, RetrievalSession ownership, investigation concepts, public evidence/result/knowledge semantics, extension boundaries, trust/budget rules, or implementation status must update both architecture documents in the same change.
- Record incompatible architectural changes and long-lived trade-offs as an ADR under `docs/adr/`; public schema/API changes also require a migration note and tests.

## Agent/Evidence boundary

The highest-level contract is:

> The Agent thinks and decides; TraceCite owns evidence.

TraceCite may own deterministic evidence acquisition, immutable source/version identity, provenance, Coverage, RetrievalSession memory, repeated-evidence accounting, replay/materialization, mechanical aggregation/traversal, bounded transport selection, and verification.

TraceCite must not own or infer hypotheses, causal conclusions, root-cause likelihood, evidence sufficiency, or a recommendation that the Agent should stop.

## Repository rules versus installed TraceCite behavior

This `AGENTS.md` governs development of the TraceCite repository. It is **not** the global investigation policy that TraceCite users should copy into application repositories.

Do not enter TraceCite investigation mode merely because the current task involves logs, traces, debugging, incidents, or root-cause analysis. The installed TraceCite investigation mode activates only while the current task actually uses TraceCite tools or TraceCite skills.

The reusable skill source is:

```text
.agents/skills/tracecite-investigate/SKILL.md
```

The global installation contract and conditional rule are documented in:

```text
docs/agent-global-setup.md
```

For general use, prefer installing the skill once at user scope (for example `~/.agents/skills/tracecite-investigate/`) and adding the short conditional rule to the host's global instructions. Do not add repository-local TraceCite policy unless the user explicitly requests it.

## Validation

For changes to Evidence Runtime or Agent integration:

- run the focused unit tests for the changed subsystem;
- run architecture/dependency tests where relevant;
- preserve canonical Result/Evidence recoverability and Coverage semantics;
- treat provider 429/quota/outage as infrastructure-invalid benchmark runs, not model/product failures;
- compare answer quality before efficiency metrics; lower token/tool cost does not compensate for a correctness regression;
- update `docs/benchmark-results*.md` only from validated paired runs and keep raw scorer caveats explicit.

Current documentation map: `docs/README.md`.
