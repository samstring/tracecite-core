# TraceCite Project Guardrails

This document defines **development and benchmark governance for TraceCite**. It constrains how TraceCite is designed, implemented, reviewed, and evaluated.

It is **not an investigation playbook for runtime Agents**.

## Scope

These guardrails apply to:

- Core and Runtime design decisions;
- Agent-facing tool contracts and projections;
- skills maintained by this repository;
- benchmark design and interpretation;
- token/context optimizations;
- provenance, identity, replay, and evidence-memory behavior.

They do not decide an Agent's hypotheses, investigation order, causal reasoning, next query, conclusion, or stopping point.

## Primary boundary

> **Agent owns thinking and decisions. TraceCite owns evidence.**

An external Agent owns:

- hypotheses and competing explanations;
- investigation order and which entity/source to inspect next;
- causal reasoning and root-cause conclusions;
- whether a comparison is relevant;
- whether available evidence is sufficient for its task;
- when to stop investigating.

TraceCite may own deterministic evidence operations, including:

- bounded retrieval and exact materialization;
- evidence identity and provenance;
- source/version identity and integrity checks;
- session-scoped novelty and repeated-evidence accounting;
- coverage, truncation, missing-evidence, and execution-state facts;
- mechanically observed identity/correlation constraints;
- exact recall/replay of previously delivered evidence.

TraceCite must not convert those mechanical facts into investigation decisions.

## Runtime semantics may be taught; investigation strategy may not

Agent-facing documentation or skills may explain **how to use TraceCite correctly**. Examples:

- what `new_evidence=0` means;
- what `no_match` means;
- when `regex=true` is required by the API syntax;
- how evidence refs, expand, and replay work;
- what `identifier_only_correlation_safe=false` means;
- what `minimum_safe_correlation_key` means;
- which fields must be supplied if the Agent itself chooses to retrieve a specific scoped identity;
- how provenance, source version, SHA, line/range, or generation fields should be preserved.

Agent-facing documentation or skills must **not prescribe the investigation**. They must not tell an Agent:

- which hypothesis to prioritize;
- which sibling/entity to inspect next;
- that it should compare specific entities;
- that an observed identity collision is probably causal;
- which root cause is likely;
- that evidence is sufficient to conclude the investigation;
- that the Agent should stop.

A useful test is:

> If the instruction remains valid only because we know the benchmark's hidden answer or preferred investigation path, it does not belong in the TraceCite runtime contract or skill.

## Evidence facts are not epistemic conclusions

Mechanical retrieval facts must remain mechanically scoped:

- `new_evidence=0` means the current retrieval exposed no new evidence in this session. It does not mean the investigation is complete.
- `no_match` means the query returned no match in the searched scope. It does not prove the event never occurred.
- incomplete coverage or truncation is not evidence of absence.
- `identifier_only_correlation_safe=false` means the identifier alone is insufficient for safe correlation in the represented evidence. It does not mean the ambiguity caused the incident.
- `observed_sibling_entities` are observed identities/references, not a recommendation to inspect or compare them.
- literal/structural relations are observations, not causal relations.

TraceCite must not rename, summarize, rank, or project these facts in a way that silently turns them into causal or stopping advice.

## Evidence integrity is non-negotiable

Token/context optimization must never destroy the ability to recover and verify evidence.

Required properties:

- material evidence remains attributable to a concrete source/version;
- line/range or equivalent stable location remains available where applicable;
- immutable evidence can be integrity-checked with the appropriate SHA/hash identity;
- mutable/live sources use explicit generation/cursor/cut semantics rather than pretending to be immutable;
- deduplication suppresses repeated delivery, not the canonical evidence itself;
- explicit recall/replay can rematerialize previously delivered evidence exactly when the underlying source contract permits it;
- summaries or compact projections do not replace canonical evidence as the source of truth.

If an optimization saves context by making evidence unverifiable or unrecoverable, it is not an acceptable optimization.

## Bounded context is a product property, not permission to hide evidence

TraceCite should keep model-visible evidence bounded and avoid repeatedly sending evidence already delivered to the same retrieval session.

However:

- output limits must be explicit through coverage/truncation/omission facts;
- relevant evidence must not be silently discarded;
- repeated evidence may be represented by refs/counts instead of bodies, but must remain recallable;
- a compact projection must not invent relevance, causality, or confidence to justify what was omitted.

The goal is **bounded, provenance-aware evidence flow**, not merely smaller tool output.

## Correctness gates token savings

A cost reduction is a product win only when required answer/evidence quality is preserved.

Benchmark interpretation must consider, at minimum:

- answer/root-cause or concept recall appropriate to the case truth grade;
- supported recall / evidence support;
- citation accuracy and unsupported claims;
- model calls;
- tool calls;
- provider-reported input, cached-input, and output fields separately;
- model-visible tool output/context load;
- wall time and timeout/context failures where available.

Do not claim a universal token-saving percentage from a small number of runs.

Do not casually sum provider `input` and `cache_read` fields into a universal "total token" metric unless that provider's accounting semantics make the sum valid.

## Benchmark integrity

Benchmarks must measure TraceCite rather than benchmark-specific coaching.

Required principles:

- A/B arms receive the same problem and the same prepared evidence bytes.
- Model/provider/version, timeout, scoring truth, and base task requirements should be matched unless a difference is intentionally under test.
- Hidden gold/fix information must not leak into the Agent prompt, TraceCite projection, runtime skill, or evidence.
- A TraceCite skill may teach TraceCite API semantics and correct tool usage, but may not encode the preferred investigation path or hidden diagnosis.
- Provider rate limits, quota errors, provider unavailability, and similar infrastructure failures invalidate the affected arm rather than counting as a product loss.
- Capability tests may force TraceCite use when the question is whether the capability works. Product-value A/B tests must label clearly when TraceCite use is forced.
- Correctness/quality gates must be preserved before cost improvements are called wins.

## This document must not become runtime coaching

`docs/PROJECT_GUARDRAILS.md` is a **development-governance source of truth**.

Do not automatically inject this document as:

- a Pi/Agent system prompt;
- a benchmark question or hidden benchmark hint;
- a runtime context file;
- a TraceCite investigation playbook;
- wholesale content inside a runtime skill.

Runtime skills should contain only the subset necessary to explain TraceCite's public semantics and correct API/tool usage.

Benchmark harnesses should continue to isolate runtime Agents from development-governance material when evaluating Agent behavior. For Pi benchmarks, `--no-context-files` (or an equivalent isolation mechanism) is preferred when appropriate.

## Review checklist

Before merging a change that affects Agent-facing behavior, evidence projection, retrieval guidance, or benchmarks, check:

1. Does this change preserve the boundary that the Agent owns reasoning and decisions?
2. Is every TraceCite-produced conclusion still a mechanical evidence/retrieval fact rather than causal advice?
3. Does the change preserve provenance, identity, exact references, and recall/replay guarantees?
4. Does any context/token optimization silently drop or rewrite canonical evidence?
5. Does a skill change teach TraceCite usage, or does it teach the Agent how to solve a class of incidents?
6. Could the change improve a benchmark because it encodes knowledge of the hidden gold or preferred path?
7. Are provider/infrastructure failures separated from product-quality failures?
8. Are quality and evidence support preserved before claiming a cost win?

If a change fails one of these checks, treat it as a design issue rather than compensating for it with benchmark-specific prompting.

## Short form

The three highest-level red lines are:

1. **Do not replace Agent reasoning with TraceCite reasoning.**
2. **Do not sacrifice evidence truth, provenance, identity, or recoverability for convenience or token savings.**
3. **Do not distort product design or Agent behavior to win benchmarks.**
