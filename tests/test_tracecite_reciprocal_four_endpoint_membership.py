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

    assert "four-endpoint membership test" not in runtime
    assert "Both `A` and `B` must appear in both materialized paths" not in runtime
