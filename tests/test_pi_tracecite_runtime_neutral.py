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


def test_skill_owns_monotonic_causal_proof_policy_not_runtime() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")

    assert "Monotonic Causal Proof Ledger" in skill
    assert "unresolved" in skill
    assert "observed" in skill
    assert "supported_inference" in skill
    assert "contradicted" in skill
    assert "bounded_unknown" in skill
    assert "MUST NOT return to `unresolved`" in skill
    assert "Reopen it only when newly materialized evidence materially contradicts" in skill

    assert "Monotonic Causal Proof Ledger" not in runtime
    assert "supported_inference" not in runtime
    assert "bounded_unknown" not in runtime


def test_skill_enforces_user_supplied_evidence_boundary() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")

    assert "# Evidence boundary" in skill
    assert "model memory          == supplied evidence" in skill
    assert "implementation details remembered from training" in skill
    assert "cannot close a claim" in skill
    assert "Do not narrate invented source code" in skill

    assert "implementation details remembered from training" not in runtime
    assert "model memory" not in runtime


def test_every_tracecite_call_must_target_open_proof_claim() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")

    assert "Every TraceCite call MUST target one material causal claim" in skill
    assert "Claim identity is semantic, not query wording" in skill
    assert "If no such claim exists, do not call TraceCite" in skill
    assert "Retrieve only evidence that can change that claim" in skill
    assert "does NOT create a new claim by itself" in skill

    assert "material causal claim" not in runtime
    assert "Causal Proof Ledger" not in runtime


def test_supported_inference_uses_phase_contrast_instead_of_holder_census() -> None:
    skill = SKILL.read_text(encoding="utf-8")

    assert "Supported inference and phase contrast" in skill
    assert "use **phase contrast** before searching for an invisible holder" in skill
    assert "stack A stops at acquisition of resource X" in skill
    assert "stack B has progressed past that acquisition into a nested call" in skill
    assert "A paired phase contrast is causal evidence" in skill
    assert "do not infer ownership from a waiter alone" in skill
    assert "do not search for more holders" in skill


def test_raw_pointer_proximity_is_not_resource_identity() -> None:
    skill = SKILL.read_text(encoding="utf-8")

    assert "nearby pointer values == same object/field identity" in skill
    assert "Raw-address proximity or guessed struct layout is not proof" in skill


def test_non_advancing_limit_applies_to_same_claim_not_query_wording() -> None:
    skill = SKILL.read_text(encoding="utf-8")

    assert "two consecutive attempts for the SAME unresolved claim" in skill
    assert "stop reformulating synonyms for that claim" in skill
    assert "Mark it `bounded_unknown`" in skill


def test_synchronization_cycle_can_close_with_supported_inference() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")

    assert "waiting at `Lock`, `RLock`" in skill
    assert "does NOT mean that resource is held" in skill
    assert "phase contrast or supplied context establishes progression" in skill
    assert "a lock-order cycle requires both opposing wait-for edges" in skill
    assert "path A: holds A -> waits B" in skill
    assert "path B: holds B -> waits A" in skill
    assert "One blocked lock, one edge, a hotspot, or many waiters is not a deadlock proof" in skill

    assert "opposing wait-for edges" not in runtime
    assert "deadlock proof" not in runtime
    assert "phase contrast" not in runtime


def test_skill_rejects_symptom_census_as_default_investigation() -> None:
    skill = SKILL.read_text(encoding="utf-8")

    assert "directly distinguishes candidate mechanisms over symptom census" in skill
    assert "MUST NOT be collected unless the user's requested conclusion materially depends on the count" in skill
    assert "Do not census unrelated shim/logger/fifo/syscall stacks" in skill


def test_artifact_boundary_prevents_downstream_lifecycle_census() -> None:
    skill = SKILL.read_text(encoding="utf-8")

    assert "Artifact boundary and downstream impact" in skill
    assert "close the observed impact at that boundary and qualify the downstream consequence" in skill
    assert "Do not census unrelated shim/logger/fifo/syscall stacks" in skill
    assert "Absence of a directly visible holder is not evidence that the holder exited" in skill


def test_closed_proof_forces_final_answer_and_blocks_new_story() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")

    assert "the NEXT assistant action MUST be the final answer" in skill
    assert "Final causal claims MUST be a subset of closed proof claims" in skill
    assert "Do not introduce new causal, lifecycle, cleanup, restart, kernel" in skill
    assert '"complete picture"' in skill

    assert "NEXT assistant action MUST be the final answer" not in runtime
    assert "closed proof claims" not in runtime


def test_skill_keeps_representative_evidence_and_reuse_discipline() -> None:
    skill = SKILL.read_text(encoding="utf-8")

    assert "one strongest representative evidence instance per distinct causal role" in skill
    assert "do not refetch them for confidence" in skill
    assert "do not repeatedly retry adjacent lines" in skill
    assert "Reuse known evidence refs, ranges, source paths, source SHAs" in skill
