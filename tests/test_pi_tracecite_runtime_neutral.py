from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
IMPL = ROOT / "benchmarks" / "agent-investigation" / "pi_tracecite_extension_impl.ts"
SKILL = ROOT / ".pi" / "skills" / "tracecite" / "SKILL.md"


def test_tracecite_runtime_returns_evidence_without_investigation_policy() -> None:
    text = IMPL.read_text(encoding="utf-8")
    for forbidden in (
        "agent_feedback",
        "convergence_checkpoint",
        "checkpoint_required",
        "investigation_goal",
        "reassess_before_next_evidence_call",
        "next_evidence_call_requires_investigation_goal",
        "supported_inference",
        "bounded_unknown",
        "material claim",
        "root cause",
        "sufficiency",
        "stop recommendation",
    ):
        assert forbidden not in text
    assert 'content: [{ type: "text" as const, text }]' in text


def test_pi_adapter_is_transparent_transport() -> None:
    text = IMPL.read_text(encoding="utf-8")
    assert "Pi is a transport adapter only" in text
    assert "Do not compact, normalize, sample, rename, or inject fields into the payload" in text
    assert "function output(text: string" in text
    assert "persistent_retrieval_session: true" in text
    assert "evidence_only: true" in text
    for removed_helper in (
        "compactCoverage",
        "compactProgress",
        "compactMatchedExisting",
        "neutralPreview",
    ):
        assert removed_helper not in text


def test_authorized_source_inventory_is_not_a_recommendation() -> None:
    text = IMPL.read_text(encoding="utf-8")
    assert "TRACECITE_EVIDENCE_FILES" in text
    assert "AUTHORIZED_EVIDENCE_FILES" in text
    assert "AUTHORIZED_EVIDENCE_HINT" in text
    assert "recommended_source" not in text
    assert "next_source" not in text


def test_skill_keeps_agent_runtime_responsibility_boundary() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    assert "The Agent remains responsible for hypotheses, investigation order, causal reasoning, conclusions, evidence sufficiency, and when to stop." in skill
    assert "These are Agent-side investigation choices, not Runtime planning or causal ranking." in skill
    assert "TraceCite does not decide:" in skill
    assert "whether evidence is sufficient" in skill
    assert "when to stop" in skill


def test_skill_keeps_generic_evidence_boundary() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    assert "A match is an observation, not proof of causality." in skill
    assert "`no_match` is a retrieval fact, not proof that an event never happened." in skill
    assert "An Evidence Index is navigation, not cited Evidence." in skill
    assert "Materialized text is Evidence; interpretation remains the Agent's responsibility." in skill


def test_skill_keeps_bounded_mechanical_transport_without_case_tuning() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    assert "Query searches with at most 5 matches return all matched Evidence directly." in skill
    assert "Query searches with more than 5 matches return `data.evidence_index`" in skill
    assert "`radius` is bounded to `0..30`." in skill
    assert "Replay does not create new Evidence or expand the raw evidence frontier." in skill


def test_retrieval_session_is_mechanical_state_only() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "RetrievalSession is mechanical evidence memory only." in skill
    assert "It does not contain or infer hypotheses, root cause, evidence sufficiency, or stop recommendations." in skill
    assert "persistent_retrieval_session: true" in runtime


def test_skill_has_no_case_specific_sync_or_container_runtime_policy() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    forbidden = [
        "blocked at acquire(X)",
        "Stack-frame orientation is not acquisition order",
        "holds A -> waits B",
        "deadlock/lock-order inversion",
        "containerd",
        "runc init",
        "shim",
        "FIFO",
        "ttrpc",
        "restart clears",
        "nearby pointer values",
    ]
    for token in forbidden:
        assert token not in skill


def test_skill_does_not_reintroduce_agent_stopping_policy() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    for removed_policy in (
        "Before each TraceCite call identify internally",
        "Claim identity is semantic, not query wording",
        "two consecutive non-advancing attempts",
        "stop reformulating",
        "the next assistant action must be the final answer",
        "NEXT assistant action MUST be the final answer",
    ):
        assert removed_policy not in skill
    assert "Stop when evidence is sufficient; do not continue merely to increase confidence." in skill
    assert "These are Agent-side investigation choices, not Runtime planning or causal ranking." in skill


def test_runtime_remains_mechanical_and_skill_owns_reasoning() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    runtime = IMPL.read_text(encoding="utf-8")
    assert "TraceCite supplies evidence mechanics." in skill
    assert "TraceCite never chooses hypotheses, causal conclusions, evidence sufficiency, or stopping." in skill
    assert "Pi is a transport adapter only" in runtime
    for forbidden in ("proof claims", "root_cause", "evidence_sufficient", "stop_recommended"):
        assert forbidden not in runtime

# candidate-first integration trigger; removed from process significance after this commit.
