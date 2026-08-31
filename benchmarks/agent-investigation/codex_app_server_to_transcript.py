from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Mapping, TextIO


class AppServer:
    def __init__(self, *, stderr: TextIO) -> None:
        self.proc = subprocess.Popen(
            ["codex", "app-server", "--listen", "stdio://"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr,
            text=True,
            bufsize=1,
            env=os.environ.copy(),
        )
        if self.proc.stdin is None or self.proc.stdout is None:
            raise RuntimeError("failed to open Codex app-server stdio")
        self.stdin = self.proc.stdin
        self.stdout = self.proc.stdout
        self.next_id = 1

    def write(self, payload: Mapping[str, Any]) -> None:
        self.stdin.write(json.dumps(dict(payload), ensure_ascii=False) + "\n")
        self.stdin.flush()

    def request(self, method: str, params: Mapping[str, Any] | None = None) -> int:
        request_id = self.next_id
        self.next_id += 1
        payload: dict[str, Any] = {"id": request_id, "method": method}
        if params is not None:
            payload["params"] = dict(params)
        self.write(payload)
        return request_id

    def read(self) -> dict[str, Any]:
        line = self.stdout.readline()
        if not line:
            raise RuntimeError(
                f"Codex app-server exited unexpectedly with code {self.proc.poll()}"
            )
        value = json.loads(line)
        if not isinstance(value, dict):
            raise RuntimeError(f"unexpected Codex app-server message: {value!r}")
        return value

    def close(self) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)


def _reject_interactive_request(server: AppServer, message: Mapping[str, Any]) -> None:
    request_id = message.get("id")
    method = message.get("method")
    if request_id is None or not isinstance(method, str):
        return
    server.write(
        {
            "id": request_id,
            "error": {
                "code": -32000,
                "message": f"benchmark client does not service interactive request {method}",
            },
        }
    )


def _wait_response(server: AppServer, request_id: int, raw: TextIO) -> dict[str, Any]:
    while True:
        message = server.read()
        raw.write(json.dumps(message, ensure_ascii=False, sort_keys=True) + "\n")
        raw.flush()
        if message.get("id") == request_id:
            if message.get("error") is not None:
                raise RuntimeError(f"Codex request failed: {message['error']!r}")
            result = message.get("result")
            return dict(result) if isinstance(result, Mapping) else {}
        _reject_interactive_request(server, message)


def _mcp_output(item: Mapping[str, Any]) -> str:
    result = item.get("result")
    if not isinstance(result, Mapping):
        error = item.get("error")
        return json.dumps(error, ensure_ascii=False, sort_keys=True) if error else ""
    structured = result.get("structuredContent")
    if structured is not None:
        return json.dumps(structured, ensure_ascii=False, sort_keys=True)
    content = result.get("content")
    if isinstance(content, list):
        texts = [
            str(value.get("text"))
            for value in content
            if isinstance(value, Mapping)
            and value.get("type") == "text"
            and isinstance(value.get("text"), str)
        ]
        if texts:
            return "\n".join(texts)
    return json.dumps(dict(result), ensure_ascii=False, sort_keys=True)


def _usage_event(token_usage: Mapping[str, Any]) -> dict[str, Any] | None:
    total = token_usage.get("total")
    if not isinstance(total, Mapping):
        return None
    return {
        "type": "model",
        "usage": {
            "input_tokens": total.get("inputTokens"),
            "output_tokens": total.get("outputTokens"),
            "reasoning_tokens": total.get("reasoningOutputTokens"),
            "cached_input_tokens": total.get("cachedInputTokens"),
            "cache_read_input_tokens": total.get("cachedInputTokens"),
            "cache_creation_input_tokens": total.get("cacheWriteInputTokens"),
        },
    }


def _default_mode(output_dir: Path) -> str:
    return "codex-native" if output_dir.name == "native" else "codex-standard-mcp"


def run(
    *,
    workspace: Path,
    question: str,
    output_dir: Path,
    model: str,
    provider: str,
    developer_instructions: str,
    mode: str | None = None,
) -> None:
    workspace = workspace.resolve()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_path = output_dir / "codex-app-server.jsonl"
    transcript_path = output_dir / "codex-transcript.jsonl"
    answer_path = output_dir / "codex-answer.md"
    stderr_path = output_dir / "codex-stderr.log"

    transcript: list[dict[str, Any]] = [
        {"type": "session", "mode": mode or _default_mode(output_dir), "model": model}
    ]
    final_answer = ""
    latest_usage: Mapping[str, Any] | None = None

    with stderr_path.open("w", encoding="utf-8") as stderr, raw_path.open(
        "w", encoding="utf-8"
    ) as raw:
        server = AppServer(stderr=stderr)
        try:
            request_id = server.request(
                "initialize",
                {
                    "clientInfo": {
                        "name": "tracecite-core-benchmark",
                        "title": "TraceCite Core Benchmark",
                        "version": "1.0.0",
                    },
                    "capabilities": {"experimentalApi": True},
                },
            )
            _wait_response(server, request_id, raw)
            server.write({"method": "initialized"})

            request_id = server.request(
                "thread/start",
                {
                    "model": model,
                    "modelProvider": provider,
                    "cwd": str(workspace),
                    "ephemeral": True,
                    "approvalPolicy": "never",
                    "sandbox": "read-only",
                    "developerInstructions": developer_instructions,
                },
            )
            thread_result = _wait_response(server, request_id, raw)
            thread_id = str(((thread_result.get("thread") or {}).get("id")) or "")
            if not thread_id:
                raise RuntimeError(f"thread/start returned no thread id: {thread_result!r}")

            request_id = server.request(
                "turn/start",
                {
                    "threadId": thread_id,
                    "input": [{"type": "text", "text": question, "textElements": []}],
                    "model": model,
                },
            )
            turn_result = _wait_response(server, request_id, raw)
            turn_id = str(((turn_result.get("turn") or {}).get("id")) or "")
            if not turn_id:
                raise RuntimeError(f"turn/start returned no turn id: {turn_result!r}")

            while True:
                message = server.read()
                raw.write(json.dumps(message, ensure_ascii=False, sort_keys=True) + "\n")
                raw.flush()
                _reject_interactive_request(server, message)
                method = message.get("method")
                params = message.get("params")
                if not isinstance(params, Mapping):
                    continue
                if params.get("turnId") not in (None, turn_id):
                    continue

                if method == "thread/tokenUsage/updated":
                    token_usage = params.get("tokenUsage")
                    if isinstance(token_usage, Mapping):
                        latest_usage = token_usage
                    continue

                if method == "item/completed":
                    item = params.get("item")
                    if not isinstance(item, Mapping):
                        continue
                    item_type = str(item.get("type") or "")
                    if item_type == "mcpToolCall":
                        event: dict[str, Any] = {
                            "type": "tool",
                            "name": str(item.get("tool") or "unknown"),
                            "server": str(item.get("server") or ""),
                            "output": _mcp_output(item),
                        }
                        arguments = item.get("arguments")
                        if isinstance(arguments, Mapping):
                            event["arguments"] = dict(arguments)
                        duration = item.get("durationMs")
                        if isinstance(duration, (int, float)) and not isinstance(duration, bool):
                            event["duration_ms"] = duration
                        transcript.append(event)
                    elif item_type == "commandExecution":
                        transcript.append(
                            {
                                "type": "tool",
                                "name": "command_execution",
                                "arguments": {"command": item.get("command")},
                                "output": str(item.get("aggregatedOutput") or ""),
                            }
                        )
                    elif item_type == "agentMessage":
                        text = item.get("text")
                        phase = item.get("phase")
                        if isinstance(text, str) and phase in (None, "final_answer", "finalAnswer"):
                            final_answer = text
                    continue

                if method == "turn/completed":
                    turn = params.get("turn")
                    if not isinstance(turn, Mapping) or str(turn.get("id") or "") != turn_id:
                        continue
                    status = str(turn.get("status") or "")
                    if status != "completed":
                        raise RuntimeError(f"Codex turn ended with status {status}: {turn!r}")
                    break
        finally:
            server.close()

    if latest_usage is not None:
        usage = _usage_event(latest_usage)
        if usage is not None:
            transcript.append(usage)
    transcript.append({"type": "final", "answer": final_answer.strip()})
    answer_path.write_text(final_answer.strip() + "\n", encoding="utf-8")
    with transcript_path.open("w", encoding="utf-8") as handle:
        for event in transcript:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one Codex app-server turn and normalize activity for TraceCite benchmarks."
    )
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--question-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--mode")
    parser.add_argument("--model", required=True)
    parser.add_argument("--provider", default="benchmark")
    parser.add_argument("--developer-instructions-file", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    run(
        workspace=args.workspace,
        question=args.question_file.read_text(encoding="utf-8"),
        output_dir=args.output_dir,
        mode=args.mode,
        model=args.model,
        provider=args.provider,
        developer_instructions=args.developer_instructions_file.read_text(encoding="utf-8"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
