from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".pi" / "skills" / "tracecite" / "SKILL.md"
IMPL = ROOT / "benchmarks" / "agent-investigation" / "pi_tracecite_extension_impl.ts"


def test_skill_prioritizes_named_component_reciprocal_search_over_new_hints() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "outer-component reciprocal search has strict precedence" in skill
    assert "follow a hint only if it directly materializes the same `B -> A` reciprocal candidate" in skill
    assert "Do not spend a call on a different waiter, WaitGroup, duplicate path, or unrelated synchronization hint" in skill
    assert "outer-component reciprocal search has strict precedence" not in runtime
    assert "same `B -> A` reciprocal candidate" not in runtime


def test_skill_forbids_same_block_expand_after_component_pair_is_materialized() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "Reciprocal-completion checkpoint" in skill
    assert "`tracecite_expand` on that same block or either already-materialized block is non-progressing and forbidden" in skill
    assert "The next call must be the outer-`B` receiver/type-family search" in skill
    assert "A claim that the `Boundary:` paragraph marks as unestablished must not be asserted as fact" in skill
    assert "Reciprocal-completion checkpoint" not in runtime
    assert "outer-`B` receiver/type-family search" not in runtime


def test_skill_anchors_reciprocal_pair_to_nearest_eligible_component() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "Pair-selection rule" in skill
    assert "nearest eligible non-stdlib receiver/type immediately above `A`" in skill
    assert "A direct vendored/third-party component is eligible" in skill
    assert "library provenance alone is not a reason to skip it" in skill
    assert "do not choose an arbitrary outermost caller" in skill
    assert "Direct impact must stop at the highest materialized blocked caller" in skill
    assert "nearest eligible non-stdlib receiver/type immediately above `A`" not in runtime
    assert "vendored/third-party component is eligible" not in runtime


def test_skill_has_hard_reciprocal_handoff_after_distinct_sync_path() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "Hard reciprocal handoff" in skill
    assert "the very next TraceCite invocation must be `tracecite_search` for that exact `B` receiver/type family" in skill
    assert "Remaining pending hints are suspended and must not be consumed first" in skill
    assert "This handoff overrides the rest of the investigation heuristics below" in skill
    assert "Hard reciprocal handoff" not in runtime
    assert "Remaining pending hints are suspended" not in runtime


def test_reciprocal_pair_preempts_remaining_orientation_hint_queue() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "The pending queue is only an orientation handoff" in skill
    assert "as soon as any materialized pending candidate exposes a synchronization-bearing path" in skill
    assert "stop consuming the remaining orientation queue" in skill
    assert "Resume the pending queue only if that reciprocal receiver/type-family search yields no usable candidate" in skill
    assert "duplicate representative/writer paths, WaitGroup paths, or unrelated waiters" in skill
    assert "pending queue is only an orientation handoff" not in runtime
    assert "stop consuming the remaining orientation queue" not in runtime


def test_pending_path_exclusively_binds_reciprocal_pair_before_impact_expansion() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "The pair must be extracted from that just-materialized pending candidate only" in skill
    assert "Do not substitute a caller from the representative path, combine callers from both paths, or redefine `B` from task-impact context" in skill
    assert "Until that reciprocal family search has been issued, re-expanding the representative path for caller/impact context is forbidden" in skill
    assert "just-materialized pending candidate only" not in runtime
    assert "re-expanding the representative path for caller/impact context is forbidden" not in runtime


def test_pending_path_can_bind_direct_dependency_component() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "A direct vendored or third-party receiver/type is eligible for `B`" in skill
    assert "do not discard it merely because it is library code" in skill
    assert "Exclude only runtime/stdlib synchronization plumbing and generic framework frames" in skill
    assert "direct vendored or third-party receiver/type is eligible" not in runtime
    assert "do not discard it merely because it is library code" not in runtime


def test_reciprocal_family_prefers_different_member_before_same_method_waiters() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "Reciprocal-family candidate selection is mandatory, not a preference" in skill
    assert "the next evidence call must expand the earliest such different-member hit in TraceCite result order" in skill
    assert "Same-method hits are non-progressing while a different-member hit is available" in skill
    assert "do not issue lifecycle/symptom searches before that candidate is materialized" in skill
    assert "Reciprocal-family candidate selection is mandatory" not in runtime
    assert "different-member hit" not in runtime


def test_pending_pair_binding_does_not_require_reciprocal_closure_first() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "Pair binding is a syntactic handoff, not a closure judgment" in skill
    assert "even when the pending acquisition is on the same synchronization domain as the representative" in skill
    assert "the mandatory `B` family search is what tests for that reverse path" in skill
    assert "Pair binding is a syntactic handoff" not in runtime
    assert "same synchronization domain as the representative" not in runtime
