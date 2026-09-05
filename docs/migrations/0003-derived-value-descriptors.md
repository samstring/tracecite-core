# Migration 0003: bounded derived-value descriptors

## Scope

This migration applies to Agent/Host integrations consuming Runtime Evidence
Compute aggregate results on the `feature_for_agent_refacotr_shell` refactor
branch.

## Change

`group` and `distinct` computations remain exact, but a string key longer than
the derived-value transport threshold (currently 512 characters) is no longer
sent in full. The value is represented by a descriptor:

```json
{
  "preview": "bounded prefix",
  "truncated": true,
  "length": 15844,
  "value_sha256": "...",
  "evidence_ref": "evidence://sha256/<source-sha>#L35754"
}
```

The descriptor is used in the existing `aggregate.values[*]` or
`aggregate.groups[*].key` position. Short values retain their historical
scalar shape. `count`, totals, ordering, coverage, and the source/version
identity are unchanged. A consumer that requires the exact value must use the
Evidence URI as a recovery handle and materialize the referenced source line;
the preview and digest must not be treated as the complete value.

## Compatibility

Consumers must accept `string | descriptor` for distinct values and group keys
when reading Compute results. This is an additive transport-boundary change to
ephemeral Agent results; it does not change persisted schema versions or
canonical source bytes. Integrations that cannot handle descriptors must pin to
the prior branch or reject the result explicitly rather than silently treating
the preview as exact.

The change prevents a single large log/message field from recreating an
unbounded intermediate result at the model boundary while preserving exact
recovery through SourceVersion Evidence.
