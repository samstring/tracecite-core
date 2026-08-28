from __future__ import annotations

import copy
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Mapping, Sequence

import free_shell
import openai_host as common
from tracecite.integrations import cli as trace_cli
from tracecite.integrations.context_engine import ContextEngine
from tracecite.integrations.evidence_ledger import EvidenceLedger
from tracecite.runtime.tools import search as tracecite_search


DEFAULT_BASE_URL = "https://api.gmi-serving.com/v1"
SYSTEM_PROMPT = """You are debugging a production incident from runtime evidence only.
Use only the benchmark tools provided to you. Do not use web search or outside knowledge.
Reconstruct the relevant sequence before giving a causal conclusion. Distinguish direct
observations from inference. If evidence is insufficient, say unknown/partial rather than
inventing a cause. Your final answer must cite concrete evidence IDs or precise source
locations that support the conclusion. Keep investigating until the evidence is sufficient
to give a supported final answer.
"""
_MAX_FINAL_CONTINUATIONS = 2
_FINAL_CONTINUATION_PROMPT = (
    "Your previous assistant response hit the provider output limit before a complete final "
    "answer was visible. Continue from where it stopped and finish the final answer concisely. "
    "Prioritize the causal conclusion and precise evidence citations; do not repeat sections "
    "that were already completed. Do not call more tools unless new evidence is actually needed."
)


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


def _choice(response: Mapping[str, Any]) -> dict[str, Any]:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("GMI chat completions response has no choices")
    first = choices[0]
    if not isinstance(first, Mapping):
        raise RuntimeError("GMI chat completions choice is not an object")
    return dict(first)


def _message(response: Mapping[str, Any]) -> dict[str, Any]:
    first = _choice(response)
    message = first.get("message")
    if not isinstance(message, Mapping):
        raise RuntimeError("GMI chat completions choice has no assistant message")
    return dict(message)


def _finish_reason(response: Mapping[str, Any]) -> str | None:
    value = _choice(response).get("finish_reason")
    return str(value) if isinstance(value, str) and value else None


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


def _incomplete_final(
    *,
    visible: str,
    usage: Mapping[str, int],
    finish_reason: str | None,
    max_output_tokens: int,
) -> bool:
    if finish_reason in {"length", "max_tokens"}:
        return True
    output_tokens = usage.get("output_tokens")
    if isinstance(output_tokens, int) and output_tokens >= max_output_tokens:
        return True
    return not visible and isinstance(output_tokens, int) and output_tokens > 0


class BenchmarkToolRuntime(common.ToolRuntime):
    """TraceCite runtime adapter with no benchmark-level output character caps."""

    def _tracecite_search(self, args: Mapping[str, Any]) -> str:
        path = common._safe_input(self.input_root, str(args.get("file") or ""))
        query = str(args.get("query") or "")
        if not query:
            raise ValueError("query must be non-empty")

        # Deliberately leave max_evidence/max_line_chars unset. The benchmark
        # must measure TraceCite's natural evidence selection rather than a host
        # character budget imposed only on one tool surface.
        payload = tracecite_search(
            path,
            query,
            regex=bool(args.get("regex")),
            snapshot=True,
            segmenter="auto",
            max_evidence=None,
            max_line_chars=None,
            cache=True,
        )
        if not isinstance(payload, Mapping):
            payload = payload.to_dict()
        canonical = copy.deepcopy(dict(payload))

        ledger_dir = self.scratch / "ledger"
        ledger_dir.mkdir(parents=True, exist_ok=True)
        result_id = EvidenceLedger(ledger_dir).store(canonical)
        data = dict(canonical.get("data") or {})
        data["result_id"] = result_id
        canonical["data"] = data

        baseline = trace_cli._compact_search_result(canonical, max_output_chars=None)
        baseline = trace_cli.lightweight_result(baseline)
        if self.mode != "tracecite_context":
            return trace_cli.render_frame(baseline)

        if not self.context_id:
            raise RuntimeError("tracecite_context requires context_id")
        projected = ContextEngine(ledger_dir, self.context_id).project_search(
            canonical,
            result_id=result_id,
        )
        delta = trace_cli._compact_search_result(projected, max_output_chars=None)
        delta = trace_cli.lightweight_result(delta)
        baseline_frame = trace_cli.render_frame(baseline)
        delta_frame = trace_cli.render_frame(delta)
        return delta_frame if len(delta_frame) < len(baseline_frame) else baseline_frame


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

    # Disable the common host's legacy global character clipping for every mode.
    common._truncate = lambda value, limit=None: value  # type: ignore[assignment]

    if mode == "free_shell":
        runtime = free_shell.Runtime(mode=mode, input_root=input_root, scratch=scratch, context_id=context_id)
        raw_tools = free_shell.tools(runtime.files)
    else:
        runtime = BenchmarkToolRuntime(mode=mode, input_root=input_root, scratch=scratch, context_id=context_id)
        raw_tools = common._tools_for_mode(mode, runtime.files)
    tools = _chat_tools(raw_tools)
    question = question_path.read_text(encoding="utf-8")
    file_names = ", ".join(path.name for path in runtime.files)
    prompt = f"{question}\n\nAvailable evidence files: {file_names}."
    conversation: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    max_output_tokens = int(os.environ.get("TRACECITE_BENCH_MAX_OUTPUT_TOKENS", "1800"))
    if max_output_tokens < 128 or max_output_tokens > 8192:
        raise ValueError("TRACECITE_BENCH_MAX_OUTPUT_TOKENS must be 128-8192")

    final_text = ""
    final_chunks: list[str] = []
    final_continuations = 0
    round_index = 0
    while True:
        round_index += 1
        response = _post_chat(
            {
                "model": model,
                "messages": conversation,
                "tools": tools,
                "tool_choice": "auto",
                "stream": False,
                "temperature": 0,
                "max_tokens": max_output_tokens,
            }
        )
        message = _message(response)
        visible = _visible_text(message)
        usage = _usage(response)
        finish_reason = _finish_reason(response)
        event: dict[str, Any] = {
            "type": "model",
            "round": round_index,
            "content": visible,
            "provider_response_id": response.get("id"),
            "finish_reason": finish_reason,
        }
        if usage:
            event["usage"] = usage
        common._append_event(transcript, event)

        calls = _tool_calls(message)
        assistant_message: dict[str, Any] = {"role": "assistant", "content": visible or None}
        if calls:
            assistant_message["tool_calls"] = calls
        conversation.append(assistant_message)

        if not calls:
            incomplete = _incomplete_final(
                visible=visible,
                usage=usage,
                finish_reason=finish_reason,
                max_output_tokens=max_output_tokens,
            )
            if incomplete and final_continuations < _MAX_FINAL_CONTINUATIONS:
                if visible:
                    final_chunks.append(visible)
                final_continuations += 1
                common._append_event(
                    transcript,
                    {
                        "type": "protocol",
                        "event": "final_continuation",
                        "round": round_index,
                        "attempt": final_continuations,
                        "finish_reason": finish_reason,
                        "visible_chars": len(visible),
                        "output_tokens": usage.get("output_tokens"),
                    },
                )
                conversation.append({"role": "user", "content": _FINAL_CONTINUATION_PROMPT})
                continue

            if incomplete:
                common._append_event(
                    transcript,
                    {
                        "type": "protocol",
                        "event": "final_incomplete_after_retries",
                        "round": round_index,
                        "attempts": final_continuations,
                        "finish_reason": finish_reason,
                        "visible_chars": len(visible),
                        "output_tokens": usage.get("output_tokens"),
                    },
                )
            chunks = [*final_chunks]
            if visible:
                chunks.append(visible)
            final_text = "\n\n".join(chunks).strip()
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
