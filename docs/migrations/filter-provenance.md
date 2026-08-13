# Filter provenance migration note

This additive change keeps the existing final `pattern`, filtered artifacts,
and run schema version stable. New consumers may read:

- `FilterResult.pattern_components` and `matched_by_counts`;
- per-record/hit `metadata.matched_by`;
- scenario/run `filter` provenance (`match_mode`, `components`, `preset`, and
  optional `scenario` metadata).

`matched_by` is deterministic and may contain multiple component IDs. A Core
call without component declarations uses the reserved `pattern` fallback and
sets `matched_by_fallback=true`. Scenario resolvers that replace an expression
report the resolved `scenario:<name>` component as effective and retain
preset/grep as provenance-only inputs.

Preset version/source/hash values are optional; absent versions are serialized
as `unknown`. Long IDs and metadata are bounded and carry `*_truncated` flags.
Existing readers can ignore the additive fields. New readers should prefer the
canonical run `filter` object and use the historical top-level final `pattern`
only for compatibility display.
