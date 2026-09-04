from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".pi" / "skills" / "tracecite" / "SKILL.md"
RUNTIME = ROOT / "benchmarks" / "agent-investigation" / "pi_tracecite_extension_impl.ts"


def test_reciprocal_closure_requires_both_components_in_both_paths() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = RUNTIME.read_text(encoding="utf-8")

    assert "Both `A` and `B` must appear in both materialized paths" in skill
    assert "`A ... B ... acquire(domain_B)`" in skill
    assert "`B ... A ... acquire(domain_A)`" in skill
    assert "`domain_A` and `domain_B` distinct synchronization acquisition sites/domains" in skill
    assert "Different outer callers that merely converge on the same inner lock" in skill
    assert "do not satisfy this four-endpoint membership test" in skill
    assert "If either component appears in only one path, reciprocal closure is false" in skill
    assert "The very next evidence call must search the exact receiver/type-family identity of outer component `B`" in skill
    assert "do not substitute a package-wide token, subsystem path, waiter census, or another synchronization primitive" in skill
    assert "the next reciprocal evidence call must materialize the most relevant synchronization-bearing hint" in skill
    assert "A no-match on one complementary primitive spelling cannot support absence" in skill
    assert "tracecite_host_activity_summary.total_tool_calls" in skill
    assert "authoritative cumulative evidence-call count" in skill

    assert "four-endpoint membership test" not in runtime
    assert "Both `A` and `B` must appear in both materialized paths" not in runtime
    assert "The very next evidence call must search the exact receiver/type-family identity of outer component `B`" not in runtime
    assert "the next reciprocal evidence call must materialize the most relevant synchronization-bearing hint" not in runtime
    assert "tracecite_host_activity_summary.total_tool_calls" not in runtime
