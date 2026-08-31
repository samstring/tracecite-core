from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / "benchmarks" / "agent-investigation" / "pi_log_code_benchmark_host.ts"
FLOW = ROOT / ".github" / "workflows" / "pi-tracecite-140039-smoke.yml"


def test_formal_flow_explicitly_activates_full_tracecite_skill() -> None:
    text = FLOW.read_text(encoding="utf-8")

    assert 'TASK="/skill:tracecite $QUESTION"' in text
    assert '--no-skills --skill "$SKILL_DIR"' in text
    assert 'SKILL_DIR="$GITHUB_WORKSPACE/tracecite-mcp/skills/tracecite"' in text
    assert 'TRACECITE_AGENT_RESOURCE_ROOTS="$SKILL_DIR"' in text
    assert "TraceCite MCP Agent Skill" in text
    assert "Golden rules" in text
    assert "skill_loaded_before_investigation" in text


def test_formal_flow_is_standard_mcp_to_current_core() -> None:
    text = FLOW.read_text(encoding="utf-8")

    assert "repository: samstring/tracecite-mcp" in text
    assert "TRACECITE_MCP_REF:" in text
    assert '"command": "python"' in text
    assert '"args": ["-m", "tracecite_mcp.server"]' in text
    assert '"directTools": true' in text
    assert '"toolPrefix": "none"' in text
    assert "python -m pip install -e ./tracecite-mcp --no-deps" in text
    assert "pi_log_code_benchmark_host.ts" in text
    assert "explicit-tracecite-skill-standard-mcp-core" in text

    assert "pi_log_code_tracecite_extension.ts" not in text
    assert "TRACECITE_PI_SESSION=" not in text
    assert "TRACECITE_PI_ACTIVITY=" not in text


def test_formal_flow_produces_answer_score_tokens_and_runtime_contract() -> None:
    text = FLOW.read_text(encoding="utf-8")

    assert "pi_session_to_transcript.py" in text
    assert "log_code_score.py" in text
    assert "run_result.py" in text
    assert "root_cause_accurate" in text
    assert "evidence_chain_complete_and_bounded" in text
    assert "fresh_input_tokens" in text
    assert "cached_input_tokens" in text
    assert "fresh_plus_cached_input_tokens" in text
    assert "runtime_log_mcp_accesses" in text
    assert "final answer is empty" in text
    assert "Pi exited with" in text


def test_host_resource_allowlist_is_mechanical_not_agent_policy() -> None:
    text = HOST.read_text(encoding="utf-8")

    assert "TRACECITE_AGENT_RESOURCE_ROOTS" in text
    assert "withinNativeResource" in text
    assert "AGENT_RESOURCE_ROOTS" in text

    forbidden = (
        "registerTool",
        "checkpointGate",
        "investigation_goal",
        "convergence_checkpoint",
        "root_cause",
        "hypothesis",
        "sufficiency",
    )
    for marker in forbidden:
        assert marker not in text
