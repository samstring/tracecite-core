from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _module():
    path = Path(__file__).resolve().parents[1] / "benchmarks" / "agent-investigation" / "run_host.py"
    spec = importlib.util.spec_from_file_location("tracecite_bench_run_host", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_preserved_failure_reason_keeps_provider_reason_over_generic_wrapper(tmp_path: Path) -> None:
    module = _module()
    transcript = tmp_path / "transcript.jsonl"
    events = [
        {"type": "session"},
        {"type": "host_error", "failure_reason": "provider_insufficient_balance", "error": "HTTP 402"},
        {"type": "host_error", "failure_reason": "host_error", "returncode": 1},
    ]
    transcript.write_text("".join(json.dumps(item) + "\n" for item in events), encoding="utf-8")

    assert module._preserved_failure_reason(transcript) == "provider_insufficient_balance"


def test_preserved_failure_reason_keeps_context_overflow(tmp_path: Path) -> None:
    module = _module()
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(
        json.dumps({"type": "host_error", "failure_reason": "context_window_exceeded"}) + "\n",
        encoding="utf-8",
    )

    assert module._preserved_failure_reason(transcript) == "context_window_exceeded"


def test_preserved_failure_reason_defaults_to_generic_host_error(tmp_path: Path) -> None:
    module = _module()
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(json.dumps({"type": "host_error", "returncode": 3}) + "\n", encoding="utf-8")

    assert module._preserved_failure_reason(transcript) == "host_error"
