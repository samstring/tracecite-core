from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
IMPL = ROOT / "benchmarks" / "agent-investigation" / "pi_tracecite_extension_impl.ts"
SKILL = ROOT / ".pi" / "skills" / "tracecite" / "SKILL.md"


def test_pending_pair_checkpoint_preempts_other_reasoning() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "**Mandatory pending-pair checkpoint:**" in skill
    assert "the next tool invocation is fixed: `tracecite_search` for the exact `B` receiver/type family" in skill
    assert "This checkpoint is triggered by stack shape alone" in skill
    assert "do not consume another pending hint first" in skill
    assert "The family search itself is the required test for a reverse `A -> B` path" in skill
    assert "Mandatory pending-pair checkpoint" not in runtime
    assert "stack shape alone" not in runtime
