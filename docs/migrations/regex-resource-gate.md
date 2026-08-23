# Regex resource-gate migration note

TraceCite now applies a bounded structural check before built-in filtering,
segmentation, preprocessing, and assertion paths execute a user-supplied
regular expression. This does not change a persisted schema, but it tightens
accepted input behavior: oversized expressions and known catastrophic
backtracking shapes such as nested variable repetitions may raise `re.error`
before any source is scanned.

Ordinary literals, date patterns, bounded repetitions, optional wrappers, and
prefix-disjoint alternatives remain supported. Callers affected by the gate
should prefer literal search when regex semantics are unnecessary, or rewrite
ambiguous nested repetitions into a single bounded expression. Runtime
assertions retain their existing invalid-regex literal fallback.

The gate is a resource guardrail, not a proof that every accepted expression
runs in linear time. Custom extension handlers that execute regexes remain
responsible for applying equivalent bounds to their own inputs.
