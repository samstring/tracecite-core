from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".pi" / "skills" / "tracecite" / "SKILL.md"
IMPL = ROOT / "benchmarks" / "agent-investigation" / "pi_tracecite_extension_impl.ts"


def test_skill_prioritizes_causal_closure_before_symptom_census() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")

    assert "Prioritize causal closure over symptom census" in skill
    assert "unresolved causal edge or structurally distinct opposing acquisition path" in skill
    assert "Do not count equivalent waiters or chase downstream symptoms while the mechanism is unresolved" in skill
    assert "Prioritize causal closure over symptom census" not in runtime
    assert "structurally distinct opposing acquisition path" not in runtime


def test_skill_separates_structural_lock_order_from_current_holder_identity() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")

    assert "Separate **current-holder proof** from **structural lock-order proof**" in skill
    assert "two independent observed stacks directly materialize opposite nested acquisition paths" in skill
    assert "structural-path evidence never identifies the current holder" in skill
    assert "promotes an unobserved sibling function/path into the mechanism" in skill
    assert "is being held for a long time" in skill
    assert "use at most four additional evidence calls to locate a structurally distinct opposing path" in skill
    assert "structural lock-order proof" not in runtime
    assert "opposite nested acquisition paths" not in runtime
