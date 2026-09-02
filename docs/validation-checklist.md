# TraceCite validation checklist

Status: current release/change checklist for `feature_for_agent` after the validated CA258 merge.

This checklist validates the current Evidence Runtime architecture. It replaces the old staged “Extension v2 / Mobile / CI” rollout checklist; those migrations are now historical records under `docs/migrations/` and ADRs.

## A. Package and dependency boundaries

- [ ] Python package metadata remains correct (`tracecite`, current version/status, supported Python/platform matrix).
- [ ] `tracecite_core` does not import `tracecite.runtime`, integrations, or domain packages.
- [ ] `tracecite.runtime` does not import concrete domain packages.
- [ ] Domain extensions depend only on public TraceCite contracts.
- [ ] `import tracecite` does not execute unauthorized third-party extensions.
- [ ] Public schema/API changes have migration notes and tests.

## B. Canonical Evidence contract

- [ ] `retrieve`-equivalent behavior returns bounded Evidence with Provenance/Coverage and explicit acquisition-end facts.
- [ ] `materialize` returns exact caller-selected context for the requested source/version/range.
- [ ] `replay` deliberately re-reads old evidence without increasing novelty.
- [ ] `aggregate` remains deterministic and does not become causal ranking.
- [ ] `traverse` stays caller-scoped/mechanical and does not choose the Agent's next investigation direction.
- [ ] `verify` validates integrity/source/version/Manifest facts, not Agent conclusions.
- [ ] Convenience wrappers (`search`, `expand`, etc.) do not own a second evidence/session model.

## C. RetrievalSession and evidence memory

- [ ] RetrievalSession is the single source of truth for seen/repeated evidence and covered immutable ranges.
- [ ] A new query that matches old evidence preserves current-query relevance via refs/metadata without automatically duplicating the body.
- [ ] `new_evidence=0` is not projected as “investigation complete.”
- [ ] Explicit replay/materialization can recover already-delivered evidence.
- [ ] Source generation/version changes cannot silently reuse stale evidence identity.
- [ ] Unknown/unaddressable evidence is not silently deduplicated.
- [ ] RetrievalSession does not store/infer hypotheses, root cause, sufficiency, or stop decisions.

## D. Coverage, provenance, and identity safety

- [ ] Bounded/truncated/lossy projections expose Coverage/omission/truncation/recovery facts.
- [ ] Zero match remains scoped retrieval output, not proof of global absence.
- [ ] Material evidence keeps source/version and stable line/range or equivalent provenance.
- [ ] Immutable evidence can be integrity-checked with hash identity where required.
- [ ] Correlation safety fields remain mechanical identity constraints, not causal hints.
- [ ] Entity timelines are not collapsed from unsafe identifiers, nearby addresses, or filename proximity alone.

## E. Agent/Host boundary

- [ ] Agent owns hypotheses, causal reasoning, sufficiency, final answer, and stopping.
- [ ] Runtime does not emit `root_cause_confidence`, `evidence_sufficient`, `next_best_query`, or `stop_recommended` as evidence truth.
- [ ] Host tool telemetry is clearly separated from canonical Evidence.
- [ ] Optional Host checkpoints report mechanical activity/budget facts only.
- [ ] Pi integration remains compatible with `.pi/skills/tracecite/SKILL.md` and the exposed TraceCite tool contract.
- [ ] Codex/OpenAI-compatible workflow remains discoverable through `AGENTS.md` + `.agents/skills/tracecite-investigate/SKILL.md`.
- [ ] Cursor project rule stays synchronized with the same evidence/trust boundary.

## F. Context Engine / Ledger

- [ ] Canonical Result is recoverable before Context Delta is applied.
- [ ] Context state is host-scoped transport memory, not Evidence or InvestigationState.
- [ ] Seen Evidence is omitted only when recoverable and omission is explicit.
- [ ] Delta is selected only when it is actually smaller than the normal projection.
- [ ] Different context IDs do not leak seen-state across investigations.
- [ ] `expand-many` or equivalent recovery can rematerialize exact evidence ranges from Ledger results.

## G. Extension boundary

- [ ] `TraceCiteExtension`/capability contracts remain versioned and domain-neutral at the top level.
- [ ] Extensions may provide domain facts/capabilities but not model-specific token policy or RetrievalSession seen-state.
- [ ] DomainEvent remains a fact representation, not a root-cause/relevance verdict.
- [ ] Live source/action capabilities remain explicitly authorized and fail closed.
- [ ] Capability/version collisions fail deterministically without partial registration.

## H. Knowledge trust

- [ ] Agent conclusions do not auto-promote to trusted Knowledge.
- [ ] A conclusion cannot serve as its own independent validation.
- [ ] Knowledge Candidate -> validation -> review -> version/expiry remains auditable.
- [ ] Knowledge may recommend future hypotheses/tests/presets but never replaces current-incident Evidence.

## I. Tests and platform validation

- [ ] Run focused tests for every changed subsystem.
- [ ] Run dependency/architecture tests for layer-boundary changes.
- [ ] Run evidence identity/coverage/replay tests for Runtime changes.
- [ ] Run Pi/Host boundary tests for Agent integration changes.
- [ ] Run supported Python/platform CI relevant to the changed package surface.
- [ ] No warning/error path emits an unstructured half-result where a structured contract is required.

## J. Agent benchmark validity

For product-efficiency claims:

- [ ] Use paired conditions with the same model and shared base prompt.
- [ ] Record exact case/model/prompt/tool configuration.
- [ ] Separate `task_result` from `run_validity`.
- [ ] Treat 429/quota/provider unavailable/harness failure as infrastructure-invalid, not model/product failure.
- [ ] Evaluate answer quality/evidence support/overclaim before token/tool metrics.
- [ ] Preserve raw scorer output; document known scorer false positives/false negatives rather than silently editing scores.
- [ ] Report input/output/cache/model/tool usage consistently.
- [ ] Do not claim a universal saving percentage from one benchmark suite.

Current validated measurements are documented in `docs/benchmark-results.md` and `docs/benchmark-results.zh-CN.md`.

## K. Documentation governance

- [ ] `README.md` and `README.zh-CN.md` describe the current implementation, not old experiment branches.
- [ ] `docs/architecture.md` and `docs/architecture.zh-CN.md` are updated together for architecture-boundary changes.
- [ ] `docs/agent-integration*.md` matches the current Pi/Codex/Cursor integration surfaces.
- [ ] Benchmark claims link to exact run IDs and preserve caveats.
- [ ] Temporary experiment/handoff/refactor-plan notes do not live in the current documentation set.
- [ ] ADRs/migrations remain historical records and are not rewritten to masquerade as current status.
- [ ] `docs/README.md` remains the current documentation map.
