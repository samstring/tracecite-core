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
    assert "Ask separately whether **independent supplied evidence** exposes the current holder or an acquire-to-release interval" in skill
    assert "converts a waiter into a holder" in skill
    assert "is being held for a long time" in skill
    assert "blocked at acquire(X)" not in runtime
    assert "current ownership" not in runtime


def test_skill_separates_structural_lock_order_from_current_holder_identity() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "Separate **current-holder proof** from **structural lock-order proof**" in skill
    assert "two independent observed stacks directly materialize opposite nested acquisition paths" in skill
    assert "structural-path evidence never identifies the current holder" in skill
    assert "If only one direction is observed, report blocking/contention and mark the opposing path unknown" in skill
    assert "claims a structural lock-order inversion/cyclic-wait mechanism without two independent observed opposite nested acquisition paths" in skill
    assert "promotes an unobserved sibling function/path into the mechanism" in skill
    assert "structural lock-order proof" not in runtime
    assert "opposite nested acquisition paths" not in runtime


def test_skill_enforces_artifact_lifecycle_boundary_and_deletion_gate() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "Stop at the artifact boundary" in skill
    assert "External process creation, RPC completion, retries, cleanup/reaping, restart recovery, and helper-goroutine identity require independent evidence" in skill
    assert "explains downstream process/RPC/retry/restart/cleanup/reaping behavior" in skill
    assert "A caveat later in the answer does not repair an unsupported earlier claim: remove the claim" in skill
    assert "If deleting a missing-edge claim also removes support for a downstream consequence, delete that consequence too" in skill
    assert "artifact boundary" not in runtime.lower()


def test_skill_owns_terminal_claim_classification_and_downgrade() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "Terminal safety rule" in skill
    assert "observed | supported_inference | bounded_unknown | contradicted" in skill
    assert "If a root-cause edge is still `bounded_unknown`, the final must downgrade every consequence that depends on that missing edge" in skill
    assert "Do not call an unsupported stronger hypothesis" in skill
    assert "supported_inference" not in runtime
    assert "bounded_unknown" not in runtime


def test_skill_has_pre_call_claim_discriminator_and_causal_priority() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "Before each TraceCite call identify internally one `claim` and one `discriminator`" in skill
    assert "If either is missing, answer now" in skill
    assert "Prioritize causal closure over symptom census" in skill
    assert "retrieve only evidence that can prove or falsify the unresolved causal edge or structurally distinct opposing acquisition path" in skill
    assert "Do not count equivalent waiters or chase downstream symptoms while the mechanism is unresolved" in skill
    assert "discriminator" not in runtime


def test_skill_serializes_and_bounds_tracecite_transport() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "Make TraceCite calls serially" in skill
    assert "absolute transport ceiling: 16 evidence calls" in skill
    assert "A result reporting total calls >= 16 is terminal; the next action must be the final answer" in skill
    assert "`tracecite_search`: `max_evidence <= 12`" in skill
    assert "`tracecite_expand`: normally `radius <= 16`" in skill
    assert "target total calls `<= 8`; absolute ceiling `16`" in skill
    assert "use at most four additional evidence calls to locate a structurally distinct opposing path" in skill
    assert "after observing `component A operation -> component B operation/acquire(B)`" in skill
    assert "do not keep searching B's lock address, B's generic lock routine, or more callers ending at the same `acquire(B)`" in skill
    assert "Hits ending at the already-known acquisition site are non-advancing for the reciprocal-path discriminator" in skill
    assert "reciprocal-path discriminator" not in runtime
    assert "after two non-advancing calls for the same claim, mark it `bounded_unknown`" in skill
    assert "no equivalent-waiter census" in skill
    assert "no symptom sweep after the causal discriminator is bounded unknown" in skill
    assert "Absolute transport ceiling" not in runtime


def test_skill_forces_final_when_mechanism_closed_or_remaining_edge_bounded_unknown() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "Once the directly supported mechanism is closed—or the remaining causal discriminator is bounded unknown—answer immediately" in skill
    assert "no confirmation pass for an already closed claim" in skill
    assert "strongest supported subsystem/blocking or structural lock-order statement" in skill
    assert "minimum exact evidence for representative observed blocking path(s), including both opposite acquisition paths when the structural cycle is supported" in skill
    assert "explicitly identify current holder identity or any missing opposing path as unknown" in skill
    assert "direct impact visible in the artifact only" in skill
    assert "remaining causal discriminator" not in runtime


def test_runtime_remains_mechanical() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "Runtime boundary" in skill
    assert "Runtime must remain diagnosis-neutral" in skill
    assert "it does not know hypotheses, causality, proof claims, root cause, sufficiency, or stopping" in skill
    assert "proof claims" not in runtime
