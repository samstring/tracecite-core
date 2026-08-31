from __future__ import annotations

import importlib.util
import json
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "benchmarks" / "agent-investigation" / "standard_mcp_benchmark.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("standard_mcp_benchmark", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_pi_config_exposes_direct_canonical_tools(tmp_path: Path) -> None:
    module = _load_module()
    workspace = tmp_path / "workspace"
    state = tmp_path / "state"
    workspace.mkdir()

    module.write_pi_config(workspace, state, python_executable="/usr/bin/python3")

    transport = json.loads((workspace / ".mcp.json").read_text(encoding="utf-8"))
    server = transport["mcpServers"]["tracecite"]
    assert server["command"] == "/usr/bin/python3"
    assert server["args"] == ["-m", "tracecite_mcp.server"]
    assert server["env"]["TRACECITE_MCP_ALLOWED_ROOTS"] == str(workspace.resolve())
    assert server["env"]["TRACECITE_MCP_STATE_DIR"] == str(state.resolve())

    adapter = json.loads((workspace / ".pi" / "mcp.json").read_text(encoding="utf-8"))
    assert adapter == {
        "settings": {"disableProxyTool": True},
        "mcpServers": {
            "tracecite": {
                "directTools": True,
                "toolPrefix": "none",
                "lifecycle": "eager",
            }
        },
    }


def test_codex_config_points_at_external_mcp_server(tmp_path: Path) -> None:
    module = _load_module()
    workspace = tmp_path / "workspace"
    state = tmp_path / "state"
    home = tmp_path / "codex-home"
    workspace.mkdir()

    module.write_codex_config(
        home,
        workspace,
        state,
        python_executable="/venv/bin/python",
        model="bench-model",
        provider="bench",
        base_url="https://example.test/v1",
        env_key="BENCH_API_KEY",
    )

    with (home / "config.toml").open("rb") as handle:
        config = tomllib.load(handle)
    assert config["model"] == "bench-model"
    assert config["model_provider"] == "bench"
    assert config["model_providers"]["bench"]["wire_api"] == "responses"
    server = config["mcp_servers"]["tracecite"]
    assert server["command"] == "/venv/bin/python"
    assert server["args"] == ["-m", "tracecite_mcp.server"]
    assert server["enabled_tools"] == list(module.CANONICAL_TRACECITE_TOOLS)
    assert server["env"]["TRACECITE_MCP_ALLOWED_ROOTS"] == str(workspace.resolve())
    assert server["env"]["TRACECITE_MCP_STATE_DIR"] == str(state.resolve())


def test_tracecite_transcript_contract_rejects_native_evidence_bypass(tmp_path: Path) -> None:
    module = _load_module()
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(
        "\n".join(
            [
                json.dumps({"type": "session", "mode": "pi-standard-mcp", "model": "m"}),
                json.dumps({"type": "tool", "name": "tracecite_retrieve", "output": "evidence"}),
                json.dumps({"type": "tool", "name": "grep", "output": "bypass"}),
                json.dumps({"type": "final", "answer": "answer"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = module.validate_tracecite_transcript(transcript, host="pi")
    assert result["tracecite_calls"] == 1
    assert result["forbidden_native_evidence_calls"] == ["grep"]
    assert result["contract_valid"] is False


def test_tracecite_transcript_contract_accepts_canonical_only_path(tmp_path: Path) -> None:
    module = _load_module()
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(
        "\n".join(
            [
                json.dumps({"type": "session", "mode": "codex-standard-mcp", "model": "m"}),
                json.dumps({"type": "tool", "name": "tracecite_retrieve", "output": "evidence"}),
                json.dumps({"type": "tool", "name": "tracecite_materialize", "output": "lines"}),
                json.dumps({"type": "final", "answer": "answer"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = module.validate_tracecite_transcript(transcript, host="codex")
    assert result["tracecite_tools_used"] == [
        "tracecite_materialize",
        "tracecite_retrieve",
    ]
    assert result["unknown_tracecite_tools"] == []
    assert result["forbidden_native_evidence_calls"] == []
    assert result["contract_valid"] is True
