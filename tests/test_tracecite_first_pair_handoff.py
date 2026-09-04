from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".pi" / "skills" / "tracecite" / "SKILL.md"
RUNTIME = ROOT / "benchmarks" / "agent-investigation" / "pi_tracecite_extension_impl.ts"


def test_first_materialized_component_pair_forces_direction_independent_handoff() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = RUNTIME.read_text(encoding="utf-8")

    assert "after **any** `tracecite_expand` materializes a synchronization-bearing path" in skill
    assert "whether the path was reached as the first representative" in skill
    assert "from a structural-diversity/navigation hint, or as a complementary path" in skill
    assert "privately bind the ordered pair `B -> A`" in skill
    assert "The next TraceCite invocation is fixed: `tracecite_search` for `B`'s receiver/type family" in skill
    assert "Do not first classify the path as representative versus complementary" in skill
    assert "search the complementary Lock/RLock spelling" in skill
    assert "Only if the materialized synchronization-bearing block contains no eligible outer application component `B`" in skill

    assert "first representative" not in runtime
    assert "ordered pair `B -> A`" not in runtime
    assert "receiver/type family" not in runtime
