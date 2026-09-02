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

## Evidence investigation workflow for Codex/OpenAI-compatible agents

When the task is to investigate logs, traces, support bundles, crash reports, or other diagnostic evidence, use the repository skill:

```text
.agents/skills/tracecite-investigate/SKILL.md
```

Use it when the question requires evidence-backed diagnosis/root-cause analysis, especially when the input is large or spans multiple sources. Keep this `AGENTS.md` short; detailed API semantics belong in the skill and `docs/agent-integration.md`.

Operating rules:

1. Work only from supplied evidence for factual incident claims; do not silently fill gaps from model memory or the web.
2. Keep retrieval bounded. Before a new evidence operation, know which unresolved material claim it can change and what discriminator would change that claim.
3. Prefer exact source/version identity and materialized line/range citations for material factual claims.
4. Treat zero matches, truncation, missing sources, incomplete Coverage, and source changes as evidence-boundary facts, not proof of real-world absence.
5. Reuse known Evidence refs/ranges. Use explicit replay when old evidence truly needs to be reconsidered.
6. Do not perform a broad evidence census after the causal proof required by the user is already supported.
7. The Agent, not TraceCite Runtime, decides whether the proof is sufficient and when to answer.

Recommended task wording:

```text
Use $tracecite-investigate to investigate <problem> from the supplied evidence.
Keep retrieval bounded. Cite exact materialized evidence for material factual claims.
Do not fill evidence gaps with external knowledge; qualify unsupported parts explicitly.
```

## Validation

For changes to Evidence Runtime or Agent integration:

- run the focused unit tests for the changed subsystem;
- run architecture/dependency tests where relevant;
- preserve canonical Result/Evidence recoverability and Coverage semantics;
- treat provider 429/quota/outage as infrastructure-invalid benchmark runs, not model/product failures;
- compare answer quality before efficiency metrics; lower token/tool cost does not compensate for a correctness regression;
- update `docs/benchmark-results*.md` only from validated paired runs and keep raw scorer caveats explicit.

Current documentation map: `docs/README.md`.
