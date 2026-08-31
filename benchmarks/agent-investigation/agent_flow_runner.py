#!/usr/bin/env python3
"""Unified formal Agent runner for Native and TraceCite modes.

The runner owns only process setup and observability wiring.
It never chooses hypotheses, evidence sufficiency, causal conclusions, or stopping.

Native mode:
    Agent uses its own default/native tools and normal Agent resources.
    No TraceCite Skill or MCP server is configured by this runner.

TraceCite mode:
    The same Agent keeps its own native tools and normal Agent resources and additionally
    receives the explicit TraceCite Skill plus standard TraceCite MCP tools. Native
    runtime-evidence access is observed as channel contamination, never blocked.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys


TRACE_TOOLS = (
    "tracecite_retrieve",
    "tracecite_materialize",
    "tracecite_replay",
    "tracecite_aggregate",
    "tracecite_traverse",
    "tracecite_verify",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent", default="pi", choices=["pi"])
    parser.add_argument("--mode", required=True, choices=["native", "tracecite"])
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--runtime-log", required=True)
    parser.add_argument("--result-root", required=True)
    parser.add_argument("--question-file", required=True)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--thinking", default="off")
    parser.add_argument("--timeout-seconds", type=int, default=1200)
    parser.add_argument("--host-extension", required=True)
    parser.add_argument("--skill-dir")
    parser.add_argument("--mcp-evidence-root")
    parser.add_argument("--mcp-state-dir")
    return parser.parse_args()


def remove_mcp_config(source_root: Path) -> None:
    for path in (source_root / ".mcp.json", source_root / ".pi" / "mcp.json"):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def configure_tracecite_mcp(
    source_root: Path,
    evidence_root: Path,
    state_dir: Path,
) -> None:
    (source_root / ".pi").mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)
    (source_root / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "tracecite": {
                        "command": "python",
                        "args": ["-m", "tracecite_mcp.server"],
                        "env": {
                            "TRACECITE_MCP_ALLOWED_ROOTS": str(evidence_root),
                            "TRACECITE_MCP_STATE_DIR": str(state_dir),
                        },
                    }
                }
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (source_root / ".pi" / "mcp.json").write_text(
        json.dumps(
            {
                "settings": {"disableProxyTool": True},
                "mcpServers": {
                    "tracecite": {
                        "directTools": True,
                        "toolPrefix": "none",
                        "lifecycle": "eager",
                    }
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def build_prompt(mode: str, runtime_log: Path) -> str:
    base = (
        "You are a real coding agent debugging a failure with a complete bug-producing "
        "pre-fix source repository as your current working directory. Do not use the web, "
        "issue/PR content, remote git operations, or post-fix knowledge. A failing runtime "
        f"log is available at {runtime_log}. Use your normal Agent-native tools for source "
        "exploration. You own hypotheses, investigation order, causal reasoning, evidence "
        "sufficiency, final conclusions, and when to stop. Cite exact runtime-log or source "
        "path:L<line> references actually observed, and distinguish observation from inference."
    )
    if mode == "native":
        return (
            base
            + " This is Native mode. Use your own normal capabilities to inspect both the "
            "runtime log and source code. TraceCite is not part of this run."
        )
    return (
        base
        + " The user explicitly selected TraceCite for this investigation. Follow the TraceCite "
        "Agent Skill and use the standard TraceCite MCP Evidence Runtime for runtime-evidence "
        "handling. Your normal Agent-native capabilities remain available; the harness does not "
        "block or remove them. Direct native access to the runtime evidence, if you choose to do "
        "it, is recorded only as evidence-channel contamination for benchmark analysis."
    )


def terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=10)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    process.wait()


def run_pi(args: argparse.Namespace) -> int:
    source_root = Path(args.source_root).resolve()
    runtime_log = Path(args.runtime_log).resolve()
    result_root = Path(args.result_root).resolve()
    question_file = Path(args.question_file).resolve()
    host_extension = Path(args.host_extension).resolve()
    evidence_root = Path(args.mcp_evidence_root or runtime_log.parent).resolve()
    state_dir = Path(args.mcp_state_dir or (result_root / "tracecite-mcp-state")).resolve()
    skill_dir = Path(args.skill_dir).resolve() if args.skill_dir else None

    result_root.mkdir(parents=True, exist_ok=True)
    session_dir = result_root / f"pi-{args.mode}-session"
    session_dir.mkdir(parents=True, exist_ok=True)
    answer_path = result_root / f"pi-{args.mode}-answer.md"
    stderr_path = result_root / f"pi-{args.mode}-stderr.log"
    exit_path = result_root / f"pi-{args.mode}-exit.txt"
    metadata_path = result_root / f"agent-flow-{args.mode}.json"

    remove_mcp_config(source_root)
    if args.mode == "tracecite":
        if not skill_dir or not (skill_dir / "SKILL.md").is_file():
            raise SystemExit("TraceCite mode requires --skill-dir containing SKILL.md")
        configure_tracecite_mcp(source_root, evidence_root, state_dir)

    question = question_file.read_text(encoding="utf-8")
    task = f"/skill:tracecite {question}" if args.mode == "tracecite" else question
    prompt = build_prompt(args.mode, runtime_log)

    command = [
        "pi",
        "--provider",
        args.provider,
        "--model",
        args.model,
        "--api-key",
        args.api_key,
        "--thinking",
        args.thinking,
        "--mode",
        "text",
        "--print",
        "--session-dir",
        str(session_dir),
        "--extension",
        str(host_extension),
        "--no-prompt-templates",
        "--no-context-files",
        "--system-prompt",
        prompt,
    ]

    if args.mode == "tracecite":
        command += ["--skill", str(skill_dir)]

    # Deliberately no --tools allowlist and no --no-skills. The Agent keeps its
    # normal capability surface; TraceCite mode only adds one Skill + MCP server.
    command.append(task)

    env = os.environ.copy()
    env.update(
        {
            "TRACECITE_HOST_ACTIVITY": str(result_root / f"{args.mode}-host-tool-activity.json"),
            "TRACECITE_LOG_ACCESS_ACTIVITY": str(result_root / f"{args.mode}-tracecite-runtime-log-access.jsonl"),
            "TRACECITE_NATIVE_EVIDENCE_ACTIVITY": str(result_root / f"{args.mode}-native-runtime-evidence-access.jsonl"),
            "TRACECITE_RUNTIME_EVIDENCE_ROOT": str(evidence_root),
            "TRACECITE_RUNTIME_LOG": str(runtime_log),
        }
    )

    metadata = {
        "schema_version": 1,
        "agent": args.agent,
        "mode": args.mode,
        "native_tools_policy": "agent-default-unrestricted",
        "agent_skills_policy": "agent-default-plus-tracecite-in-tracecite-mode",
        "tracecite_skill_activation": "/skill:tracecite" if args.mode == "tracecite" else None,
        "tracecite_mcp_configured": args.mode == "tracecite",
        "tracecite_tools_expected": list(TRACE_TOOLS) if args.mode == "tracecite" else [],
        "runtime_log": str(runtime_log),
        "source_root": str(source_root),
    }
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

    code = 1
    process: subprocess.Popen[bytes] | None = None
    try:
        with answer_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            process = subprocess.Popen(
                command,
                cwd=source_root,
                env=env,
                stdout=stdout,
                stderr=stderr,
                start_new_session=True,
            )
            try:
                code = process.wait(timeout=args.timeout_seconds)
            except subprocess.TimeoutExpired:
                terminate_process_group(process)
                code = 124
    finally:
        if process is not None and process.poll() is None:
            terminate_process_group(process)
        # Mode isolation: a later Native arm must never inherit TraceCite MCP configuration.
        remove_mcp_config(source_root)
        exit_path.write_text(f"{code}\n", encoding="utf-8")

    return code


def main() -> int:
    args = parse_args()
    if args.agent != "pi":
        raise SystemExit(f"unsupported Agent adapter: {args.agent}")
    return run_pi(args)


if __name__ == "__main__":
    sys.exit(main())
