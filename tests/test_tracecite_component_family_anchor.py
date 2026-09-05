from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".pi" / "skills" / "tracecite" / "SKILL.md"
RUNTIME = ROOT / "benchmarks" / "agent-investigation" / "pi_tracecite_extension_impl.ts"


def test_skill_uses_component_family_not_exact_method_for_reciprocal_search() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = RUNTIME.read_text(encoding="utf-8")
    assert "component identity of outer component `B` at receiver/type-family level" in skill
    assert "not on the exact method already observed" in skill
    assert "match sibling methods of `B`" in skill
    assert "intentionally omit the method name" in skill
    assert "do not re-expand the original representative path merely to extend caller/impact context" in skill
    assert "reserve the next call for this component-family reciprocal search" in skill
    assert "component-family reciprocal" not in runtime
    assert "sibling methods" not in runtime


def test_receiver_family_query_is_syntax_robust() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = RUNTIME.read_text(encoding="utf-8")
    assert "Construct that receiver/type-family query from stable package/type tokens, not from the rendered punctuation between them" in skill
    assert "common stack renderings such as `pkg.(*Type).Method`" in skill
    assert "prefer a permissive separator such as `package.*Type` rather than a literal concatenation such as `package\\.Type`" in skill
    assert "Do not require the method name" in skill
    assert "Do not concatenate package and type with a literal dot unless that exact text is actually present in the evidence" in skill
    assert "Receiver-family query construction is syntax-robust" in skill
    assert "package.*Type" not in runtime
    assert "receiver-family query construction" not in runtime.lower()
