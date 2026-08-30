---
name: tracecite
description: Use TraceCite as an evidence-retrieval tool for large or repetitive local text/log sources. Understand when search, expand, replay, or native tools are appropriate, and avoid retrieving the same evidence twice without a concrete reason.
compatibility: Requires the tracecite_search and tracecite_expand tools from the TraceCite Pi extension.
---

# TraceCite Evidence Retrieval

TraceCite retrieves and materializes evidence. You remain responsible for hypotheses, investigation order, causal reasoning, conclusions, and when to stop.

The goal is not to maximize TraceCite calls. Choose the cheapest retrieval path that preserves enough exact evidence for sound reasoning.

## Tool selection

| Need | Prefer |
| --- | --- |
| List files, inspect size/line count, or inspect directory structure | native `ls`, `find`, `wc` |
| Read a very small file directly | native `read` |
| Locate relevant evidence in a large or repetitive text/log source | `tracecite_search` |
| Materialize exact context around a known hit | `tracecite_expand` |
| Re-read context already exposed in this retrieval session | `tracecite_expand(..., replay=true)` |
| Compute, aggregate, transform, sort, count, or perform a structural query TraceCite does not express | native shell/tools |
| Independently verify a critical observation | narrow native `read`/`grep` when useful |

Avoid broad native output when a bounded evidence query would answer the same question with substantially less context.

## Normal workflow

1. Orient with cheap metadata if needed.
2. Use `tracecite_search` when bounded discovery is useful.
3. Inspect evidence refs, coverage, novelty, correlation constraints, and missing-evidence facts.
4. Use `tracecite_expand` for exact line-addressable context needed to support a claim.
5. Continue the investigation only according to your own reasoning and evidence needs.
6. If old exact evidence must be reconsidered, replay it instead of rediscovering it.

## Novelty and repeated evidence

`new_evidence=0` means this retrieval exposed no new evidence in the current session. It does not mean the investigation is complete.

If the needed evidence was already seen:

- reuse its existing ref;
- use `tracecite_expand` for exact context;
- use `replay=true` when intentionally re-reading already exposed text;
- do not run a near-synonym search merely to retrieve the same evidence again.

Run another search when the evidence target materially changes, for example to a different entity, identifier, time region, error class, state transition, source region, or hypothesis-specific observation.

## Avoid duplicate retrieval paths

After TraceCite has exposed evidence, do not immediately fetch the same text again with native `grep` or `read` unless there is a concrete reason.

Good reasons include:

- independent verification of an important observation;
- a transformation, aggregation, or structural query TraceCite cannot express;
- resolving a retrieval gap more directly with a native tool.

Keep native verification narrow. Large duplicate outputs increase context without adding evidence.

## High-fanout searches

When a query matches many repeated or sibling events, narrow it with stable identities already observed in the evidence, such as pod, container, request, process, or other scoped identifiers.

Treat correlation constraints as identity-safety facts, not causal conclusions. A shared generic error string does not prove that two events belong to the same entity.

## Evidence semantics

- A search hit is an observation, not proof of causality.
- `observed_relations` describe literal textual or structural co-observation, not root cause.
- `source_sha256`, when present, identifies the source version associated with the evidence and can be reused for exact expansion/replay.
- Replayed text is old evidence being re-read; it is not new evidence.
- Missing evidence is a retrieval fact. Do not invent a deeper cause when support is absent.

## Exact claims

Use exact line numbers from materialized evidence for material factual claims. Search previews are for discovery; use `tracecite_expand` or a narrow native read when the full supporting text has not yet been materialized.
