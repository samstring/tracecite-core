from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".pi" / "skills" / "tracecite" / "SKILL.md"
RUNTIME = ROOT / "benchmarks" / "agent-investigation" / "pi_tracecite_extension_impl.ts"


def test_stack_only_counts_all_tracecite_invocations_and_reserves_last_reciprocal_slot() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = RUNTIME.read_text(encoding="utf-8")

    assert "Every tool invocation counts, including source errors, `no_match`, `no_new_evidence`, and refused calls" in skill
    assert "source repair does not refund or reset a slot" in skill
    assert "If only one evidence-call slot remains, that slot is reserved exclusively for this outer-component-family reciprocal search" in skill
    assert "otherwise finalize unclosed" in skill
    assert "After call 6 returns, the same model turn must go directly to the terminal four-paragraph answer" in skill
    assert "attempt any seventh evidence call" in skill

    # These are Agent/Skill investigation and stopping rules, not Runtime policy.
    assert "outer-component-family reciprocal search" not in runtime
    assert "terminal four-paragraph answer" not in runtime
    assert "source repair does not refund" not in runtime
