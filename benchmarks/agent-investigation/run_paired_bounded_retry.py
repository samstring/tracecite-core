from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any

import run_host as isolated
import run_paired_retry as legacy


DEFAULT_HOST_SCRIPT = Path("benchmarks/agent-investigation/gmi_investigation_host.py")


def _write_json(path: Path, value: Any) -> None:
    legacy._write_json(path, value)


def _run_until_provider_available(
    *,
    case_dir: Path,
    prepared: Path,
    mode: str,
    model: str,
    arm_dir: Path,
    retry_delay_seconds: int,
    max_attempts: int,
    timeout_seconds: int,
    host_command: list[str],
) -> tuple[dict[str, Any], Path, str | None, int, list[str]]:
    """Retry an entire arm only a bounded number of times.

    Model-request retries inside the host are separately bounded. This outer
    retry exists only to cross a provider-wide transient window without turning
    one 429 into an unbounded workflow loop.
    """

    attempts_root = arm_dir / "attempts"
    attempts_root.mkdir(parents=True, exist_ok=True)
    retry_reasons: list[str] = []

    for attempt in range(1, max_attempts + 1):
        attempt_dir = attempts_root / f"attempt-{attempt:03d}"
        attempt_dir.mkdir(parents=True, exist_ok=True)
        transcript = attempt_dir / "transcript.jsonl"

        print(f"[{mode}] attempt {attempt}/{max_attempts}: running host", flush=True)
        result = isolated.run_host(
            case_dir,
            prepared,
            mode=mode,
            model=model,
            seed=1,
            output=transcript,
            host_command=host_command,
            timeout_seconds=timeout_seconds,
            pass_env=legacy.DEFAULT_PASS_ENV
            + (
                "TRACECITE_BENCH_PROVIDER_MAX_ATTEMPTS",
                "TRACECITE_BENCH_PROVIDER_BACKOFF_SECONDS",
            ),
        )
        _write_json(attempt_dir / "run-result.json", result)
        reason = legacy._failure_reason(transcript)
        _write_json(
            attempt_dir / "attempt.json",
            {
                "attempt": attempt,
                "max_attempts": max_attempts,
                "mode": mode,
                "status": result.get("status"),
                "failure_reason": reason,
                "retryable": reason in legacy.RETRYABLE_FAILURES,
            },
        )

        if result.get("status") in {"ok", "incomplete"}:
            print(f"[{mode}] attempt {attempt}: completed with {result.get('status')}", flush=True)
            return result, transcript, reason, attempt, retry_reasons

        if reason not in legacy.RETRYABLE_FAILURES:
            print(
                f"[{mode}] attempt {attempt}: non-retryable failure {reason or result.get('status')}",
                flush=True,
            )
            return result, transcript, reason, attempt, retry_reasons

        retry_reasons.append(reason)
        if attempt >= max_attempts:
            print(
                f"[{mode}] attempt {attempt}: {reason}; retry budget exhausted",
                flush=True,
            )
            return result, transcript, reason, attempt, retry_reasons

        print(
            f"[{mode}] attempt {attempt}: {reason}; retrying whole arm after {retry_delay_seconds}s",
            flush=True,
        )
        time.sleep(retry_delay_seconds)

    raise AssertionError("unreachable")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run one paired TraceCite/free-shell case with TraceCite first and bounded provider retries."
        )
    )
    parser.add_argument("case_dir", type=Path)
    parser.add_argument("prepared", type=Path)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--scorer", choices=("legacy", "root"), required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--result-dir", type=Path, required=True)
    parser.add_argument("--retry-delay-seconds", type=int, default=120)
    parser.add_argument("--max-provider-attempts", type=int, default=2)
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument(
        "--host-script",
        type=Path,
        default=None,
        help=(
            "Host script relative to repository root or absolute. "
            "Defaults to the full TraceCite investigation host."
        ),
    )
    args = parser.parse_args()

    if args.retry_delay_seconds < 1:
        parser.error("--retry-delay-seconds must be at least 1")
    if args.max_provider_attempts < 1:
        parser.error("--max-provider-attempts must be at least 1")

    repo_root = Path(__file__).resolve().parents[2]
    requested = args.host_script or DEFAULT_HOST_SCRIPT
    try:
        host_script = legacy._resolve_host_script(repo_root, requested)
    except ValueError as exc:
        parser.error(str(exc))
    host_command = [sys.executable, str(host_script)]
    args.result_dir.mkdir(parents=True, exist_ok=True)

    outcomes: list[dict[str, Any]] = []
    # Candidate-first is intentional: the free-shell baseline must not consume
    # the shared provider rate window before the TraceCite arm begins.
    for mode in ("tracecite", "free_shell"):
        arm_dir = args.result_dir / mode
        arm_dir.mkdir(parents=True, exist_ok=True)
        result, transcript, reason, attempts, retry_reasons = _run_until_provider_available(
            case_dir=args.case_dir,
            prepared=args.prepared,
            mode=mode,
            model=args.model,
            arm_dir=arm_dir,
            retry_delay_seconds=args.retry_delay_seconds,
            max_attempts=args.max_provider_attempts,
            timeout_seconds=args.timeout_seconds,
            host_command=host_command,
        )
        outcomes.append(
            legacy._finalize_arm(
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

    _write_json(
        args.result_dir / "pair.json",
        {
            "case_id": args.case_id,
            "execution_order": ["tracecite", "free_shell"],
            "max_provider_attempts_per_arm": args.max_provider_attempts,
            "outcomes": outcomes,
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
