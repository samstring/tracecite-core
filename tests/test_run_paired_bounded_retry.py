from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "benchmarks" / "agent-investigation"
sys.path.insert(0, str(BENCH))

import run_paired_bounded_retry as runner  # noqa: E402


def _fake_result(status: str) -> dict[str, object]:
    return {"status": status, "returncode": 1 if status == "host_error" else 0}


def test_outer_provider_retry_stops_after_success(monkeypatch, tmp_path: Path) -> None:
    calls: list[str] = []
    sleeps: list[int] = []

    def fake_run_host(*args, **kwargs):
        calls.append(str(kwargs.get("mode")))
        transcript = Path(kwargs["output"])
        if len(calls) == 1:
            transcript.write_text(
                json.dumps(
                    {
                        "type": "host_error",
                        "failure_reason": "provider_rate_limited",
                        "error": "RuntimeError",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            return _fake_result("host_error")
        transcript.write_text("", encoding="utf-8")
        return _fake_result("ok")

    monkeypatch.setattr(runner.isolated, "run_host", fake_run_host)
    monkeypatch.setattr(runner.time, "sleep", lambda seconds: sleeps.append(seconds))

    result, _transcript, reason, attempts, retry_reasons = runner._run_until_provider_available(
        case_dir=tmp_path,
        prepared=tmp_path / "prepared.json",
        mode="tracecite",
        model="model",
        arm_dir=tmp_path / "arm",
        retry_delay_seconds=120,
        max_attempts=2,
        timeout_seconds=10,
        host_command=["python", "host.py"],
    )

    assert result["status"] == "ok"
    assert reason is None
    assert attempts == 2
    assert retry_reasons == ["provider_rate_limited"]
    assert calls == ["tracecite", "tracecite"]
    assert sleeps == [120]


def test_outer_provider_retry_never_loops_forever(monkeypatch, tmp_path: Path) -> None:
    calls = 0
    sleeps: list[int] = []

    def fake_run_host(*args, **kwargs):
        nonlocal calls
        calls += 1
        transcript = Path(kwargs["output"])
        transcript.write_text(
            json.dumps(
                {
                    "type": "host_error",
                    "failure_reason": "provider_rate_limited",
                    "error": "RuntimeError",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        return _fake_result("host_error")

    monkeypatch.setattr(runner.isolated, "run_host", fake_run_host)
    monkeypatch.setattr(runner.time, "sleep", lambda seconds: sleeps.append(seconds))

    result, _transcript, reason, attempts, retry_reasons = runner._run_until_provider_available(
        case_dir=tmp_path,
        prepared=tmp_path / "prepared.json",
        mode="tracecite",
        model="model",
        arm_dir=tmp_path / "arm",
        retry_delay_seconds=120,
        max_attempts=2,
        timeout_seconds=10,
        host_command=["python", "host.py"],
    )

    assert result["status"] == "host_error"
    assert reason == "provider_rate_limited"
    assert attempts == 2
    assert retry_reasons == ["provider_rate_limited", "provider_rate_limited"]
    assert calls == 2
    assert sleeps == [120]
