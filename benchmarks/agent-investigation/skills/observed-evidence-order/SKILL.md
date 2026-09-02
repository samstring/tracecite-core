---
name: observed-evidence-order
description: Treat source line positions as observed artifact output order only. Use them as chronology hints without turning presentation order into execution order or causality.
---

# Observed evidence order

When evidence comes from the same source artifact and has source line/range coordinates, preserve and compare that source order.

Interpret it narrowly:

```text
lower source line/range -> appears earlier in this artifact
higher source line/range -> appears later in this artifact
```

This is **observed output order**, not automatically execution order, lock-acquisition order, global happens-before, or causal order.

Use source order as a chronology hint that can help organize evidence and reject impossible narratives, but require additional evidence before converting it into an execution or causal claim.

Prefer stronger ordering evidence when available, for example:

```text
explicit timestamps
same request/session identity
same thread/goroutine execution progression
explicit lifecycle/state transition
```

Important limits:

- Different goroutines/threads may be printed in an arbitrary or presentation-oriented order.
- Stack-dump frame order is not lock acquisition order.
- Buffered or asynchronous logging may make output order differ from real execution completion order.
- Line order across different source artifacts is not comparable unless another shared ordering signal establishes the relation.

When reasoning from line order, phrase the mechanical fact internally as:

```text
A appears before B in the same supplied artifact
```

Do not silently upgrade that fact to:

```text
A executed before B
A caused B
A's lock was acquired before B's lock
```

The Agent owns those inferences and must justify them from the supplied evidence.
