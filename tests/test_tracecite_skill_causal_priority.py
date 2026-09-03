from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".pi" / "skills" / "tracecite" / "SKILL.md"
IMPL = ROOT / "benchmarks" / "agent-investigation" / "pi_tracecite_extension_impl.ts"


def test_skill_prioritizes_causal_closure_before_symptom_census() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")

    assert "Prioritize causal closure over symptom census" in skill
    assert "the unresolved causal edge" in skill
    assert "Do not count equivalent waiters or chase downstream symptoms while the mechanism is unresolved" in skill
    assert "Prioritize causal closure over symptom census" not in runtime
    assert "unresolved causal edge" not in runtime
