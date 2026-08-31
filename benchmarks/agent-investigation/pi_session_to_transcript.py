from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping


def _text_content(value: Any) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        return ""
    parts: list[str] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        if str(item.get("type") or "") == "text":
            text = str(item.get("text") or "")
            if text:
                parts.append(text)
    return "\n".join(parts)


def convert_session(
    session_path: Path,
    answer_path: Path,
    output_path: Path,
    *,
    mode: str,
    model: str,
) -> None:
    events: list[dict[str, Any]] = [{"type": "session", "mode": mode, "model": model}]
    tool_calls: dict[str, dict[str, Any]] = {}

    for raw_line in session_path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip():
            continue
        entry = json.loads(raw_line)
        if not isinstance(entry, Mapping) or entry.get("type") != "message":
            continue
        message = entry.get("message")
        if not isinstance(message, Mapping):
            continue

        role = str(message.get("role") or "")
        if role == "toolResult":
            call_id = str(message.get("toolCallId") or "")
            call = tool_calls.get(call_id) or {}
            tool_event: dict[str, Any] = {
                "type": "tool",
                "name": str(message.get("toolName") or call.get("name") or "unknown"),
                "output": _text_content(message.get("content")),
            }
            arguments = call.get("arguments")
            if isinstance(arguments, Mapping):
                # Preserve the tool target/range so evaluators can bind source
                # citations to the exact file lines the Agent actually read.
                tool_event["arguments"] = dict(arguments)
            details = message.get("details")
            if isinstance(details, Mapping):
                activity = details.get("tracecite_host_activity")
                if isinstance(activity, Mapping):
                    tool_event["activity"] = dict(activity)
                    duration = activity.get("duration_ms")
                    if isinstance(duration, (int, float)) and not isinstance(duration, bool) and duration >= 0:
                        tool_event["duration_ms"] = duration
                summary = details.get("tracecite_host_activity_summary")
                if isinstance(summary, Mapping):
                    tool_event["activity_summary"] = dict(summary)
            events.append(tool_event)
            continue

        if role != "assistant":
            continue

        content = message.get("content")
        if isinstance(content, list):
            for item in content:
                if not isinstance(item, Mapping) or str(item.get("type") or "") != "toolCall":
                    continue
                call_id = str(item.get("id") or "")
                if not call_id:
                    continue
                call: dict[str, Any] = {"name": str(item.get("name") or "unknown")}
                arguments = item.get("arguments")
                if isinstance(arguments, Mapping):
                    call["arguments"] = dict(arguments)
                tool_calls[call_id] = call

        usage = message.get("usage")
        if isinstance(usage, Mapping):
            events.append(
                {
                    "type": "model",
                    "usage": {
                        "input_tokens": usage.get("input"),
                        "output_tokens": usage.get("output"),
                        "reasoning_tokens": usage.get("reasoning"),
                        "cached_input_tokens": usage.get("cacheRead"),
                        "cache_read_input_tokens": usage.get("cacheRead"),
                        "cache_creation_input_tokens": usage.get("cacheWrite"),
                    },
                }
            )

    events.append(
        {
            "type": "final",
            "answer": answer_path.read_text(encoding="utf-8").strip(),
        }
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert a real Pi coding-agent session into TraceCite benchmark transcript JSONL."
    )
    parser.add_argument("session", type=Path)
    parser.add_argument("answer", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--mode", required=True)
    parser.add_argument("--model", required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    convert_session(
        args.session,
        args.answer,
        args.output,
        mode=args.mode,
        model=args.model,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
