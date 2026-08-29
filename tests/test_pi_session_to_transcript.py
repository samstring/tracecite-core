from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "benchmarks" / "agent-investigation" / "pi_session_to_transcript.py"


def _jsonl(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_pi_session_adapter_preserves_tool_output_usage_and_final_answer(tmp_path: Path) -> None:
    session = tmp_path / "session.jsonl"
    answer = tmp_path / "answer.md"
    output = tmp_path / "transcript.jsonl"

    session.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "message",
                        "message": {
                            "role": "assistant",
                            "content": [{"type": "text", "text": "I will inspect the log."}],
                            "usage": {
                                "input": 120,
                                "output": 30,
                                "reasoning": 5,
                                "cacheRead": 20,
                                "cacheWrite": 4,
                            },
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "message",
                        "message": {
                            "role": "toolResult",
                            "toolName": "grep",
                            "content": [
                                {"type": "text", "text": "42\tERROR checksum failed"},
                                {"type": "text", "text": "43\trequest=7"},
                            ],
                        },
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    answer.write_text("Failure is at build-log.txt:L42.\n", encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(session),
            str(answer),
            str(output),
            "--mode",
            "pi-baseline",
            "--model",
            "MiniMaxAI/MiniMax-M3",
        ],
        cwd=ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert completed.returncode == 0, completed.stderr

    events = _jsonl(output)
    assert events[0] == {
        "type": "session",
        "mode": "pi-baseline",
        "model": "MiniMaxAI/MiniMax-M3",
    }
    model = next(item for item in events if item["type"] == "model")
    assert model["usage"] == {
        "input_tokens": 120,
        "output_tokens": 30,
        "reasoning_tokens": 5,
        "cached_input_tokens": 20,
        "cache_read_input_tokens": 20,
        "cache_creation_input_tokens": 4,
    }
    tool = next(item for item in events if item["type"] == "tool")
    assert tool["name"] == "grep"
    assert tool["output"] == "42\tERROR checksum failed\n43\trequest=7"
    assert events[-1] == {
        "type": "final",
        "answer": "Failure is at build-log.txt:L42.",
    }
