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


def test_skill_anchors_reciprocal_pair_to_nearest_application_component() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "Pair-selection rule" in skill
    assert "nearest non-library application receiver/type immediately above `A`" in skill
    assert "do not choose an arbitrary outermost caller" in skill
    assert "Direct impact must stop at the highest materialized blocked caller" in skill
    assert "Pair-selection rule" not in runtime
    assert "nearest non-library application receiver/type immediately above `A`" not in runtime


def test_skill_has_hard_reciprocal_handoff_after_complementary_expand() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "Hard reciprocal handoff" in skill
    assert "the next TraceCite invocation is fixed" in skill
    assert "Do not expand the original representative block, the complementary block, or any already-materialized range first" in skill
    assert "This handoff overrides the rest of the investigation heuristics below" in skill
    assert "Hard reciprocal handoff" not in runtime
    assert "the next TraceCite invocation is fixed" not in runtime
