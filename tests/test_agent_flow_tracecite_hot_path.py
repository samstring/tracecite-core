from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _runner_module():
    path = Path(__file__).resolve().parents[1] / "benchmarks" / "agent-investigation" / "agent_flow_runner.py"
    spec = importlib.util.spec_from_file_location("agent_flow_runner_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_tracecite_host_profile_is_direct_and_script_free(tmp_path) -> None:
    runner = _runner_module()
    workspace = tmp_path / "workspace"
    evidence = tmp_path / "evidence"
    state = tmp_path / "state"
    workspace.mkdir()
    evidence.mkdir()

    runner.configure_tracecite_mcp(workspace, evidence, state)

    config = json.loads((workspace / ".pi" / "mcp.json").read_text(encoding="utf-8"))
    assert config["settings"] == {
        "disableProxyTool": True,
        "scriptMode": False,
    }
    server = config["mcpServers"]["tracecite"]
    expected = list(runner.TRACE_HOT_PATH_TOOLS)
    assert server["directTools"] == expected
    assert server["includeTools"] == expected
    assert expected == [
        "tracecite_analyze",
        "tracecite_run",
        "tracecite_materialize",
        "tracecite_replay",
    ]
