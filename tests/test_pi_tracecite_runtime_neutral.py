from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
IMPL = ROOT / "benchmarks" / "agent-investigation" / "pi_tracecite_extension_impl.ts"
SKILL = ROOT / ".pi" / "skills" / "tracecite" / "SKILL.md"


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


def test_skill_has_semantic_waiter_holder_gate_without_runtime_policy() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "Highest-priority semantic invariants" in skill
    assert "A waiter is never a holder" in skill
    assert "blocked at acquire(X)" in skill
    assert "waits X" in skill
    assert "Multiple waiters on X do not prove a holder identity" in skill
    assert "A waiter is never a holder" not in runtime
    assert "blocked at acquire(X)" not in runtime


def test_skill_requires_two_independent_opposing_edges() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "Deadlock/cycle requires two independently supported opposing edges" in skill
    assert "EDGE A: holds A -> waits B" in skill
    assert "EDGE B: holds B -> waits A" in skill
    assert "mark the missing edge `bounded_unknown`" in skill
    assert "Deadlock/cycle requires" not in runtime
    assert "bounded_unknown" not in runtime


def test_skill_rejects_exclusivity_and_rlock_as_holder_proof() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    assert "Do not use lock exclusivity as evidence of holder identity" in skill
    assert "only one worker can be inside" in skill
    assert "Blocked `RLock` proves a reader is waiting" in skill
    assert "does not by itself prove which reader/writer holds the lock" in skill


def test_skill_enforces_artifact_lifecycle_boundary() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "Stay inside the artifact lifecycle boundary" in skill
    assert "does not by itself prove that a shim/process was forked" in skill
    assert "whether cleanup/reaping is blocked" in skill
    assert "why restart recovers" in skill
    assert "artifact lifecycle boundary" not in runtime


def test_skill_has_mandatory_final_answer_filter() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "Mandatory final-answer proof filter" in skill
    assert "without making another TraceCite call" in skill
    assert "Does it promote a waiter into a holder?" in skill
    assert "Does it claim a cycle without two concrete opposing current holds->waits edges?" in skill
    assert "delete or qualify that sentence" in skill
    assert "Mandatory final-answer proof filter" not in runtime


def test_skill_owns_minimum_causal_proof_ledger_not_runtime() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "Minimum causal proof ledger" in skill
    assert "supported_inference" in skill
    assert "bounded_unknown" in skill
    assert "Do not reopen a closed claim for reassurance" in skill
    assert "supported_inference" not in runtime
    assert "bounded_unknown" not in runtime


def test_skill_normalizes_blocking_and_execution_phase() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    assert "blocked at acquire(X) -> waits X" in skill
    assert "blocked at acquire(X) -/-> holds X" in skill
    assert "Stack textual order is not acquisition order" in skill
    assert "acquisition dominates the observed block" in skill
    assert "release has not occurred before that point" in skill


def test_skill_rejects_pointer_identity_invention() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    assert "Do not manufacture object identity" in skill
    assert "Nearby pointer values, address offsets, guessed struct layout" in skill
    assert "Only supplied evidence may establish identity" in skill


def test_skill_has_pre_call_claim_discriminator_gate() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "Before every TraceCite call identify internally" in skill
    assert "claim: the single unresolved or contradicted material fact" in skill
    assert "discriminator: the concrete result that would change that claim" in skill
    assert "If either cannot be named, do not call TraceCite; answer" in skill
    assert "discriminator" not in runtime


def test_skill_bounds_transport_and_synonym_loops() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "`tracecite_search`: `max_evidence <= 12`" in skill
    assert "`tracecite_expand`: normally `radius <= 16`" in skill
    assert "default total evidence-call budget: **16 calls**" in skill
    assert "after two consecutive non-advancing attempts for the same claim" in skill
    assert "one strongest representative per distinct causal role" in skill
    assert "16 calls" not in runtime


def test_skill_orders_mechanism_before_direct_impact_and_lifecycle() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    assert "mechanism / required causal edges" in skill
    assert "direct impact visible in supplied evidence" in skill
    assert "requested downstream consequence only to the artifact boundary" in skill


def test_closed_proof_forces_next_action_final_answer() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "Stop rule" in skill
    assert "next assistant action must be the final answer" in skill
    assert "No confirmatory search, census, symptom sweep, or lifecycle completion" in skill
    assert "terminal commitment" in skill
    assert "next assistant action must be the final answer" not in runtime


def test_runtime_remains_mechanical() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "Runtime boundary" in skill
    assert "Runtime must remain diagnosis-neutral" in skill
    assert "it does not know hypotheses, causality, proof claims, root cause, sufficiency, or stopping" in skill
    assert "proof claims" not in runtime
