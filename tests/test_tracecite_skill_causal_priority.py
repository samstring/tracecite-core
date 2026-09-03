from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".pi" / "skills" / "tracecite" / "SKILL.md"
IMPL = ROOT / "benchmarks" / "agent-investigation" / "pi_tracecite_extension_impl.ts"


def test_skill_prioritizes_causal_closure_before_symptom_census() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")

    assert "Build the **smallest supported causal proof**" in skill
    assert "Once a path crosses from component A into component B, the next useful search is for the reverse B-to-A nesting" in skill
    assert "Do not spend calls proving that many equivalent waiters exist" in skill
    assert "smallest supported causal proof" not in runtime
    assert "reverse B-to-A nesting" not in runtime


def test_skill_separates_structural_lock_order_from_current_holder_identity() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")

    assert "This supports only the **structural inversion / cyclic-wait mechanism**" in skill
    assert "two **observed stack paths** directly show reversed component nesting" in skill
    assert "It does not identify current holders" in skill
    assert "Current holder identity remains `bounded_unknown`" in skill
    assert "held for a long time" in skill
    assert "use at most four additional calls to find a structurally distinct reciprocal path" in skill
    assert "structural inversion / cyclic-wait mechanism" not in runtime
    assert "reversed component nesting" not in runtime
