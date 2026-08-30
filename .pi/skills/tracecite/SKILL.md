---
name: tracecite
description: Use TraceCite correctly when investigating large local logs or text evidence. Prefer TraceCite for bounded evidence discovery, novelty-aware retrieval, exact expansion, and replay; avoid duplicating the same retrieval with grep/read unless independent verification or unsupported processing is actually needed.
compatibility: Requires the tracecite_search and tracecite_expand tools from the TraceCite Pi extension.
---

# TraceCite Evidence Workflow

TraceCite is an evidence-retrieval layer for an Agent. It does not decide hypotheses, root cause, investigation order, or when to stop. You own those decisions.

## When to use TraceCite

For large logs or text evidence, use TraceCite as the primary content-retrieval path when you need to locate relevant evidence without placing broad raw output into model context.

It is fine to use cheap native commands for metadata such as file names, file size, or line count. Avoid broad `cat`, `head`, `grep`, or large `read` calls as the first evidence-discovery step when TraceCite can answer the same retrieval question with bounded output.

For very small files, native `read` may be cheaper unless the task or benchmark explicitly requires TraceCite.

## Core workflow

1. **Orient cheaply.** If useful, inspect only metadata such as `ls -lh` or `wc -l`.
2. **Discover with `tracecite_search`.** Search for an error signature, stable identifier, state transition, component name, or other query chosen from your current hypothesis.
3. **Read the retrieval facts.** Pay attention to evidence refs, `coverage`, `progress`, `new_evidence`, `repeated_evidence`, correlation constraints, and missing-evidence facts.
4. **Materialize exact evidence with `tracecite_expand`.** Expand the relevant line when you need exact source text or line-addressable support for a factual claim.
5. **Continue reasoning yourself.** Change the hypothesis/query only when the investigation calls for it. TraceCite does not tell you what the root cause is or whether you have enough evidence.
6. **Replay instead of re-fetching.** If you intentionally need to re-read previously exposed exact context, use `tracecite_expand(..., replay=true)` rather than re-running native retrieval for the same text.

## Novelty and deduplication

`new_evidence=0` with repeated evidence means the current TraceCite call exposed no new evidence in this retrieval session. It does **not** mean the investigation is complete.

When this happens:

- Do not mechanically repeat near-synonym searches for the same evidence.
- Reuse the evidence refs you already have.
- Use `tracecite_expand` if you need exact context from a known ref.
- Use `replay=true` only when you deliberately need old context again.
- If you continue searching, do so because you are testing a materially different hypothesis, identity, source region, or evidence need.

## Avoid duplicate retrieval paths

Once TraceCite has already exposed evidence, do not immediately use native `grep` or `read` to fetch the same content again merely for convenience. That defeats session deduplication and increases model context.

Use native tools for evidence content only when there is a concrete reason, for example:

- TraceCite cannot express the needed transformation or structural query.
- You need an independent verification of a critical observation.
- You need metadata or a computation over the file rather than textual evidence retrieval.
- TraceCite reports a gap that native tooling can resolve more directly.

If you use native verification, keep it narrow and avoid dumping large matching sets into context.

## High-fanout searches

If a search matches many sibling events or repeated errors, narrow the query using stable identities that are already present in the evidence, such as a pod/container/request/process identifier. Treat TraceCite correlation constraints as identity-safety facts, not causal conclusions.

Do not infer that two events are the same entity merely because they share a generic error string.

## Evidence semantics

- A search hit is an observation, not proof of causality.
- `observed_relations` are literal textual/structural co-observations, not root-cause claims.
- `source_sha256` identifies an immutable source version when available; reuse it for exact replay/expansion when appropriate.
- Replayed text is old evidence being re-read; it is not new evidence.
- Missing evidence is a retrieval fact. State insufficiency explicitly rather than inventing a deeper cause.

## Citation discipline

Use exact line numbers from materialized evidence for material factual claims. Compact search previews are useful for discovery, but use `tracecite_expand` or a narrow native read before making an exact claim if the full supporting text has not yet been materialized.

## Efficiency target

The goal is not to maximize TraceCite calls. The goal is to minimize unnecessary evidence text and repeated retrieval while preserving enough exact evidence for sound Agent reasoning.

A healthy large-file path usually looks like:

`cheap metadata -> tracecite_search -> targeted tracecite_expand -> reasoning -> only materially new search/expand if needed`

not:

`broad grep/read -> tracecite_search -> tracecite_expand -> broad grep/read of the same evidence -> repeated near-synonym searches`.
