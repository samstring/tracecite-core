from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
IMPL = ROOT / "benchmarks" / "agent-investigation" / "pi_tracecite_extension_impl.ts"
GUARD = ROOT / "benchmarks" / "agent-investigation" / "pi_tracecite_retrieval_guard.ts"
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


def test_retrieval_budget_survives_low_level_agent_retry() -> None:
    guard = GUARD.read_text(encoding="utf-8")
    agent_start = guard.split('pi.on("agent_start"', 1)[1].split('pi.on("tool_call"', 1)[0]
    assert "retrievals = 0" not in agent_start
    assert "noGrowthBySignature.clear()" not in agent_start
    assert "continued_investigation: retrievals > 0" in agent_start
    assert "Provider retries do not reset this budget" in guard


def test_retrieval_guard_blocks_only_mechanical_coverage_reuse() -> None:
    guard = GUARD.read_text(encoding="utf-8")
    assert "coveredRangesByFile" in guard
    assert "rangeCovered" in guard
    assert "context_start_line" in guard
    assert "context_end_line" in guard
    assert 'reason: "range_already_covered"' in guard
    assert "hypothesis" not in guard.lower()
    assert "causal sufficiency" in guard


def test_no_match_is_not_cross_query_no_growth_and_errors_do_not_poison_novelty() -> None:
    guard = GUARD.read_text(encoding="utf-8")
    assert 'progress?.status === "no_match"' in guard
    assert 'return "neutral_no_match"' in guard
    assert "it never\n  // contributes to any cross-query/global no-growth decision" in guard
    tool_result = guard.split('pi.on("tool_result"', 1)[1].split('pi.on("agent_end"', 1)[0]
    assert "Boolean(event.isError)\n      ? (noGrowthBySignature.get(meta.key) || 0)" in tool_result
