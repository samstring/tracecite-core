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


def test_skill_keeps_waiter_holder_and_current_ownership_boundary_in_skill_only() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "`blocked at acquire(X)` proves only `waits X`" in skill
    assert "does not prove `holds Y`" in skill
    assert "current ownership is supported only when supplied evidence exposes the acquire-to-release control-flow interval" in skill
    assert "converts a waiter into a holder" in skill
    assert "blocked at acquire(X)" not in runtime
    assert "current ownership" not in runtime


def test_skill_requires_two_current_opposing_edges_and_downgrades_incomplete_cycle() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "Deadlock/cycle/lock-order inversion requires two independently supported **current** edges" in skill
    assert "`holds A -> waits B`" in skill
    assert "`holds B -> waits A`" in skill
    assert "If either holder edge is missing, report only the observed blocking/contention and mark the missing causal edge unknown" in skill
    assert "names an unobserved holder or opposing causal edge" in skill
    assert "claims deadlock/cycle/lock-order inversion without both current `holds -> waits` edges" in skill
    assert "Deadlock/cycle/lock-order inversion" not in runtime
    assert "bounded_unknown" not in runtime


def test_skill_enforces_artifact_lifecycle_boundary_and_deletion_gate() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "Stop at the artifact boundary" in skill
    assert "External process creation, RPC completion, retries, cleanup/reaping, restart recovery, and helper-goroutine identity require independent evidence" in skill
    assert "explains downstream process/RPC/retry/restart/cleanup/reaping behavior" in skill
    assert "A caveat later in the answer does not repair an unsupported earlier claim: remove the claim" in skill
    assert "artifact boundary" not in runtime.lower()


def test_skill_owns_terminal_claim_classification_and_downgrade() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "Terminal safety rule" in skill
    assert "observed | supported_inference | bounded_unknown | contradicted" in skill
    assert "If a root-cause edge is still `bounded_unknown`, the final must explicitly downgrade to the strongest supported statement" in skill
    assert "Do not call the stronger hypothesis" in skill
    assert "supported_inference" not in runtime
    assert "bounded_unknown" not in runtime


def test_skill_has_pre_call_claim_discriminator_and_causal_priority() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "Before each TraceCite call identify internally one `claim` and one `discriminator`" in skill
    assert "If either is missing, answer now" in skill
    assert "Prioritize causal closure over symptom census" in skill
    assert "retrieve only evidence that can prove or falsify the unresolved causal edge" in skill
    assert "Do not count equivalent waiters or chase downstream symptoms while the mechanism is unresolved" in skill
    assert "discriminator" not in runtime


def test_skill_serializes_and_bounds_tracecite_transport() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "Make TraceCite calls serially" in skill
    assert "Absolute transport ceiling: 16 evidence calls" in skill
    assert "A result reporting total calls >= 16 is terminal; the next action must be the final answer" in skill
    assert "`tracecite_search`: `max_evidence <= 12`" in skill
    assert "`tracecite_expand`: normally `radius <= 16`" in skill
    assert "target total calls `<= 12`; absolute ceiling `16`" in skill
    assert "after two non-advancing calls for the same claim, mark it `bounded_unknown`" in skill
    assert "no equivalent-waiter census" in skill
    assert "no symptom sweep after the causal discriminator is bounded unknown" in skill
    assert "Absolute transport ceiling" not in runtime


def test_skill_forces_final_when_mechanism_closed_or_remaining_edge_bounded_unknown() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "Once the directly supported mechanism is closed—or the remaining causal discriminator is bounded unknown—answer immediately" in skill
    assert "no confirmation pass for an already closed claim" in skill
    assert "strongest supported mechanism/subsystem statement" in skill
    assert "minimum exact evidence for the observed blocking path(s)" in skill
    assert "explicitly identify any missing holder/opposing edge as unknown" in skill
    assert "direct impact visible in the artifact only" in skill
    assert "remaining causal discriminator" not in runtime


def test_runtime_remains_mechanical() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "Runtime boundary" in skill
    assert "Runtime must remain diagnosis-neutral" in skill
    assert "it does not know hypotheses, causality, proof claims, root cause, sufficiency, or stopping" in skill
    assert "proof claims" not in runtime
