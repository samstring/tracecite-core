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


def test_skill_keeps_generic_pre_call_claim_gate() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "Before each TraceCite call identify internally" in skill
    assert "one unresolved or contradicted material claim" in skill
    assert "the concrete result that could change that claim" in skill
    assert "do not call TraceCite" in skill
    assert "material claim" not in runtime


def test_skill_keeps_generic_evidence_boundary() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    assert "Only supplied artifacts are evidence" in skill
    assert "search match" in skill
    assert "causal proof" in skill
    assert "file/line order" in skill
    assert "global happens-before" in skill
    assert "absence of a match" in skill
    assert "global absence" in skill


def test_skill_keeps_bounded_transport_without_case_tuning() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    assert "# Bounded evidence transport" in skill
    assert "minimum representative context needed" in skill
    assert "one strongest representative instance per distinct causal role" in skill
    assert "equivalent examples are not additional proof" in skill


def test_skill_owns_generic_proof_state_not_runtime() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "supported_inference" in skill
    assert "bounded_unknown" in skill
    assert "Stop when every material claim required by the question" in skill
    assert "supported_inference" not in runtime
    assert "bounded_unknown" not in runtime


def test_skill_has_no_case_specific_sync_or_container_runtime_policy() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    forbidden = [
        "blocked at acquire(X)",
        "Stack-frame orientation is not acquisition order",
        "holds A -> waits B",
        "deadlock/lock-order inversion",
        "containerd",
        "runc init",
        "shim",
        "FIFO",
        "ttrpc",
        "restart clears",
        "nearby pointer values",
    ]
    for token in forbidden:
        assert token not in skill


def test_same_semantic_claim_cannot_escape_by_rewording() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    assert "Claim identity is semantic, not query wording" in skill
    assert "two consecutive non-advancing attempts" in skill
    assert "stop reformulating" in skill


def test_new_hints_do_not_expand_proof_scope() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    assert "does not create a new material claim by itself" in skill
    assert "Track only the smallest set of material claims required by the user's question" in skill


def test_closed_proof_forces_answer_transition() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "the next assistant action must be the final answer" in skill
    assert "Do not perform a reassurance search, broader census, or verification turn merely for confidence" in skill
    assert "Every material causal statement in the final answer must correspond to a closed claim" in skill
    assert "NEXT assistant action MUST be the final answer" not in runtime


def test_runtime_remains_mechanical() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "Runtime boundary" in skill
    assert "It does not know hypotheses, causality, proof claims, root cause, sufficiency, or stopping" in skill
    assert "proof claims" not in runtime
