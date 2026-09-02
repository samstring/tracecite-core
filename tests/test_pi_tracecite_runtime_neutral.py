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


def test_skill_normalizes_blocking_before_diagnosis() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "Hard rule: normalize blocking evidence before diagnosis" in skill
    assert "blocked at acquire(X) -> waits X" in skill
    assert "blocked at acquire(X) -/-> holds X" in skill
    assert "A waiting `RLock` is not an `RLock` holder" in skill
    assert "Correct the proof state before any further retrieval" in skill
    assert "normalize blocking evidence" not in runtime
    assert "waiting `RLock`" not in runtime


def test_skill_closes_supported_holds_with_phase_contrast() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    assert "path/stack A stops at acquire(X)" in skill
    assert "path/stack B is already past acquire(X)" in skill
    assert "B supports: holds X while waiting on the nested resource" in skill
    assert "Do not search indefinitely for a literal `held=true`" in skill


def test_cycle_requires_two_normalized_edges() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    assert "path A: holds A -> waits B" in skill
    assert "path B: holds B -> waits A" in skill
    assert "A deadlock/lock-order inversion is closed only when both opposing edges" in skill
    assert "One waiter, many waiters, a hotspot, or a writer queue is not a cycle" in skill


def test_skill_owns_monotonic_proof_not_runtime() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "Monotonic Causal Proof Ledger" in skill
    assert "supported_inference" in skill
    assert "bounded_unknown" in skill
    assert "MUST NOT reopen" in skill
    assert "Monotonic Causal Proof Ledger" not in runtime
    assert "supported_inference" not in runtime


def test_every_tracecite_call_targets_open_semantic_claim() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    assert "Every TraceCite call MUST either" in skill
    assert "Claim identity is semantic, not query wording" in skill
    assert "If no such claim exists, do not call TraceCite" in skill
    assert "After two consecutive non-advancing attempts for the SAME semantic claim" in skill


def test_skill_enforces_supplied_evidence_boundary() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    assert "model memory          == supplied evidence" in skill
    assert "nearby pointer values == same object/field identity" in skill
    assert "absence of holder     == holder exited/vanished" in skill
    assert "guessed source code" in skill


def test_mechanism_precedes_downstream_symptom_census() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    assert "Mechanism first; downstream symptoms are subordinate" in skill
    assert "mechanism / causal edges" in skill
    assert "A symptom stated in the user prompt is context to explain, not evidence" in skill
    assert "do not start a secondary census of shims, FIFOs, waits, loggers" in skill
    assert "Co-occurrence, duration, count, or a generic long-lived waiter is insufficient" in skill


def test_artifact_boundary_qualifies_unrepresented_downstream_state() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    assert "cannot represent a later external process/lifecycle state" in skill
    assert "qualify the downstream consequence without more retrieval" in skill


def test_closed_proof_forces_final_answer_and_blocks_new_story() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "the NEXT assistant action MUST be the final answer" in skill
    assert "terminal commitment" in skill
    assert "Final causal claims MUST be a subset of closed proof claims" in skill
    assert "timing-default" in skill
    assert "NEXT assistant action MUST be the final answer" not in runtime


def test_runtime_remains_mechanical() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "Runtime boundary" in skill
    assert "It does not know hypotheses, causality, proof claims, root cause, sufficiency, or stopping" in skill
    assert "proof claims" not in runtime
