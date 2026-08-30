from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "benchmarks" / "agent-investigation" / "pi_session_to_transcript.py"
EXTENSION = ROOT / "benchmarks" / "agent-investigation" / "pi_tracecite_extension.ts"


def test_pi_extension_observes_native_and_tracecite_tools() -> None:
    text = EXTENSION.read_text(encoding="utf-8")
    assert 'pi.on("tool_call"' in text
    assert 'pi.on("tool_result"' in text
    assert 'tool === "grep"' in text
    assert 'tool === "read"' in text
    assert 'tool === "bash"' in text
    assert 'return "opaque_shell"' in text
    assert 'metadata: event.toolName === "bash" ? { opaque: true }' in text
    assert 'TRACECITE_PI_ACTIVITY' in text


def test_pi_session_adapter_preserves_host_tool_activity(tmp_path: Path) -> None:
    session = tmp_path / "session.jsonl"
    answer = tmp_path / "answer.md"
    output = tmp_path / "transcript.jsonl"
    session.write_text(
        json.dumps(
            {
                "type": "message",
                "message": {
                    "role": "toolResult",
                    "toolName": "grep",
                    "content": [{"type": "text", "text": "12\terror"}],
                    "details": {
                        "tracecite_host_activity": {"tool": "grep", "category": "native_search", "duration_ms": 7, "status": "ok"},
                        "tracecite_host_activity_summary": {"total_tool_calls": 1, "categories": {"native_search": 1}, "tools": {"grep": 1}, "observed_duration_ms": 7},
                    },
                },
            }
        ) + "\n",
        encoding="utf-8",
    )
    answer.write_text("Done.\n", encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), str(session), str(answer), str(output), "--mode", "pi-tracecite", "--model", "demo"],
        cwd=ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert completed.returncode == 0, completed.stderr
    events = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines() if line.strip()]
    tool = next(item for item in events if item.get("type") == "tool")
    assert tool["activity"]["category"] == "native_search"
    assert tool["duration_ms"] == 7
    assert tool["activity_summary"]["total_tool_calls"] == 1
