# Persisted-schema compatibility governance

TraceCite records its compatibility promise in the stdlib-only registry at
`src/tracecite/runtime/schema_compat.py`.  The registry is deliberately
separate from public schema implementations: it declares the current version,
the reader used to validate a fixture, any supported legacy versions, and the
fixture that proves each declaration.

Run the check from a checkout with:

```sh
python scripts/check_schema_compat.py
```

The command prints a sorted, machine-readable JSON report and exits non-zero
when a source constant, fixture, reader, or migration declaration drifts.  The
same command is suitable for CI; it has no network or third-party dependency.

## What is covered

The registry currently covers:

- the versioned `AgentResult` transport envelope (ephemeral, not an on-disk
  store);
- the versioned `InvestigationSummary` advisory envelope (ephemeral, not an
  investigation state file);
- versioned scenario input documents;
- versioned run manifests;
- the records and hits JSONL filter artifacts, classified as unversioned
  additive artifacts;
- `InvestigationState`, its nested `BudgetPolicy`, and its cache sidecar;
- `KnowledgeGovernanceStore`, including the explicit v1-to-v2 migration.

Filter JSONL deliberately has no invented schema version or migration.  New
provenance fields are additive and old readers continue to consume the rows;
an incompatible change must first add an explicit version and a migration
fixture.  `InvestigationSummary` and similar in-memory reports are derived,
ephemeral values.  The summary is listed only because it is a public,
versioned output; it is not an on-disk state file or granted a migration
promise.

## Compatibility rules

Every versioned entry names a source constant and has a current-version golden
fixture.  A legacy version is only supported when its fixture, reader, and
migration handler are all declared.  The checker invokes the existing public
reader and, for legacy entries, migrates a temporary copy and verifies that it
lands on the current version.  It does not inspect Git history, infer versions
from prose, or silently rewrite user data.

When a persisted schema changes incompatibly, update the registry, add a
deterministic fixture for the old version and its migration, and add a focused
note in this directory.  Additive unversioned metadata changes should instead
document why old readers remain valid; do not claim a migration that does not
exist.
