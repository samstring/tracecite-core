# Architecture governance checks

Run the repository checks locally with:

```bash
python scripts/check_architecture.py
python scripts/check_schema_compat.py
```

Both checkers use only the Python standard library and accept `--root` when a
checkout or test fixture is elsewhere. The architecture checker verifies:

- relative Markdown targets and Markdown fragments stay valid;
- the English and Chinese implementation-status tables have the same row
  shape and broad status categories (`implemented`, `partial`, or `pending`);
- ADR names, metadata status values, and required template sections follow
  [`docs/adr/README.md`](adr/README.md); and
- Core/Runtime imports preserve the documented dependency direction without a
  company or domain-specific banned-word list.

It intentionally does not inspect git history or infer migrations from diffs;
those checks are too prone to false positives for a deterministic local gate.
Instead, the schema checker validates an explicit registry of persisted and
transport schemas, their source version constants, bounded golden fixtures,
readers, and declared migration handlers. Unversioned additive artifacts are
registered as such rather than assigned an invented schema version. See the
[schema compatibility policy](migrations/schema-compatibility.md).

Both commands run in CI before the full Core pytest suite. Governance tests
also exercise temporary failing fixtures for each check:

```bash
python -m pytest tests/test_architecture_governance.py
python -m pytest tests/test_schema_compat.py
```
