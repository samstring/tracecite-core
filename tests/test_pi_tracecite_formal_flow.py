from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / "benchmarks" / "agent-investigation" / "pi_log_code_benchmark_host.ts"
RUNNER = ROOT / "benchmarks" / "agent-investigation" / "agent_flow_runner.py"
FLOW = ROOT / ".github" / "workflows" / "pi-tracecite-140039-smoke.yml"


def test_formal_flow_uses_single_runner_and_new_mcp() -> None:
    text = FLOW.read_text(encoding="utf-8")

    assert "agent_flow_runner.py" in text
    assert "--mode tracecite" in text
    assert '--skill-dir "$GITHUB_WORKSPACE/tracecite-mcp/skills/tracecite"' in text
    assert "09215adbf01bd612b3115186951b9154320c5ca5" in text
    assert "repository: samstring/tracecite-mcp" in text
    assert "python -m pip install -e ./tracecite-mcp --no-deps" in text
    assert "formal-agent-runner-explicit-tracecite-skill-standard-mcp-core" in text

    # MCP/Skill activation details belong to the shared runner, not this workflow.
    assert 'TASK="/skill:tracecite $QUESTION"' not in text
    assert '"command": "python"' not in text
    assert '"args": ["-m", "tracecite_mcp.server"]' not in text
    assert '"directTools": true' not in text
    assert '"toolPrefix": "none"' not in text
    assert "--tools read,bash,grep" not in text
    assert "pi_log_code_tracecite_extension.ts" not in text


def test_runner_explicitly_activates_tracecite_without_restricting_agent() -> None:
    text = RUNNER.read_text(encoding="utf-8")

    assert 'task = f"/skill:tracecite {question}" if args.mode == "tracecite" else question' in text
    assert 'command += ["--skill", str(skill_dir)]' in text
    assert "Deliberately no --tools allowlist" in text
    assert '"--tools"' not in text
    assert '"--no-skills"' not in text
    assert '"native_tools_policy": "agent-default-unrestricted"' in text


def test_formal_flow_produces_answer_quality_tokens_and_channel_observability() -> None:
    text = FLOW.read_text(encoding="utf-8")

    assert "pi_session_to_transcript.py" in text
    assert "log_code_score.py" in text
    assert "run_result.py" in text
    assert "root_cause_accurate" in text
    assert "evidence_chain_complete_and_bounded" in text
    assert "evidence_boundary_respected" in text
    assert "fresh_input_tokens" in text
    assert "cached_input_tokens" in text
    assert "fresh_plus_cached_input_tokens" in text
    assert "runtime_log_mcp_accesses" in text
    assert "native_runtime_evidence_accesses" in text
    assert "tracecite_evidence_channel_clean" in text
    assert "final answer is empty" in text
    assert "Agent runner exited with" in text


def test_host_observes_but_never_blocks_native_evidence_access() -> None:
    text = HOST.read_text(encoding="utf-8")

    assert "recordTraceCiteRuntimeAccess" in text
    assert "recordNativeRuntimeAccess" in text
    assert "Observability only" in text
    assert "return undefined" in text

    forbidden = (
        "TRACECITE_AGENT_RESOURCE_ROOTS",
        "withinNativeResource",
        "guardReason",
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
