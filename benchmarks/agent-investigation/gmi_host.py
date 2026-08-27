from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Mapping, Sequence

import openai_host as common


DEFAULT_BASE_URL = "https://api.gmi-serving.com/v1"


def _chat_tools(tools: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for tool in tools:
        converted.append(
            {
                "type": "function",
                "function": {
                    "name": str(tool.get("name") or ""),
                    "description": str(tool.get("description") or ""),
                    "parameters": dict(tool.get("parameters") or {}),
                },
            }
        )
    return converted


def _post_chat(payload: Mapping[str, Any]) -> dict[str, Any]:
    api_key = os.environ.get(common.API_KEY_ENV, "").strip()
    if not api_key:
        raise RuntimeError(f"{common.API_KEY_ENV} is required for the GMI benchmark host")
    base = os.environ.get("OPENAI_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    request = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps(dict(payload)).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "TraceCite-Agent-Benchmark/1",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            value = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GMI API HTTP {exc.code}: {body[:2000]}") from exc
    if not isinstance(value, dict):
        raise RuntimeError("GMI chat completions API returned a non-object payload")
    return value


def _usage(response: Mapping[str, Any]) -> dict[str, int]:
    raw = response.get("usage")
    if not isinstance(raw, Mapping):
        return {}
    result: dict[str, int] = {}
    for source, target in (
        ("prompt_tokens", "input_tokens"),
        ("completion_tokens", "output_tokens"),
        ("input_tokens", "input_tokens"),
        ("output_tokens", "output_tokens"),
    ):
        value = raw.get(source)
        if isinstance(value, int) and value >= 0:
            result[target] = value
    prompt_details = raw.get("prompt_tokens_details") or raw.get("input_tokens_details")
    if isinstance(prompt_details, Mapping):
        cached = prompt_details.get("cached_tokens")
        if isinstance(cached, int) and cached >= 0:
            result["cached_input_tokens"] = cached
    completion_details = raw.get("completion_tokens_details") or raw.get("output_tokens_details")
    if isinstance(completion_details, Mapping):
        reasoning = completion_details.get("reasoning_tokens")
        if isinstance(reasoning, int) and reasoning >= 0:
            result["reasoning_tokens"] = reasoning
    return result


def _message(response: Mapping[str, Any]) -> dict[str, Any]:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("GMI chat completions response has no choices")
    first = choices[0]
    if not isinstance(first, Mapping):
        raise RuntimeError("GMI chat completions choice is not an object")
    message = first.get("message")
    if not isinstance(message, Mapping):
        raise RuntimeError("GMI chat completions choice has no assistant message")
    return dict(message)


def _visible_text(message: Mapping[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        chunks: list[str] = []
        for part in content:
            if isinstance(part, Mapping):
                text = part.get("text")
                if isinstance(text, str):
                    chunks.append(text)
        return "\n".join(chunks).strip()
    return ""


def _tool_calls(message: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = message.get("tool_calls")
    if not isinstance(raw, list):
        return []
    calls: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        function = item.get("function")
        if not isinstance(function, Mapping):
            continue
        calls.append(
            {
                "id": str(item.get("id") or ""),
                "type": "function",
                "function": {
                    "name": str(function.get("name") or ""),
                    "arguments": function.get("arguments") if isinstance(function.get("arguments"), str) else "{}",
                },
            }
        )
    return calls


def run() -> int:
    mode = os.environ.get("TRACECITE_BENCH_MODE", "").strip()
    model = os.environ.get("TRACECITE_BENCH_MODEL", "").strip()
    question_path = common._env_path("TRACECITE_BENCH_QUESTION")
    input_root = common._env_path("TRACECITE_BENCH_INPUTS")
    scratch = common._env_path("TRACECITE_BENCH_SCRATCH")
    transcript = common._env_path("TRACECITE_BENCH_TRANSCRIPT")
    context_id = os.environ.get("TRACECITE_BENCH_CONTEXT_ID", "").strip()
    if not model:
        raise RuntimeError("TRACECITE_BENCH_MODEL is required")

    runtime = common.ToolRuntime(mode=mode, input_root=input_root, scratch=scratch, context_id=context_id)
    tools = _chat_tools(common._tools_for_mode(mode, runtime.files))
    question = question_path.read_text(encoding="utf-8")
    file_names = ", ".join(path.name for path in runtime.files)
    prompt = f"{question}\n\nAvailable evidence files: {file_names}."
    conversation: list[dict[str, Any]] = [
        {"role": "system", "content": common.SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    max_turns = int(os.environ.get("TRACECITE_BENCH_MAX_TURNS", "10"))
    if max_turns < 1 or max_turns > 30:
        raise ValueError("TRACECITE_BENCH_MAX_TURNS must be 1-30")
    max_output_tokens = int(os.environ.get("TRACECITE_BENCH_MAX_OUTPUT_TOKENS", "1800"))
    if max_output_tokens < 128 or max_output_tokens > 8192:
        raise ValueError("TRACECITE_BENCH_MAX_OUTPUT_TOKENS must be 128-8192")

    final_text = ""
    for round_index in range(1, max_turns + 1):
        response = _post_chat(
            {
                "model": model,
                "messages": conversation,
                "tools": tools,
                "tool_choice": "auto",
                "stream": False,
                "max_tokens": max_output_tokens,
            }
        )
        message = _message(response)
        visible = _visible_text(message)
        event: dict[str, Any] = {
            "type": "model",
            "round": round_index,
            "content": visible,
            "provider_response_id": response.get("id"),
        }
        usage = _usage(response)
        if usage:
            event["usage"] = usage
        common._append_event(transcript, event)

        calls = _tool_calls(message)
        assistant_message: dict[str, Any] = {"role": "assistant", "content": visible or None}
        if calls:
            assistant_message["tool_calls"] = calls
        conversation.append(assistant_message)

        if not calls:
            final_text = visible
            break

        for call in calls:
            function = call["function"]
            name = str(function.get("name") or "")
            call_id = str(call.get("id") or "")
            raw_arguments = function.get("arguments")
            args: dict[str, Any] = {}
            try:
                decoded = json.loads(raw_arguments) if isinstance(raw_arguments, str) else {}
                if not isinstance(decoded, dict):
                    raise ValueError("tool arguments must decode to an object")
                args = decoded
                started = time.monotonic()
                output = runtime.call(name, args)
                duration_ms = round((time.monotonic() - started) * 1000, 3)
            except Exception as exc:
                output = json.dumps({"error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False)
                duration_ms = 0.0
            output = common._truncate(output)
            common._append_event(
                transcript,
                {
                    "type": "tool",
                    "round": round_index,
                    "tool": name,
                    "input": args,
                    "output": output,
                    "duration_ms": duration_ms,
                },
            )
            conversation.append({"role": "tool", "tool_call_id": call_id, "content": output})
    else:
        final_text = "Investigation stopped because the model-turn budget was exhausted."

    evidence = sorted(set(common._EVIDENCE_ID_RE.findall(final_text)))
    common._append_event(transcript, {"type": "final", "answer": final_text, "evidence": evidence})
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(run())
    except Exception as exc:
        transcript_value = os.environ.get("TRACECITE_BENCH_TRANSCRIPT", "").strip()
        if transcript_value:
            try:
                common._append_event(
                    Path(transcript_value),
                    {"type": "host_error", "error": type(exc).__name__, "message": str(exc)},
                )
            except Exception:
                pass
        print(f"benchmark host failed: {type(exc).__name__}: {exc}", file=os.sys.stderr)
        raise
