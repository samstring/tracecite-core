---
name: tracecite
description: Use TraceCite as bounded evidence transport and mechanical evidence memory. TraceCite retrieves/materializes supplied evidence with provenance; the Agent owns interpretation, hypotheses, causal reasoning, sufficiency, root cause, and stopping.
compatibility: Requires the TraceCite Pi extension. tracecite_search/tracecite_expand may be exposed as compatibility aliases for retrieval/materialization.
---

# Evidence contract

```text
TraceCite = retrieve + materialize + provenance + mechanical evidence memory
Agent     = interpret + infer + decide sufficiency + stop
```

TraceCite Runtime does not choose hypotheses, causal importance, root cause, investigation direction, or stopping. Evidence mechanics may reduce repetition, but token saving never overrides correctness.

# Evidence boundary

Only supplied artifacts are evidence when the task is scoped to supplied evidence. Model memory, guessed source code, web knowledge, likely fixes, inferred implementation details, or unstated external state may suggest a question but cannot close a material claim unless the supplied artifacts support it.

Keep observation and inference distinct:

```text
observed            = directly present in materialized supplied evidence
supported_inference = follows from supplied evidence without a material contradiction
bounded_unknown     = the supplied evidence cannot establish the detail
```

Do not treat:

```text
search match          == causal proof
frequency/rank        == causal importance
file/line order       == global happens-before or causality
nearby values         == same identity
absence of a match    == global absence
```

A search preview or navigation hint is a coordinate, not a causal conclusion. Materialize the minimum context needed before relying on a multi-line record, stack, traceback, transaction, or other structured evidence body.

# Claim-driven investigation

Keep the investigation bounded. Once the root cause is sufficiently supported by the supplied evidence and source-code verification, answer immediately instead of performing confirmatory searches.

Track only the smallest set of material claims required by the user's question. A TraceCite call is justified only when it targets one unresolved or contradicted material claim, or materializes an already-identified range needed to settle that claim.

Before each TraceCite call identify internally the one material claim still unresolved or contradicted and the concrete discriminator that could change or settle it. Before every additional TraceCite retrieval, also emit a concise retrieval justification in this form:

```text
claim: the one root-cause-relevant fact still unresolved or contradicted
discriminator: the concrete evidence that could change or settle that claim
```

This is a bounded tool-use justification, not a request for private chain-of-thought. Keep it short and specific. If either field cannot be named, or if no root-cause-relevant question remains unanswered, do not call TraceCite again; answer with the supported conclusion and any explicit boundary.

For one claim:

```text
1. Search for the strongest discriminator.
2. Materialize only the minimum representative context needed.
3. Update the claim from the supplied evidence.
4. Stop querying it once it is observed, supported_inference, or bounded_unknown.
```

Claim identity is semantic, not query wording. Synonyms do not create new claims. A new hint, cluster, subsystem, rare signal, or co-occurring symptom does not create a new material claim by itself.

After two consecutive non-advancing attempts for the same semantic claim, stop reformulating it. Mark it `bounded_unknown` or qualify the conclusion instead of continuing a census.

# Bounded evidence transport

- Prefer one strongest representative instance per distinct causal role; equivalent examples are not additional proof unless multiplicity is material to the question.
- `tracecite_search`: keep inline evidence bounded; request at most 12 items unless the user's question explicitly requires broader enumeration.
- `tracecite_expand`: normally keep radius <= 16 and widen only when the material claim requires context cut off by the first expansion.
- Reuse known evidence refs, ranges, source paths, source identities, and immutable source generations.
- `status=no_match` is request-local, not global absence.
- `status=no_new_evidence`, matched-existing evidence, duplicate requests, and covered ranges are mechanical facts; do not refetch them for confidence.
- In TraceCite-only mode, do not retry blocked native evidence access.

# Causal closure and stopping

For root-cause work, build the smallest causal proof that answers the question. Close the mechanism/direct-impact claims required by the user before expanding into secondary symptoms. Do not substitute evidence volume for causal closure.

A claim may close as `supported_inference` when supplied evidence establishes the needed relation strongly enough and no material supplied evidence contradicts it. State inference as inference rather than pretending it was directly observed.

If the supplied artifact cannot represent a requested later or external state, stop at the last supported in-artifact transition and mark the rest `bounded_unknown` or explicitly qualify it. Do not invent a bridge merely to make the story complete.

Stop when every material claim required by the question is `observed`, `supported_inference`, or `bounded_unknown`, with no unresolved material contradiction.

When that becomes true, the next assistant action must be the final answer. Do not perform a reassurance search, broader census, or verification turn merely for confidence.

Every material causal statement in the final answer must correspond to a closed claim:

```text
observed            -> state as fact
supported_inference -> state as conclusion/inference
bounded_unknown     -> qualify explicitly
unresolved          -> do not present as established
contradicted        -> resolve or qualify
```

For root-cause questions, keep the answer to the minimum supported mechanism, causal path(s), direct impact, evidence citations, and any explicit evidence boundary.

# Runtime boundary

TraceCite Runtime may remember evidence identities, ranges, source generations, novelty, coverage, diversity, and repetition. It does not know hypotheses, causality, proof claims, root cause, sufficiency, or stopping.
