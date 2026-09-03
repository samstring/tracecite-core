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
    assert "`blocked at acquire(X)` proves only `waits X`; it never proves `holds X`" in skill
    assert "Current holder identity remains `bounded_unknown` unless independent supplied evidence establishes it" in skill
    assert "that a waiter currently owns an outer lock" in skill
    assert "held for a long time" in skill
    assert "blocked at acquire(X)" not in runtime
    assert "current ownership" not in runtime


def test_skill_separates_structural_lock_order_from_current_holder_identity() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "Reciprocal structural discriminator" in skill
    assert "two **observed stack paths** directly show reversed component nesting across two distinct synchronization domains" in skill
    assert "This supports only the **structural inversion / cyclic-wait mechanism**. It does not identify current holders" in skill
    assert "If only one direction is observed, downgrade to observed blocking/contention" in skill
    assert "a structural reciprocal lock-order statement **only if both reversed component paths were directly observed**" in skill
    assert "structural lock-order proof" not in runtime
    assert "opposite nested acquisition paths" not in runtime


def test_skill_enforces_artifact_lifecycle_boundary_and_deletion_gate() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "## 4. Lifecycle boundary" in skill
    assert "External process creation, shim/runc state, RPC completion, retries, cleanup/reaping, termination progress, or restart recovery require independent event-capable evidence" in skill
    assert "Do not write a lifecycle story and then add this caveat" in skill
    assert "A later caveat does not repair an earlier unsupported assertion. Remove the assertion and all downstream consequences that depend on it" in skill
    assert "artifact boundary" not in runtime.lower()


def test_skill_owns_terminal_claim_classification_and_downgrade() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "## 5. Terminal claim discipline" in skill
    assert "`observed | supported_inference | bounded_unknown | contradicted`" in skill
    assert "Delete every sentence whose causal premise is `bounded_unknown`" in skill
    assert "Do **not** add narrative beyond those classes" in skill
    assert "supported_inference" not in runtime
    assert "bounded_unknown" not in runtime


def test_skill_has_pre_call_claim_discriminator_and_causal_priority() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "Before every TraceCite call identify one unresolved claim and one discriminator" in skill
    assert "If the next call cannot change the conclusion, stop" in skill
    assert "Once a path crosses from component A into component B, the next useful search is for the reverse B-to-A nesting" in skill
    assert "reciprocal retrieval must be **symbol-directed**" in skill
    assert "Generic subsystem queries such as `Collect`, `metrics`, `prometheus`, `cgroup`, or `lock` are non-advancing" in skill
    assert "Do not spend calls proving that many equivalent waiters exist" in skill
    assert "symbol-directed" not in runtime
    assert "discriminator" not in runtime


def test_skill_serializes_and_bounds_tracecite_transport() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "Make calls serially" in skill
    assert "Target `<= 8` total evidence calls; absolute Runtime transport ceiling is 16" in skill
    assert "After one representative blocker, use at most four additional calls to find a structurally distinct reciprocal path" in skill
    assert "After two non-advancing calls for the same discriminator, mark it `bounded_unknown` and finalize" in skill
    assert "No equivalent-waiter census" in skill
    assert "No symptom sweep after the causal discriminator is closed or bounded unknown" in skill
    assert "If the Runtime reports the evidence-call ceiling, the next action is the final answer" in skill
    assert "absolute Runtime transport ceiling" not in runtime


def test_skill_forces_final_when_mechanism_closed_or_remaining_edge_bounded_unknown() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "No confirmation pass for a closed claim" in skill
    assert "strongest supported in-process mechanism" in skill
    assert "minimum exact evidence for the representative path(s)" in skill
    assert "holder/ownership uncertainty explicitly stated" in skill
    assert "direct artifact-visible impact only" in skill
    assert "the exact root cause remains unclosed" in skill
    assert "If either reciprocal path is missing in `stack_only`, the final mechanism must remain blocking/contention with root cause unclosed" in skill
    assert "The single lifecycle-boundary sentence is the only permitted downstream-lifecycle text" in skill
    assert "remaining causal discriminator" not in runtime


def test_runtime_remains_mechanical() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "Runtime boundary" in skill
    assert "Runtime must remain diagnosis-neutral" in skill
    assert "it does not know hypotheses, causality, proof claims, root cause, sufficiency, or stopping" in skill
    assert "proof claims" not in runtime
