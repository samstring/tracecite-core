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


def test_skill_layer_can_own_usage_guidance() -> None:
    text = SKILL.read_text(encoding="utf-8")

    assert "Recommended Agent investigation loop" in text
    assert "TraceCite's job is to make the evidence recoverable" in text
    assert "The Agent's job is to understand what that evidence means" in text


def test_skill_uses_answer_obligation_stopping_without_runtime_policy() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")

    assert "Minimal answer obligations" in skill
    assert "answer obligations" in skill
    assert "One evidence round = one obligation" in skill
    assert "2 consecutive non-advancing rounds" in skill
    assert "answer immediately" in skill
    assert "answer obligations" not in runtime
    assert "non-advancing rounds" not in runtime


def test_skill_requires_minimal_causal_closure_without_runtime_steering() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")

    assert "Minimal causal closure" in skill
    assert "minimum causal edges that must be true" in skill
    assert "minimum causal chain" in skill
    assert "Do not substitute evidence volume for causal closure" in skill
    assert "mechanism edge(s) + impact edge + no material contradiction" in skill

    assert "Minimal causal closure" not in runtime
    assert "minimum causal edges" not in runtime
    assert "causal closure" not in runtime


def test_skill_terminal_transition_prevents_post_closure_meta_loop() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")

    assert "Terminal answer transition" in skill
    assert "the next assistant action is the final answer" in skill
    assert "no intermediate verification/meta-planning turn" in skill
    assert "do not repeatedly retry adjacent lines" in skill
    assert "failure mechanism/class and affected subsystem/component" in skill
    assert "A terminal declaration is a commitment" in skill

    assert "Terminal answer transition" not in runtime
    assert "failure mechanism/class" not in runtime
    assert "terminal declaration" not in runtime


def test_skill_interprets_synchronization_stacks_without_runtime_steering() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")

    assert "Synchronization evidence semantics" in skill
    assert "waiting at that operation" in skill
    assert "minimal wait-for graph" in skill
    assert "representative evidence over exhaustive census" in skill
    assert "one strongest representative stack" in skill
    assert "A missing cycle edge keeps the root-cause obligation open" in skill

    assert "minimal wait-for graph" not in runtime
    assert "representative evidence over exhaustive census" not in runtime
    assert "missing cycle edge" not in runtime


def test_skill_final_answer_cannot_invent_new_causal_story() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")

    assert "Final-answer evidence discipline" in skill
    assert "Do not introduce a new causal claim in the final answer" in skill
    assert "hidden process-management behavior" in skill
    assert "Omit unsupported lifecycle extrapolation" in skill
    assert "A correct root-cause answer is preferable" in skill

    assert "Final-answer evidence discipline" not in runtime
    assert "new causal claim in the final answer" not in runtime
    assert "hidden process-management behavior" not in runtime


def test_skill_prioritizes_representative_evidence_over_census() -> None:
    skill = SKILL.read_text(encoding="utf-8")

    assert "smallest sufficient evidence packet" in skill
    assert "Prefer one representative instance per distinct causal role" in skill
    assert "do not census equivalents" in skill
    assert "More matches, more examples, more waiters" in skill
