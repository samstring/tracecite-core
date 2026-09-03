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
    assert "Current lock holder/ownership is not established" in skill
    assert "Pointer/address equality does not prove shared object or lock identity" in skill
    assert "Stack position is not lifecycle chronology" in skill
    assert "blocked at acquire(X)" not in runtime
    assert "current lock holder" not in runtime.lower()


def test_skill_requires_two_observed_reciprocal_component_paths() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "two observed stack paths directly show reversed component nesting" in skill
    assert "`A-owned operation -> B-owned operation/acquisition path`" in skill
    assert "`B-owned operation -> A-owned operation/acquisition path`" in skill
    assert "`A1 -> B1` and `B2 -> A2`" in skill
    assert "Structural inversion never establishes current holders or a current deadlock cycle" in skill
    assert "reversed component nesting" not in runtime


def test_skill_uses_one_explicit_six_call_counter() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "## Stack-only evidence-call state machine" in skill
    assert "Every `tracecite_search` and every `tracecite_expand` is one evidence call" in skill
    assert "Maintain one local `evidence_call_index`, initialized to `0`" in skill
    assert "Increment it exactly once after each TraceCite tool response" in skill
    assert "calls 1–2 are the complete orientation phase" in skill
    assert "calls 3–6 are reciprocal-only" in skill
    assert "when `evidence_call_index >= 6`, another TraceCite call is forbidden" in skill
    assert "A Runtime transport allowance may be higher" in skill
    assert "never extra investigation budget" in skill
    assert "Do not continue toward a higher Runtime ceiling" in skill
    assert "evidence_call_index" not in runtime
    assert "reciprocal-only" not in runtime


def test_skill_stops_after_nonadvancing_reciprocal_attempts() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "After two non-advancing reciprocal attempts" in skill
    assert "If the reverse path is still unclosed after call 6, finalize immediately" in skill
    assert "broad discovery queries such as `goroutine`, `Lock`, `semacquire`" in skill
    assert "lifecycle/symptom sweeps such as `runc`, `shim`, `process`, `RPC`, or `FIFO`" in skill
    assert "This state machine is Agent investigation/stopping policy. It must not be moved into Runtime" in skill
    assert "non-advancing reciprocal" not in runtime


def test_skill_forces_fixed_stack_only_terminal_shape() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "The first assistant prose after the final evidence call MUST begin exactly with `Observed:`" in skill
    assert "the very next assistant token MUST be the `O` in `Observed:`" in skill
    assert "emit exactly four short paragraphs and nothing else" in skill
    assert "`Observed:` representative directly observed blocked path(s)" in skill
    assert "`Mechanism:` either" in skill
    assert "`Uncertainty:` “Current lock holder/ownership is not established by this artifact.”" in skill
    assert "`Boundary:` “The supplied evidence supports the in-process blocking pattern, but does not establish the downstream process/RPC/restart lifecycle.”" in skill
    assert "Do not add any fifth paragraph" in skill
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
