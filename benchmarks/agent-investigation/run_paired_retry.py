from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any

import run_host as isolated
from tracecite import benchmarking as legacy
from tracecite import root_cause_benchmarking as root_cause

RETRYABLE_FAILURES = frozenset({"provider_rate_limited", "provider_unavailable"})
DEFAULT_PASS_ENV = (
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "TRACECITE_BENCH_MAX_OUTPUT_TOKENS",
    "TRACECITE_BENCH_MAX_ROUNDS",
    "TRACECITE_BENCH_NO_GROWTH_ROUNDS",
)
DEFAULT_HOST_SCRIPT = Path("benchmarks/agent-investigation/gmi_canonical_host.py")


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _failure_reason(transcript: Path) -> str | None:
    if not transcript.is_file():
        return None
    reason: str | None = None
    for line in transcript.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict) or event.get("type") != "host_error":
            continue
        candidate = str(event.get("failure_reason") or event.get("error") or "").strip()
        if candidate:
            reason = candidate
    return reason


def _attempted_context(transcript: Path) -> tuple[int, int]:
    values: list[int] = []
    if not transcript.is_file():
        return 0, 0
    for line in transcript.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict) or event.get("type") != "request_context":
            continue
        value = event.get("serialized_chars")
        if isinstance(value, int) and value >= 0:
            values.append(value)
    return sum(values), max(values, default=0)


def _resolve_host_script(repo_root: Path, requested: Path | None) -> Path:
    candidate = DEFAULT_HOST_SCRIPT if requested is None else requested
    resolved = candidate if candidate.is_absolute() else repo_root / candidate
    resolved = resolved.resolve()
    if not resolved.is_file():
        raise ValueError(f"benchmark host script not found: {resolved}")
    return resolved


def _run_until_provider_available(
    *,
    case_dir: Path,
    prepared: Path,
    mode: str,
    model: str,
    arm_dir: Path,
    retry_delay_seconds: int,
    timeout_seconds: int,
    host_command: list[str],
) -> tuple[dict[str, Any], Path, str | None, int, list[str]]:
    attempts_root = arm_dir / "attempts"
    attempts_root.mkdir(parents=True, exist_ok=True)
    retry_reasons: list[str] = []
    attempt = 0

    while True:
        attempt += 1
        attempt_dir = attempts_root / f"attempt-{attempt:03d}"
        attempt_dir.mkdir(parents=True, exist_ok=True)
        transcript = attempt_dir / "transcript.jsonl"

        print(
            f"[{mode}] attempt {attempt}: running host",
            flush=True,
        )
        result = isolated.run_host(
            case_dir,
            prepared,
            mode=mode,
            model=model,
            seed=1,
            output=transcript,
            host_command=host_command,
            timeout_seconds=timeout_seconds,
            pass_env=DEFAULT_PASS_ENV,
        )
        _write_json(attempt_dir / "run-result.json", result)
        reason = _failure_reason(transcript)
        _write_json(
            attempt_dir / "attempt.json",
            {
                "attempt": attempt,
                "mode": mode,
                "status": result.get("status"),
                "failure_reason": reason,
                "retryable": reason in RETRYABLE_FAILURES,
            },
        )

        if result.get("status") in {"ok", "incomplete"}:
            print(f"[{mode}] attempt {attempt}: completed with {result.get('status')}", flush=True)
            return result, transcript, reason, attempt, retry_reasons

        if reason not in RETRYABLE_FAILURES:
            print(
                f"[{mode}] attempt {attempt}: non-retryable failure {reason or result.get('status')}",
                flush=True,
            )
            return result, transcript, reason, attempt, retry_reasons

        retry_reasons.append(reason)
        print(
            f"[{mode}] attempt {attempt}: {reason}; retrying after {retry_delay_seconds}s",
            flush=True,
        )
        time.sleep(retry_delay_seconds)


def _score(case_dir: Path, transcript: Path, scorer: str) -> dict[str, Any]:
    if scorer == "root":
        return root_cause.score_transcript(case_dir, transcript)
    return legacy.score_transcript(case_dir, transcript)


def _finalize_arm(
    *,
    case_id: str,
    case_dir: Path,
    scorer: str,
    mode: str,
    model: str,
    arm_dir: Path,
    result: dict[str, Any],
    transcript: Path,
    failure_reason: str | None,
    attempts: int,
    retry_reasons: list[str],
) -> dict[str, Any]:
    final_transcript = arm_dir / "transcript.jsonl"
    shutil.copy2(transcript, final_transcript)
    _write_json(arm_dir / "run-result.json", result)
    (arm_dir / "status.txt").write_text(str(result.get("status") or "host_error") + "\n")

    score: dict[str, Any] | None = None
    if result.get("status") in {"ok", "incomplete"}:
        score = _score(case_dir, final_transcript, scorer)
        _write_json(arm_dir / "score.json", score)

    quality = (score or {}).get("quality") or {}
    context = dict((score or {}).get("context_cost") or {})
    cumulative, peak = _attempted_context(final_transcript)
    if cumulative:
        context.setdefault("cumulative_attempted_context_chars", cumulative)
        context.setdefault("peak_attempted_context_chars", peak)

    if scorer == "root":
        primary_quality_name = "dimension_recall"
        primary_quality = quality.get("dimension_recall")
    else:
        primary_quality_name = "concept_recall"
        primary_quality = quality.get("concept_recall")

    outcome = {
        "schema_version": 1,
        "case_id": case_id,
        "mode": mode,
        "scorer": scorer,
        "model": model,
        "run_status": result.get("status"),
        "host_failure_reason": failure_reason,
        "passed": (score or {}).get("passed") if score else None,
        "primary_quality_name": primary_quality_name,
        "primary_quality": primary_quality,
        "quality": quality if score else None,
        "context_cost": context if score else None,
        "attempts": attempts,
        "provider_retries": len(retry_reasons),
        "provider_retry_reasons": retry_reasons,
        "run": result,
    }
    _write_json(arm_dir / "outcome.json", outcome)
    return outcome


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run one paired free_shell/TraceCite case, retrying transient provider failures every two minutes."
    )
    parser.add_argument("case_dir", type=Path)
    parser.add_argument("prepared", type=Path)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--scorer", choices=("legacy", "root"), required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--result-dir", type=Path, required=True)
    parser.add_argument("--retry-delay-seconds", type=int, default=120)
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument(
        "--host-script",
        type=Path,
        default=None,
        help=(
            "Host script relative to the repository root or an absolute path. "
            "Defaults to the canonical benchmark host."
        ),
    )
    args = parser.parse_args()

    if args.retry_delay_seconds < 1:
        parser.error("--retry-delay-seconds must be at least 1")

    repo_root = Path(__file__).resolve().parents[2]
    try:
        host_script = _resolve_host_script(repo_root, args.host_script)
    except ValueError as exc:
        parser.error(str(exc))
    host_command = [sys.executable, str(host_script)]
    args.result_dir.mkdir(parents=True, exist_ok=True)

    outcomes: list[dict[str, Any]] = []
    for mode in ("free_shell", "tracecite"):
        arm_dir = args.result_dir / mode
        arm_dir.mkdir(parents=True, exist_ok=True)
        result, transcript, reason, attempts, retry_reasons = _run_until_provider_available(
            case_dir=args.case_dir,
            prepared=args.prepared,
            mode=mode,
            model=args.model,
            arm_dir=arm_dir,
            retry_delay_seconds=args.retry_delay_seconds,
            timeout_seconds=args.timeout_seconds,
            host_command=host_command,
        )
        outcomes.append(
            _finalize_arm(
                case_id=args.case_id,
                case_dir=args.case_dir,
                scorer=args.scorer,
                mode=mode,
                model=args.model,
                arm_dir=arm_dir,
                result=result,
                transcript=transcript,
                failure_reason=reason,
                attempts=attempts,
                retry_reasons=retry_reasons,
            )
        )

    _write_json(args.result_dir / "pair.json", {"case_id": args.case_id, "outcomes": outcomes})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
