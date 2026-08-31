from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


CANONICAL_TRACECITE_TOOLS = (
    "tracecite_retrieve",
    "tracecite_materialize",
    "tracecite_replay",
    "tracecite_aggregate",
    "tracecite_traverse",
    "tracecite_verify",
)

PI_FORBIDDEN_NATIVE_EVIDENCE_TOOLS = {"read", "grep", "bash"}
CODEX_FORBIDDEN_NATIVE_EVIDENCE_TOOLS = {"shell_command", "command_execution"}


def _json_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def write_pi_config(
    workspace: Path,
    state_dir: Path,
    *,
    python_executable: str,
) -> None:
    workspace = workspace.resolve()
    state_dir = state_dir.resolve()
    (workspace / ".pi").mkdir(parents=True, exist_ok=True)

    transport = {
        "mcpServers": {
            "tracecite": {
                "command": python_executable,
                "args": ["-m", "tracecite_mcp.server"],
                "env": {
                    "TRACECITE_MCP_ALLOWED_ROOTS": str(workspace),
                    "TRACECITE_MCP_STATE_DIR": str(state_dir),
                },
            }
        }
    }
    adapter = {
        "settings": {"disableProxyTool": True},
        "mcpServers": {
            "tracecite": {
                "directTools": True,
                "toolPrefix": "none",
                "lifecycle": "eager",
            }
        },
    }
    (workspace / ".mcp.json").write_text(
        json.dumps(transport, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (workspace / ".pi" / "mcp.json").write_text(
        json.dumps(adapter, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_codex_config(
    codex_home: Path,
    workspace: Path,
    state_dir: Path,
    *,
    python_executable: str,
    model: str,
    provider: str,
    base_url: str,
    env_key: str,
    include_mcp: bool = True,
) -> None:
    codex_home = codex_home.resolve()
    workspace = workspace.resolve()
    state_dir = state_dir.resolve()
    codex_home.mkdir(parents=True, exist_ok=True)

    config = f"""model = {_json_string(model)}
model_provider = {_json_string(provider)}
approval_policy = "never"

[model_providers.{provider}]
name = "TraceCite benchmark provider"
base_url = {_json_string(base_url)}
env_key = {_json_string(env_key)}
wire_api = "responses"
requires_openai_auth = false
"""
    if include_mcp:
        tool_list = ", ".join(_json_string(name) for name in CANONICAL_TRACECITE_TOOLS)
        config += f"""
[mcp_servers.tracecite]
command = {_json_string(python_executable)}
args = ["-m", "tracecite_mcp.server"]
enabled_tools = [{tool_list}]
startup_timeout_sec = 30
tool_timeout_sec = 120

[mcp_servers.tracecite.env]
TRACECITE_MCP_ALLOWED_ROOTS = {_json_string(str(workspace))}
TRACECITE_MCP_STATE_DIR = {_json_string(str(state_dir))}
"""
    (codex_home / "config.toml").write_text(config, encoding="utf-8")


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        value = json.loads(raw)
        if isinstance(value, dict):
            events.append(value)
    return events


def validate_tracecite_transcript(path: Path, *, host: str) -> dict[str, Any]:
    events = _load_jsonl(path)
    tools = [event for event in events if event.get("type") == "tool"]
    names = [str(event.get("name") or "") for event in tools]
    tracecite_names = [name for name in names if name.startswith("tracecite_")]
    unknown_tracecite = sorted(set(tracecite_names) - set(CANONICAL_TRACECITE_TOOLS))
    forbidden_names = (
        PI_FORBIDDEN_NATIVE_EVIDENCE_TOOLS
        if host == "pi"
        else CODEX_FORBIDDEN_NATIVE_EVIDENCE_TOOLS
    )
    forbidden = [name for name in names if name in forbidden_names]
    final_events = [event for event in events if event.get("type") == "final"]
    final_answer = str(final_events[-1].get("answer") or "").strip() if final_events else ""

    result = {
        "schema_version": 1,
        "host": host,
        "canonical_tools": list(CANONICAL_TRACECITE_TOOLS),
        "tool_calls": len(tools),
        "tracecite_calls": len(tracecite_names),
        "tracecite_tools_used": sorted(set(tracecite_names)),
        "unknown_tracecite_tools": unknown_tracecite,
        "forbidden_native_evidence_calls": forbidden,
        "has_final_answer": bool(final_answer),
    }
    result["contract_valid"] = bool(
        tracecite_names
        and not unknown_tracecite
        and not forbidden
        and final_answer
    )
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare and validate TraceCite standard-MCP benchmark host plumbing."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    pi = sub.add_parser("configure-pi")
    pi.add_argument("--workspace", type=Path, required=True)
    pi.add_argument("--state-dir", type=Path, required=True)
    pi.add_argument("--python", default=sys.executable)

    codex = sub.add_parser("configure-codex")
    codex.add_argument("--codex-home", type=Path, required=True)
    codex.add_argument("--workspace", type=Path, required=True)
    codex.add_argument("--state-dir", type=Path, required=True)
    codex.add_argument("--python", default=sys.executable)
    codex.add_argument("--model", required=True)
    codex.add_argument("--provider", default="benchmark")
    codex.add_argument("--base-url", required=True)
    codex.add_argument("--env-key", default="OPENAI_API_KEY")
    codex.add_argument("--no-mcp", action="store_true")

    validate = sub.add_parser("validate-transcript")
    validate.add_argument("--transcript", type=Path, required=True)
    validate.add_argument("--host", choices=("pi", "codex"), required=True)
    validate.add_argument("--output", type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.command == "configure-pi":
        write_pi_config(args.workspace, args.state_dir, python_executable=args.python)
        return 0
    if args.command == "configure-codex":
        write_codex_config(
            args.codex_home,
            args.workspace,
            args.state_dir,
            python_executable=args.python,
            model=args.model,
            provider=args.provider,
            base_url=args.base_url,
            env_key=args.env_key,
            include_mcp=not args.no_mcp,
        )
        return 0
    if args.command == "validate-transcript":
        result = validate_tracecite_transcript(args.transcript, host=args.host)
        payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(payload, encoding="utf-8")
        print(payload, end="")
        return 0 if result["contract_valid"] else 2
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
