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
    assert "Non-negotiable final gate" in skill
    assert "Waiter != holder" in skill
    assert "blocked at acquire(X)" in skill
    assert "waits X" in skill
    assert "Multiple waiters or lock exclusivity never identify a holder" in skill
    assert "Waiter != holder" not in runtime
    assert "blocked at acquire(X)" not in runtime


def test_skill_requires_two_independent_opposing_edges() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "Deadlock/cycle/lock-order inversion requires two independently supported current edges" in skill
    assert "holds A -> waits B" in skill
    assert "holds B -> waits A" in skill
    assert "report only the supported blocking/contention and the missing edge as unknown" in skill
    assert "Do not use the words deadlock, cycle, cyclic wait, lock-order inversion, or AB-BA" in skill
    assert "but not an unobserved holder, waiter census, pointer proximity, queued-reader/writer semantics, guessed lock scope, or progress-past-acquire reasoning" in skill
    assert "Repeated waits on one resource establish contention only, not an opposing causal path" in skill
    assert "unobserved holder -/-> supported holder edge" in skill
    assert "Deadlock/cycle/lock-order inversion" not in runtime
    assert "bounded_unknown" not in runtime


def test_skill_rejects_exclusivity_and_rlock_as_holder_proof() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    assert "Multiple waiters or lock exclusivity never identify a holder" in skill
    assert "A blocked `RLock(X)` does not prove that a writer currently holds X" in skill
    assert "queued-writer preference" in skill
    assert "blocked at RLock(X) -/-> writer currently holds X" in skill
    assert "repeated waits on X -/-> opposing causal edge" in skill
    assert "current hold needs current-ownership proof" in skill


def test_skill_enforces_artifact_lifecycle_boundary() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "Artifact lifecycle boundary" in skill
    assert "does not by itself prove that a shim/process was forked" in skill
    assert "whether cleanup/reaping is blocked" in skill
    assert "why restart recovers" in skill
    assert "Artifact lifecycle boundary" not in runtime


def test_skill_has_mandatory_final_answer_filter() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "Non-negotiable final gate" in skill
    assert "Immediately before answering, delete or qualify every material sentence" in skill
    assert "Waiter != holder" in skill
    assert "Deadlock/cycle/lock-order inversion requires two independently supported current edges" in skill
    assert "This gate overrides completeness and helpfulness" in skill
    assert "Non-negotiable final gate" not in runtime


def test_skill_owns_minimum_causal_proof_ledger_not_runtime() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "Proof ledger" in skill
    assert "supported_inference" in skill
    assert "bounded_unknown" in skill
    assert "Do not reopen it for reassurance" in skill
    assert "supported_inference" not in runtime
    assert "bounded_unknown" not in runtime


def test_skill_normalizes_blocking_and_execution_phase() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    assert "blocked at acquire(X) -> waits X" in skill
    assert "blocked at acquire(X) -/-> holds X" in skill
    assert "caller frame alone -/-> current ownership" in skill
    assert "acquire(Y) + current nested call + release only after nested return -> may support currently holds Y" in skill


def test_skill_rejects_pointer_identity_invention() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    assert "Do not manufacture identity" in skill
    assert "Pointer proximity, guessed struct layout, helper names" in skill
    assert "cannot establish object/request/process identity" in skill


def test_skill_has_pre_call_claim_discriminator_gate() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "Before every TraceCite call identify internally" in skill
    assert "claim: one unresolved or contradicted material fact" in skill
    assert "discriminator: the concrete result that would change that claim" in skill
    assert "If either cannot be named, answer instead of calling TraceCite" in skill
    assert "discriminator" not in runtime


def test_skill_bounds_transport_and_synonym_loops() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "`tracecite_search`: `max_evidence <= 12`" in skill
    assert "`tracecite_expand`: normally `radius <= 16`" in skill
    assert "target total evidence calls: <= 12; absolute ceiling: 16" in skill
    assert "after two consecutive non-advancing calls for the same claim" in skill
    assert "Use one strongest representative per causal role" in skill
    assert "tracecite_host_activity_summary.total_tool_calls" in skill
    assert "Inspect this field before interpreting or acting on the returned evidence" in skill
    assert "If the returned total is 16 or greater, that tool result is the terminal retrieval result" in skill
    assert "the next assistant action must be the final answer, not another TraceCite call" in skill
    assert "Do not estimate or restart the count from memory" in skill
    assert "absolute ceiling: 16" not in runtime


def test_skill_orders_mechanism_before_direct_impact_and_lifecycle() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    assert "one mechanism/subsystem statement" in skill
    assert "the minimum supported causal path or opposing edges" in skill
    assert "direct impact visible in supplied evidence" in skill
    assert "one artifact-boundary sentence for unsupported downstream lifecycle" in skill


def test_closed_proof_forces_next_action_final_answer() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "Stop rule" in skill
    assert "next assistant action must be the final answer" in skill
    assert "No confirmatory search, waiter census, symptom sweep, or lifecycle completion" in skill
    assert "terminal commitment" in skill
    assert "next assistant action must be the final answer" not in runtime


def test_runtime_remains_mechanical() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "Runtime boundary" in skill
    assert "Runtime must remain diagnosis-neutral" in skill
    assert "it does not know hypotheses, causality, proof claims, root cause, sufficiency, or stopping" in skill
    assert "proof claims" not in runtime
