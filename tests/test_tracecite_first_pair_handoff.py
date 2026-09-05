from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".pi" / "skills" / "tracecite" / "SKILL.md"
RUNTIME = ROOT / "benchmarks" / "agent-investigation" / "pi_tracecite_extension_impl.ts"


def test_reciprocal_pair_binding_waits_for_distinct_sync_path() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = RUNTIME.read_text(encoding="utf-8")

    assert "do **not** bind `B -> A` from the first representative synchronization-bearing path" in skill
    assert "pending ordered queue in the exact order TraceCite returned them" in skill
    assert "Materializing the representative does not clear that queue" in skill
    assert "the next TraceCite invocation must materialize the first still-unmaterialized candidate" in skill
    assert "do not replace that mandatory handoff with a fresh function/method query" in skill
    assert "continue only with the next still-pending orientation candidate" in skill
    assert "Once a pending distinct synchronization-bearing path materializes" in skill
    assert "the next TraceCite invocation is then fixed: `tracecite_search` for `B`'s receiver/type family" in skill

    assert "pending ordered queue" not in runtime
    assert "component-pair binding" not in runtime
    assert "receiver/type family" not in runtime
