# TraceCite development workflow

Status: current development-process contract for `feature_for_agent`.

## Branch roles

- `main` is the stable baseline. Do not use it as the day-to-day development branch.
- `feature_for_agent` is the single source of truth for active TraceCite development.
- By default, make normal product changes directly on `feature_for_agent` as small, reviewable commits.
- Benchmarks, CI runs, reproductions, and one-off validations must use workflows/artifacts rather than creating a branch solely to run a test.

## Single active child-branch rule

Creating a child branch from `feature_for_agent` is an exception for isolated or risky work, not the default workflow.

At any time there may be **at most one active child branch** with commits that are not yet contained in `feature_for_agent`.

An active child branch is any repository branch other than `main` and `feature_for_agent` whose divergence point from `feature_for_agent` is at or after the branch-policy baseline and which contains commits not reachable from `feature_for_agent`.

Rules:

1. Do not create a second active child branch while one active child branch already contains unique commits.
2. Finish the active branch before starting another: merge/cherry-pick its intended changes back into `feature_for_agent`, then delete or leave the branch with no unique commits.
3. If an experiment fails, discard/delete that branch before creating the next experiment branch.
4. Do not continue development on historical experiment/benchmark/refactor branches. They are frozen history. If code must be reused, selectively port it into `feature_for_agent`.
5. A new isolated branch must start from the current `feature_for_agent` HEAD, have one clear purpose, and must not become a second long-lived product line.
6. `feature_for_agent` remains authoritative even while an isolated child exists. The child is temporary work, not a competing current version.

The policy baseline is commit:

```text
746605127cdff6e2a8149eca8cb6944d6868c605
```

Branches whose divergence from `feature_for_agent` predates this baseline are grandfathered historical branches. They are excluded from the active-child count only so existing history does not need to be deleted immediately; they are **read-only** under this process and must not receive new development commits.

## Expected workflow

Normal change:

```text
feature_for_agent
  -> small commit
  -> focused tests
  -> Core CI / relevant benchmark
  -> next commit
```

Risky isolated change:

```text
feature_for_agent
  -> one temporary child branch
  -> implement + validate
  -> merge/cherry-pick back into feature_for_agent
  -> retire the child branch
  -> only then may another child branch be created
```

Release/stabilization:

```text
feature_for_agent
  -> validated stable state
  -> merge/promote to main
```

## Automated guard

`.github/workflows/branch-topology-guard.yml` checks the repository branch topology on every branch push and on manual dispatch.

The guard fails when:

- more than one post-baseline child branch contains commits not present in `feature_for_agent`; or
- a new push adds development commits to a grandfathered historical branch.

The guard is a validation signal. Repository branch protection/rulesets should require this check if server-side push blocking is desired.
