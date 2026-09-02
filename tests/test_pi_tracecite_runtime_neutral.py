from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
IMPL = ROOT / "benchmarks" / "agent-investigation" / "pi_tracecite_extension_impl.ts"
SKILL = ROOT / ".pi" / "skills" / "tracecite" / "SKILL.md"


def test_tracecite_runtime_returns_evidence_without_investigation_policy() -> None:
    text = IMPL.read_text(encoding="utf-8")

    # Runtime tools transport evidence and mechanical metadata. Investigation
    # policy may live in the Agent/skill layer, but it must not be injected into
    # every TraceCite result or used to gate the Agent's next evidence call.
    assert "agent_feedback" not in text
    assert "convergence_checkpoint" not in text
    assert "checkpoint_required" not in text
    assert "investigation_goal" not in text
    assert "reassess_before_next_evidence_call" not in text
    assert "next_evidence_call_requires_investigation_goal" not in text
    assert 'content: [{ type: "text" as const, text }]' in text


def test_agent_projection_keeps_only_bounded_mechanical_metadata() -> None:
    text = IMPL.read_text(encoding="utf-8")

    # Large unmatched token/sample surveys are useful internally but should not
    # be repeated into every Agent turn. Novelty and bounded coverage remain.
    assert "function compactCoverage" in text
    assert "function compactProgress" in text
    assert "function compactMatchedExisting" in text
    assert '"unmatched"' not in text
    assert '"consecutive_no_growth"' in text
    assert "neutralPreview" in text


def test_path_errors_expose_only_configured_source_inventory() -> None:
    text = IMPL.read_text(encoding="utf-8")

    # A bad caller path may expose the finite Host-configured evidence inventory
    # as neutral capability metadata. It must not add a recommended source/query.
    assert "function availableSources" in text
    assert "TRACECITE_EVIDENCE_FILES" in text
    assert "available_sources: sources" in text
    assert "recommended_source" not in text
    assert "next_source" not in text


def test_skill_layer_can_own_usage_guidance() -> None:
    text = SKILL.read_text(encoding="utf-8")

    assert "Recommended Agent investigation loop" in text
    assert "TraceCite's job is to make the evidence recoverable" in text
    assert "The Agent's job is to understand what that evidence means" in text


def test_skill_uses_answer_obligation_stopping_without_runtime_policy() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")

    assert "answer obligations" in skill
    assert "One evidence round = one obligation" in skill
    assert "2 consecutive non-advancing rounds" in skill
    assert "answer immediately" in skill
    assert "answer obligations" not in runtime
    assert "non-advancing rounds" not in runtime


def test_skill_terminal_transition_prevents_post_closure_meta_loop() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")

    assert "Terminal answer transition" in skill
    assert "the next assistant action is the final answer" in skill
    assert "no intermediate verification/meta-planning turn" in skill
    assert "do not repeatedly retry adjacent lines" in skill
    assert "failure mechanism/class and the affected subsystem or component" in skill

    # Semantic stopping and answer-shaping remain Agent/skill policy, never
    # TraceCite runtime policy.
    assert "Terminal answer transition" not in runtime
    assert "failure mechanism/class" not in runtime
