# Architecture Decision Records

Use an Architecture Decision Record (ADR) for an incompatible architectural change or a decision with a long-lived trade-off. Small internal refactors that preserve the contracts in `docs/architecture.md` do not require an ADR.

Name records `NNNN-short-title.md`. ADRs are immutable after acceptance except for status and links; superseding decisions create a new ADR.

Required template:

```markdown
# NNNN: Decision title

- Status: proposed | accepted | superseded | rejected
- Date: YYYY-MM-DD
- Owners:
- Supersedes:
- Superseded by:

## Context

What problem, constraints, and evidence require a decision?

## Decision

What is changing, and which architectural invariant or public contract is affected?

## Alternatives considered

What credible alternatives were evaluated and why were they not selected?

## Consequences

Positive effects, costs, risks, compatibility impact, and operational impact.

## Migration and validation

Schema/API versioning, rollout, rollback, tests, and at least two domain cases when a main-package boundary changes.

## Documentation updates

List the architecture, integration, extension, knowledge, and validation documents updated with this decision.
```

Both [`docs/architecture.md`](../architecture.md) and
[`docs/architecture.zh-CN.md`](../architecture.zh-CN.md) remain the current
architecture contract. ADRs explain why that contract changed; they do not
replace it.
