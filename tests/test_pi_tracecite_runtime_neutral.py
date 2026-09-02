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


def test_skill_has_hard_pre_call_proof_gate() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "Highest-priority execution contract" in skill
    assert "Before EVERY TraceCite call" in skill
    assert "claim: the one unresolved/contradicted material causal fact" in skill
    assert "discriminator: the concrete result that would change that claim" in skill
    assert "do not call TraceCite; answer now" in skill
    assert "discriminator" not in runtime


def test_skill_forces_mechanism_first_and_bounds_downstream_state() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    assert "mechanism / required causal edges" in skill
    assert "Do **not** investigate downstream symptoms while mechanism edges are unresolved" in skill
    assert "requested downstream consequence only to the artifact boundary" in skill
    assert "Do not search broadly for external process state after this boundary is known" in skill
    assert "In-process stack evidence alone does not prove process creation state" in skill


def test_skill_bounds_tracecite_transport_requests() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    assert "request at most **12** inline evidence items" in skill
    assert "normally use radius **<= 16**" in skill
    assert "one strongest representative instance per distinct causal role" in skill
    assert "Counts and equivalent stacks are not additional proof" in skill


def test_skill_owns_monotonic_proof_not_runtime() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "Monotonic causal proof ledger" in skill
    assert "supported_inference" in skill
    assert "bounded_unknown" in skill
    assert "MUST NOT reopen" in skill
    assert "supported_inference" not in runtime
    assert "bounded_unknown" not in runtime


def test_skill_normalizes_blocking_before_cycle_claim() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "blocked at acquire(X) -> waits X" in skill
    assert "blocked at acquire(X) -/-> holds X" in skill
    assert "one representative stops at acquire(X)" in skill
    assert "another representative of the same path/function is already past acquire(X)" in skill
    assert "A deadlock/lock-order inversion requires both opposing edges" in skill
    assert "blocked at acquire(X)" not in runtime


def test_skill_rejects_pointer_arithmetic_and_search_absence_as_proof() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    assert "nearby pointer values == same object/field identity" in skill
    assert "absence of a match    == global absence" in skill
    assert "Do not use numeric address proximity to establish object/field identity" in skill
    assert "guessed struct layout" in skill


def test_same_semantic_claim_cannot_escape_by_synonym() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    assert "Claim identity is semantic, not query wording" in skill
    assert "After two consecutive non-advancing attempts for the SAME semantic claim" in skill
    assert "stop reformulating synonyms" in skill


def test_new_hints_do_not_expand_proof_scope() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    assert "does NOT create a new claim by itself" in skill
    assert "Do not run independent searches for multiple alternative stories" in skill
    assert "otherwise reassess proof state first" in skill


def test_closed_proof_forces_compact_final_answer() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "the **NEXT assistant action MUST be the final answer**" in skill
    assert "terminal commitment" in skill
    assert "Every material causal statement in the final answer MUST be a closed proof claim" in skill
    assert "the minimum competing causal paths/edges" in skill
    assert "only the strongest representative evidence citations" in skill
    assert "NEXT assistant action MUST be the final answer" not in runtime


def test_runtime_remains_mechanical() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "Runtime boundary" in skill
    assert "It does not know hypotheses, causality, proof claims, root cause, sufficiency, or stopping" in skill
    assert "proof claims" not in runtime
