# Knowledge governance

TraceCite separates agent proposals from trusted domain knowledge. The main
distribution provides a domain-neutral lifecycle; extensions decide how a
verified candidate is materialized.

```text
proposal + evidence
        ↓
candidate store
        ↓ independent case
verified / contradicted
        ↓ distinct reviewer
promoted by domain adapter
```

The public API is `tracecite.knowledge`:

- `KnowledgeGovernanceStore.propose()` requires a case id and Evidence refs.
- `verify()` rejects duplicate case ids. Two supporting independent cases are
  required by default; any contradiction blocks promotion.
- `promote()` requires a reviewer distinct from the creator and invokes a
  domain adapter only after the managed target passes its SHA-256 check.
- `check_target()` detects formal knowledge changed outside promotion.

Candidate files and trusted knowledge must be physically separate. Atomic JSON
writes prevent torn state, but the store intentionally contains no Mobile, CI,
product, or company semantics.

Direct domain write functions may remain available as adapter internals for
compatibility. Agent-facing hosts must expose proposal/verification/promotion,
not those internal mutation functions.
