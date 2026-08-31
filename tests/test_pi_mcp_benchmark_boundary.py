from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / "benchmarks" / "agent-investigation" / "pi_log_code_benchmark_host.ts"
WORKFLOW = ROOT / ".github" / "workflows" / "pi-log-code-ab.yml"


def test_benchmark_host_is_observability_and_guard_only() -> None:
    text = HOST.read_text(encoding="utf-8")

    assert "pi.on(\"tool_call\"" in text
    assert "pi.on(\"tool_result\"" in text
    assert "recordRuntimeLogAccess" in text
    assert "guardReason" in text

    forbidden = (
        "registerTool",
        "pi_tracecite_extension_impl",
        "pi_tracecite_bridge",
        "checkpointGate",
        "investigation_goal",
        "convergence_checkpoint",
        "root_cause",
        "hypothesis",
        "sufficiency",
    )
    for marker in forbidden:
        assert marker not in text


def test_log_code_ab_uses_standard_mcp_and_external_agent_skill() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "repository: samstring/tracecite-mcp" in text
    assert "python -m pip install -e ./tracecite-mcp --no-deps" in text
    assert '"command": "python"' in text
    assert '"args": ["-m", "tracecite_mcp.server"]' in text
    assert '"directTools": true' in text
    assert '"toolPrefix": "none"' in text
    assert "pi_log_code_benchmark_host.ts" in text
    assert "tracecite-mcp/skills/tracecite/SKILL.md" in text
    assert "standard-mcp-plus-agent-skill" in text

    assert "--extension \"$GITHUB_WORKSPACE/benchmarks/agent-investigation/pi_log_code_tracecite_extension.ts\"" not in text
    assert "TRACECITE_PI_SESSION=" not in text
    assert "TRACECITE_PI_ACTIVITY=" not in text


def test_mcp_is_pinned_while_core_is_current_checkout() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "TRACECITE_MCP_REF:" in text
    assert "ref: ${{ env.TRACECITE_MCP_REF }}" in text
    assert "MCP did not resolve current Core checkout" in text
