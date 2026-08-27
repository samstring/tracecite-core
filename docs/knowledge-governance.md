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
  domain adapter only after the managed target passes its SHA-256 check. It
  records bounded validity metadata: source/tool/schema versions, reviewer and
  review time, optional expiry/revalidation times, and opaque JSON conditions.
- `check_target()` detects formal knowledge changed outside promotion.
- `evaluate_validity()` and `is_current()` make trust explicit: promoted
  knowledge can be `current`, `stale`, `expired`, or `superseded`, and only
  `current` is usable. Expired or revalidation-due records are never silently
  trusted; Core does not interpret domain conditions.
- `revalidate()` is an explicit independent review that refreshes validity
  metadata and keeps bounded review history. Omitted expiry/revalidation
  deadlines are cleared by the new review; semantic changes use
  `supersede()` (or `propose(..., supersedes=...)`), which creates a new
  version and preserves the old payload and lineage instead of mutating it.
  For a merely proposed/verified predecessor, the old untrusted candidate is
  marked superseded immediately; for a promoted predecessor, it remains
  current until the replacement itself is successfully promoted.
- Every store read-modify-write is protected by a cross-process lock beside
  the JSON file. Successful promotion and supersession are idempotent, so
  concurrent retries do not invoke a domain promoter twice or create a second
  version.

Candidate files and trusted knowledge must be physically separate. Atomic JSON
writes prevent torn state, and the lock closes the cross-investigation lost
update window. The store intentionally contains no Mobile, CI, product, or
company semantics.

The current governance schema is v2. A v1 store is read with compatibility
defaults (`unknown` source/tool/schema versions, legacy promotion time as the
review time, version 1, and no lineage); call `KnowledgeGovernanceStore.migrate()`
to persist the upgrade under the same lock. Metadata is bounded and JSON-only;
unknown validity keys, invalid timestamps, oversized values, and malformed
candidate records fail validation instead of being trusted.

Investigation Runtime exposes an explicit
`InvestigationStore.propose_knowledge_candidate()` bridge. It accepts only a
`supported` Finding with supporting Evidence and a related Test; `unknown` and
`contradicted` Findings are not eligible reusable claims. The bridge writes the
candidate through `KnowledgeGovernanceStore.propose()` first, then records only
the candidate ID, Finding ID, store link, and status in InvestigationState. A
proposal failure therefore leaves no state link, and repeating a proposal for
the same Finding reuses the existing candidate rather than creating a duplicate.
The payload retains caller-supplied applicability/exclusions, both supporting
and contradicting refs, Coverage/limitations, Test strategies/recipes, and the
source investigation schema/revision for independent review.

Proposal Evidence refs must use the immutable pointer form currently emitted by
Runtime: `evidence://sha256/<64-hex-digest>#L<start>[-L<end>]`, with a valid
one-based range. Manifest refs are intentionally not accepted until a versioned
manifest URI contract is defined. Reusing an existing proposal compares the
normalized payload and all stable identity fields (`kind`, `domain`, `scope`,
creator, and case); parameter drift, including a different candidate-store path,
returns a conflict instead of silently reusing the old proposal.

The status stored in InvestigationState is a link-time snapshot. Independent
review, revalidation, supersession, or promotion updates the candidate store
only; it does not silently rewrite InvestigationState. Hosts that need current
status should explicitly fetch the candidate and call `evaluate_validity()`.
`usable: false` is a deliberate stop signal, not evidence that the claim is
false. A superseded candidate remains addressable for audit, while its
replacement carries the next version and `supersedes` link.

Direct domain write functions may remain available as adapter internals for
compatibility. Agent-facing hosts must expose proposal/verification/promotion,
not those internal mutation functions.
