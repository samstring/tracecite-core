from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".pi" / "skills" / "tracecite" / "SKILL.md"
RUNTIME = ROOT / "benchmarks" / "agent-investigation" / "pi_tracecite_extension_impl.ts"


def test_reciprocal_pair_binding_waits_for_distinct_sync_path() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = RUNTIME.read_text(encoding="utf-8")

    assert "do **not** bind `B -> A` from the first representative synchronization-bearing path" in skill
    assert "nearest caller may be an incidental task/orchestration caller" in skill
    assert "unmaterialized `structural_diversity` / `navigation_hint` candidate" in skill
    assert "a **different synchronization-bearing stack block**" in skill
    assert "before any component-pair binding, WaitGroup branch, Lock/RLock spelling search" in skill
    assert "Once that distinct synchronization-bearing path is materialized" in skill
    assert "the next TraceCite invocation is then fixed: `tracecite_search` for `B`'s receiver/type family" in skill

    assert "incidental task/orchestration caller" not in runtime
    assert "component-pair binding" not in runtime
    assert "receiver/type family" not in runtime
