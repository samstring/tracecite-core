from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / "benchmarks" / "agent-investigation" / "pi_log_code_benchmark_host.ts"
RUNNER = ROOT / "benchmarks" / "agent-investigation" / "agent_flow_runner.py"
WORKFLOW = ROOT / ".github" / "workflows" / "pi-log-code-ab.yml"


def test_benchmark_host_is_observability_only() -> None:
    text = HOST.read_text(encoding="utf-8")

    assert 'pi.on("tool_call"' in text
    assert 'pi.on("tool_result"' in text
    assert "recordTraceCiteRuntimeAccess" in text
    assert "recordNativeRuntimeAccess" in text
    assert "Observability only" in text
    assert "return undefined" in text

    forbidden = (
        "registerTool",
        "guardReason",
        "TRACECITE_LOG_GUARD_ACTIVITY",
        "checkpointGate",
        "investigation_goal",
        "convergence_checkpoint",
        "root_cause",
        "hypothesis",
        "sufficiency",
    )
    for marker in forbidden:
        assert marker not in text


def test_formal_runner_keeps_native_capabilities_and_adds_tracecite_only_in_tracecite_mode() -> None:
    text = RUNNER.read_text(encoding="utf-8")

    assert 'choices=["native", "tracecite"]' in text
    assert "configure_tracecite_mcp" in text
    assert 'task = f"/skill:tracecite {question}" if args.mode == "tracecite" else question' in text
    assert 'command += ["--skill", str(skill_dir)]' in text
    assert "Deliberately no --tools allowlist" in text
    assert '"native_tools_policy": "agent-default-unrestricted"' in text
    assert '"tracecite_mcp_configured": args.mode == "tracecite"' in text
    assert "remove_mcp_config(source_root)" in text

    assert '"--tools"' not in text
    assert '"--no-skills"' not in text
    assert "pi_tracecite_extension_impl" not in text
    assert "pi_tracecite_bridge" not in text


def test_log_code_ab_calls_single_formal_runner_for_both_arms() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "agent_flow_runner.py" in text
    assert '--mode "$arm"' in text
    assert 'if [[ "$arm" == native ]]' in text
    assert "SOURCE_NATIVE" in text
    assert "SOURCE_TRACECITE" in text
    assert "isolated_source_trees" in text
    assert "repository: samstring/tracecite-mcp" in text
    assert "09215adbf01bd612b3115186951b9154320c5ca5" in text
    assert "tracecite-mcp/skills/tracecite" in text
    assert "formal-agent-runner-explicit-skill-standard-mcp" in text

    # The workflow must not duplicate Agent/MCP setup that belongs to the runner.
    assert '"command": "python"' not in text
    assert '"args": ["-m", "tracecite_mcp.server"]' not in text
    assert '"directTools": true' not in text
    assert '"toolPrefix": "none"' not in text
    assert "--tools read,bash,grep" not in text
    assert "pi_log_code_tracecite_extension.ts" not in text
    assert "TRACECITE_PI_SESSION=" not in text
    assert "TRACECITE_PI_ACTIVITY=" not in text


def test_native_and_tracecite_arm_do_not_share_mutable_source_tree() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert 'cp -a "$SOURCE_BASE" "$SOURCE_NATIVE"' in text
    assert 'cp -a "$SOURCE_BASE" "$SOURCE_TRACECITE"' in text
    assert 'source_root="$SOURCE_NATIVE"' in text
    assert 'source_root="$SOURCE_TRACECITE"' in text


def test_mcp_is_pinned_while_core_is_current_checkout() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "TRACECITE_MCP_REF:" in text
    assert "ref: ${{ env.TRACECITE_MCP_REF }}" in text
    assert "MCP did not resolve current Core checkout" in text
