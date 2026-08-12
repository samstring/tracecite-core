---
name: tracecite-review-knowledge
description: Review, verify, approve, reject, or defer proposed TraceCite knowledge without contaminating the trusted store. Use when an Agent discovers reusable terms, markers, scenarios, learnings, playbooks, patterns, or diagnostic claims, or when a user asks what should enter a knowledge base. Do not use for ordinary evidence investigation unless knowledge promotion is being considered.
---

# TraceCite Knowledge Review

Keep automated discoveries in a candidate store. Promote only a scoped, evidence-backed candidate that has independent verification and explicit user approval.

## Keep candidates separate

- Treat frequency, repetition, and model confidence as discovery signals, not proof of knowledge.
- Use the domain adapter's governed `propose`, `verify`, and `promote` operations. Never call direct knowledge-write helpers or edit the trusted JSON file.
- Keep the candidate and trusted stores physically separate.
- Preserve the candidate's creator, scope, semantic claim, evidence references, cases, supporting outcomes, contradictions, and decision history.
- Never let an Agent-generated conclusion verify itself.

## Sanitize before proposal

Reject or redact candidates containing secrets, tokens, cookies, credentials, personal identifiers, device identifiers, phone numbers, email addresses, UUID-like values, encoded payloads, Base64-like fragments, or high-entropy strings.

Reject or defer candidates that are merely:

- Generic framework, product, or organization names.
- Common implementation words without stable diagnostic meaning.
- A raw value tied to one user, device, request, or incident.
- A semantic duplicate of existing knowledge.
- Unsupported interpretations inferred only from token frequency.

Do not turn a redacted value into a broader rule unless the broader rule has its own evidence.

## Verify independently

1. Propose the candidate with bounded, hash-addressed evidence from its first case.
2. Seek a separate case that did not inherit the first case's conclusion.
3. Record the second case as support, contradiction, or inconclusive. Do not count duplicate evidence as an independent case.
4. Search for counterexamples and applicability limits.
5. Keep the candidate unverified when coverage or semantics remain ambiguous.
6. Block promotion on any unresolved contradiction.

Two occurrences in one source are one case. Two dates, files, users, or runs are independent only when they represent genuinely separate observations.

## Ask the user before promotion

Before any `promote` call, show:

- Candidate ID, kind, proposed value, and semantic meaning.
- Intended domain and scope.
- Supporting and contradicting cases.
- Evidence URIs and coverage.
- Missing evidence, privacy concerns, and over-generalization risks.
- The exact trusted-store change that promotion would make.

Ask the user to choose `approve`, `approve with changes`, `defer`, or `reject`.

- On `approve`, require an explicit reply tied to the displayed candidate and change.
- On `approve with changes`, update and re-review the candidate before promotion.
- On `defer`, retain it only in the candidate store.
- On `reject`, record the reason when the adapter supports it, so the same noise is not repeatedly suggested.
- On silence, ambiguity, or unrelated confirmation, do not promote.

The current reviewer name is not proof of human authorization. Never invent values such as `human-reviewer`, never claim approval occurred without the user's explicit decision, and never automatically call `promote`. If the host cannot provide trustworthy approval, leave the candidate pending and give the user the safe next command or action.

## Complete promotion safely

1. Confirm the candidate is verified and contradiction-free.
2. Confirm the approver is distinct from the creator.
3. Recheck the trusted store's integrity immediately before promotion.
4. Promote only the approved candidate and scope.
5. Recheck integrity afterward and report the resulting candidate status, target path, and digest.
6. Stop analysis if the trusted store is missing, modified outside governance, or otherwise fails closed.

Read `../../../docs/knowledge-governance.md` for the governance API and persistence contract. Read `../../../docs/knowledge-governance.zh-CN.md` when Chinese guidance is preferable.
