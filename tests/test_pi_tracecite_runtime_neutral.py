from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
IMPL = ROOT / "benchmarks" / "agent-investigation" / "pi_tracecite_extension_impl.ts"
SKILL = ROOT / ".pi" / "skills" / "tracecite" / "SKILL.md"
SMOKE = ROOT / ".github" / "workflows" / "pi-tracecite-mode-containerd-smoke.yml"


def test_tracecite_runtime_returns_evidence_without_investigation_policy() -> None:
    text = IMPL.read_text(encoding="utf-8")
    assert "agent_feedback" not in text
    assert "convergence_checkpoint" not in text
    assert "checkpoint_required" not in text
    assert "investigation_goal" not in text
    assert "reassess_before_next_evidence_call" not in text
    assert "next_evidence_call_requires_investigation_goal" not in text
    assert 'content: [{ type: "text" as const, text }]' in text


def test_agent_projection_keeps_only_bounded_mechanical_metadata() -> None:
    text = IMPL.read_text(encoding="utf-8")
    assert "function compactCoverage" in text
    assert "function compactProgress" in text
    assert "function compactMatchedExisting" in text
    assert '"unmatched"' not in text
    assert '"consecutive_no_growth"' in text
    assert "neutralPreview" in text


def test_path_errors_expose_only_configured_source_inventory() -> None:
    text = IMPL.read_text(encoding="utf-8")
    assert "function availableSources" in text
    assert "TRACECITE_EVIDENCE_FILES" in text
    assert "available_sources: sources" in text
    assert "recommended_source" not in text
    assert "next_source" not in text


def test_skill_keeps_waiter_holder_and_current_ownership_boundary_in_skill_only() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "`blocked at acquire(X)` proves only `waits X`; it never proves `holds X`" in skill
    assert "If (3) is no, no waiter may be called a holder" in skill
    assert "turns a waiter into a holder" in skill
    assert "Current lock holder/ownership is not established by this artifact" in skill
    assert "blocked at acquire(X)" not in runtime
    assert "current ownership" not in runtime


def test_skill_separates_structural_lock_order_from_current_holder_identity() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "Structural reciprocal discriminator" in skill
    assert "two observed stack paths directly show reversed component nesting across two distinct synchronization domains" in skill
    assert "This establishes only the structural inversion. It does **not** establish current holder identity or a current deadlock cycle" in skill
    assert "a structural reciprocal lock-order statement only if both reversed component paths were directly observed" in skill
    assert "structural lock-order proof" not in runtime
    assert "opposite nested acquisition paths" not in runtime


def test_skill_enforces_artifact_lifecycle_boundary_and_deletion_gate() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "## 4. Lifecycle boundary" in skill
    assert "External process creation, shim/runc state, RPC completion, retries, cleanup/reaping, termination progress, and restart recovery require independent `event_capable` evidence" in skill
    assert "Do not write a lifecycle story and then add this caveat" in skill
    assert "A caveat cannot repair an earlier unsupported assertion. Remove the assertion and every downstream consequence that depends on it" in skill
    assert "artifact boundary" not in runtime.lower()


def test_skill_owns_terminal_claim_classification_and_downgrade() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "## 5. Terminal answer gate" in skill
    assert "Exploratory reasoning is disposable. Before finalizing, discard it and rebuild only from the allowed claim ledger" in skill
    assert "No other causal class is allowed without stronger supplied evidence" in skill
    assert "Forbidden promotions" in skill
    assert "bounded_unknown" not in runtime


def test_skill_has_pre_call_claim_discriminator_and_causal_priority() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "Before each TraceCite call identify one unresolved claim and one discriminator" in skill
    assert "If the next call cannot change the supported conclusion, stop" in skill
    assert "Once one cross-component path is found, search only for the reverse component nesting" in skill
    assert "Prefer symbols/call-chain structure over addresses and waiter counts" in skill
    assert "No equivalent-waiter census" in skill
    assert "discriminator" not in runtime


def test_skill_execution_card_forces_symbol_directed_reverse_search_and_terminal_output() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "## Execution card — obey before any retrieval" in skill
    assert "Use at most two orientation calls to locate one representative domain-specific blocked stack" in skill
    assert "stop broad discovery queries such as `goroutine`, `Lock`, `semacquire`, `metadata`" in skill
    assert "Every remaining causal-discriminator retrieval must target exact symbols/call-chain structure that could expose the **reverse component nesting**" in skill
    assert "A call that only returns the same blocked acquisition direction is non-advancing" in skill
    assert "After two non-advancing reverse-path attempts, or when TraceCite reports the evidence-call ceiling, causal discovery is over" in skill
    assert "This execution card is Agent investigation/stopping policy. It must not be moved into Runtime" in skill
    assert "orientation calls" not in runtime
    assert "reverse component nesting" not in runtime


def test_skill_serializes_and_bounds_tracecite_transport() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "Make calls serially" in skill
    assert "Target `<= 8` evidence calls; Runtime may enforce a diagnosis-neutral absolute transport ceiling of 16" in skill
    assert "After one representative blocker, spend at most four calls on a structurally distinct reciprocal path" in skill
    assert "After two non-advancing calls for one discriminator, mark it `bounded_unknown` and finalize" in skill
    assert "No equivalent-waiter census, confirmation pass, or symptom sweep after the discriminator closes" in skill
    assert "Runtime call exhaustion never upgrades evidence" in skill
    assert "diagnosis-neutral absolute transport ceiling" not in runtime


def test_skill_forces_fixed_stack_only_final_after_mechanism_closes_or_bounds() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "If the reverse path is observed, stop searching for more equivalent waiters" in skill
    assert "If it is not found after two non-advancing attempts, mark the mechanism `bounded_unknown`" in skill
    assert "the only downstream-lifecycle sentence allowed" in skill
    assert "### Required stack-only final format" in skill
    assert "emit **exactly four short paragraphs** and nothing else" in skill
    assert "`Observed:` cite representative directly observed blocked path(s)" in skill
    assert "`Mechanism:` either" in skill
    assert "`Uncertainty:` “Current lock holder/ownership is not established by this artifact.”" in skill
    assert "`Boundary:` “The supplied evidence supports the in-process blocking pattern, but does not establish the downstream process/RPC/restart lifecycle.”" in skill
    assert "remaining causal discriminator" not in runtime


def test_smoke_system_override_includes_full_skill_contract() -> None:
    smoke = SMOKE.read_text(encoding="utf-8")
    assert 'SKILL_PROMPT="$(cat "$GITHUB_WORKSPACE/.pi/skills/tracecite/SKILL.md")"' in smoke
    assert "The following TraceCite Skill contract is mandatory for this run:" in smoke
    assert '${SKILL_PROMPT}' in smoke
    assert '--system-prompt "$SYSTEM_PROMPT"' in smoke


def test_runtime_remains_mechanical() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "Runtime boundary" in skill
    assert "Runtime must remain diagnosis-neutral" in skill
    assert "it does not know hypotheses, causality, proof claims, root cause, sufficiency, or stopping" in skill
    assert "proof claims" not in runtime
