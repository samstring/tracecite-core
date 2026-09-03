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


def test_skill_keeps_waiter_holder_and_lifecycle_boundaries_in_skill_only() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "`blocked at acquire(X)` proves only `waits X`; it never proves `holds X`" in skill
    assert "A waiter is not a holder" in skill
    assert "Current lock holder/ownership is unknown unless independent evidence directly proves it" in skill
    assert "Pointer/address equality does not prove shared, singleton, global, or same-object identity" in skill
    assert "Stack position and source order are not lifecycle chronology" in skill
    assert "blocked at acquire(X)" not in runtime
    assert "current lock holder" not in runtime.lower()


def test_skill_requires_two_observed_reciprocal_component_paths() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "two observed stack paths directly show reversed component nesting" in skill
    assert "across distinct synchronization domains" in skill
    assert "`A1 -> B1` and `B2 -> A2`" in skill
    assert "Structural inversion never establishes current holders or a current deadlock cycle" in skill
    assert "reversed component nesting" not in runtime


def test_skill_uses_one_explicit_six_call_counter() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "## Highest-priority stack-only stop contract" in skill
    assert "6 total TraceCite evidence calls" in skill
    assert "`tracecite_search` + `tracecite_expand` combined" in skill
    assert "Count locally from 1" in skill
    assert "Calls 1-2: locate one representative blocked domain path" in skill
    assert "Calls 3-6: only seek the exact reverse component nesting" in skill
    assert "Never reset the count and never continue toward a higher Runtime ceiling" in skill
    assert "evidence_call_index" not in runtime
    assert "reciprocal-only" not in runtime


def test_skill_stops_after_nonadvancing_reciprocal_attempts() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "two reciprocal attempts fail to advance" in skill
    assert "call 6 returns" in skill
    assert "stop all tool use immediately" in skill
    assert "Broad waiter census, pointer searches, lifecycle searches, and symptom sweeps are forbidden after orientation" in skill
    assert "Agent investigation and stopping policy live here" in skill
    assert "reciprocal attempts" not in runtime


def test_skill_forces_fixed_stack_only_terminal_shape() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "The entire user-visible answer then begins with `Observed:`" in skill
    assert "There is no preamble, scratch reasoning, evidence summary, heading, bullet list, stopping narration, or text before `Observed:`" in skill
    assert "The entire answer is exactly four short paragraphs" in skill
    assert "`Observed:` representative directly observed blocked path(s)" in skill
    assert "`Mechanism:` either" in skill
    assert "`Uncertainty:` `Current lock holder/ownership is not established by this artifact.`" in skill
    assert "`Boundary:` `The supplied evidence supports the in-process blocking pattern, but does not establish the downstream process/RPC/restart lifecycle.`" in skill
    assert "Nothing else may appear before or after them" in skill
    assert "terminal mode" not in runtime.lower()


def test_smoke_system_override_includes_full_skill_contract() -> None:
    smoke = SMOKE.read_text(encoding="utf-8")
    assert 'SKILL_PROMPT="$(cat "$GITHUB_WORKSPACE/.pi/skills/tracecite/SKILL.md")"' in smoke
    assert "The following TraceCite Skill contract is mandatory for this run:" in smoke
    assert '${SKILL_PROMPT}' in smoke
    assert '--system-prompt "$SYSTEM_PROMPT"' in smoke


def test_runtime_remains_mechanical() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "## Runtime boundary" in skill
    assert "Runtime must remain diagnosis-neutral" in skill
    assert "it does not know hypotheses, causality, proof claims, root cause, sufficiency, or stopping" in skill
    assert "proof claims" not in runtime
