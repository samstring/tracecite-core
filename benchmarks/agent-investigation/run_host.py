from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any, Mapping, Sequence

from tracecite.benchmarking import validate_case


MODES = ("shell_rg", "tracecite", "tracecite_context")
_BASE_ENV = (
    "PATH",
    "HOME",
    "USER",
    "LOGNAME",
    "TMPDIR",
    "TEMP",
    "TMP",
    "SYSTEMROOT",
    "COMSPEC",
    "PATHEXT",
    "VIRTUAL_ENV",
    "PYTHONPATH",
    "LANG",
    "LC_ALL",
)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _copy_inputs(prepared: Mapping[str, Any], destination: Path) -> list[dict[str, Any]]:
    raw_inputs = prepared.get("inputs")
    if not isinstance(raw_inputs, list) or not raw_inputs:
        raise ValueError("prepared manifest has no inputs")
    destination.mkdir(parents=True, exist_ok=True)
    copied: list[dict[str, Any]] = []
    names: set[str] = set()
    for index, item in enumerate(raw_inputs):
        if not isinstance(item, Mapping):
            raise ValueError(f"prepared inputs[{index}] must be an object")
        source = Path(str(item.get("path") or ""))
        expected = str(item.get("sha256") or "")
        if not source.is_file():
            raise FileNotFoundError(source)
        if len(expected) != 64 or _sha256(source) != expected:
            raise ValueError(f"prepared input digest mismatch: {item.get('id') or source.name}")
        name = source.name
        if not name or name in names:
            raise ValueError(f"prepared input filename collision: {name!r}")
        names.add(name)
        target = destination / name
        shutil.copy2(source, target)
        if _sha256(target) != expected:
            raise ValueError(f"copied input digest mismatch: {name}")
        copied.append(
            {
                "id": item.get("id"),
                "filename": name,
                "sha256": expected,
                "bytes": target.stat().st_size,
            }
        )
    return copied


def _safe_environment(pass_env: Sequence[str]) -> dict[str, str]:
    env = {key: os.environ[key] for key in _BASE_ENV if key in os.environ}
    for name in pass_env:
        if not name or "=" in name:
            raise ValueError("--pass-env expects an environment variable name")
        if name in os.environ:
            env[name] = os.environ[name]
    return env


def _iter_events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise ValueError(f"transcript line {line_number} must be a JSON object")
        events.append(payload)
    return events


def _append_event(path: Path, event: Mapping[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(event), ensure_ascii=False, sort_keys=True) + "\n")


def run_host(
    case_dir: Path,
    prepared_manifest: Path,
    *,
    mode: str,
    model: str,
    seed: int,
    output: Path,
    host_command: Sequence[str],
    timeout_seconds: int = 900,
    pass_env: Sequence[str] = (),
    run_id: str | None = None,
) -> dict[str, Any]:
    if mode not in MODES:
        raise ValueError(f"mode must be one of: {', '.join(MODES)}")
    if not model.strip():
        raise ValueError("model must be non-empty")
    if timeout_seconds < 1:
        raise ValueError("timeout_seconds must be at least 1")
    command = list(host_command)
    if not command:
        raise ValueError("host command is required after --")

    validation = validate_case(case_dir)
    case = _read_json(case_dir / "case.json")
    prepared = _read_json(prepared_manifest)
    case_id = str(validation["case_id"])
    if str(prepared.get("case_id") or "") != case_id:
        raise ValueError("prepared manifest case_id does not match case")

    question_name = str(case.get("question_file", "question.md"))
    question = case_dir / question_name
    selected_run_id = run_id or uuid.uuid4().hex
    context_id = uuid.uuid4().hex if mode == "tracecite_context" else None
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=f"tracecite-bench-{case_id}-{mode}-") as temporary:
        workspace = Path(temporary)
        question_target = workspace / "QUESTION.md"
        shutil.copy2(question, question_target)
        copied_inputs = _copy_inputs(prepared, workspace / "inputs")
        scratch = workspace / "scratch"
        scratch.mkdir()
        transcript = scratch / "transcript.jsonl"
        session: dict[str, Any] = {
            "type": "session",
            "run_id": selected_run_id,
            "case_id": case_id,
            "mode": mode,
            "model": model,
            "seed": seed,
        }
        if context_id is not None:
            session["context_id"] = context_id
        transcript.write_text(
            json.dumps(session, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        env = _safe_environment(pass_env)
        env.update(
            {
                "TRACECITE_BENCH_WORKSPACE": str(workspace),
                "TRACECITE_BENCH_QUESTION": str(question_target),
                "TRACECITE_BENCH_INPUTS": str(workspace / "inputs"),
                "TRACECITE_BENCH_SCRATCH": str(scratch),
                "TRACECITE_BENCH_TRANSCRIPT": str(transcript),
                "TRACECITE_BENCH_MODE": mode,
                "TRACECITE_BENCH_MODEL": model,
                "TRACECITE_BENCH_SEED": str(seed),
                "TRACECITE_BENCH_RUN_ID": selected_run_id,
                "TRACECITE_BENCH_CONTEXT_ID": context_id or "",
            }
        )

        returncode: int | None
        timed_out = False
        stdout = ""
        stderr = ""
        try:
            completed = subprocess.run(
                command,
                cwd=workspace,
                env=env,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout_seconds,
            )
            returncode = completed.returncode
            stdout = completed.stdout
            stderr = completed.stderr
            if returncode != 0:
                _append_event(
                    transcript,
                    {
                        "type": "host_error",
                        "returncode": returncode,
                        "stdout_chars": len(stdout),
                        "stderr_chars": len(stderr),
                    },
                )
        except subprocess.TimeoutExpired as exc:
            returncode = None
            timed_out = True
            stdout = exc.stdout if isinstance(exc.stdout, str) else ""
            stderr = exc.stderr if isinstance(exc.stderr, str) else ""
            _append_event(
                transcript,
                {
                    "type": "host_error",
                    "error": "timeout",
                    "timeout_seconds": timeout_seconds,
                    "stdout_chars": len(stdout),
                    "stderr_chars": len(stderr),
                },
            )

        events = _iter_events(transcript)
        if not events or events[0] != session:
            raise ValueError("host must append to the runner-created transcript, not replace its session")
        if sum(1 for event in events if event.get("type") == "session") != 1:
            raise ValueError("transcript must contain exactly one session event")

        shutil.copy2(transcript, output)
        final_events = [event for event in events if event.get("type") == "final"]
        model_events = [event for event in events if event.get("type") == "model"]
        tool_events = [event for event in events if event.get("type") == "tool"]
        status = (
            "host_error"
            if timed_out or returncode not in {0}
            else ("ok" if final_events else "incomplete")
        )
        return {
            "schema_version": 1,
            "status": status,
            "run_id": selected_run_id,
            "case_id": case_id,
            "mode": mode,
            "model": model,
            "seed": seed,
            "context_id": context_id,
            "transcript": str(output),
            "host_returncode": returncode,
            "timed_out": timed_out,
            "events": {
                "model": len(model_events),
                "tool": len(tool_events),
                "final": len(final_events),
            },
            "inputs": copied_inputs,
        }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one isolated external Agent Host attempt for the TraceCite benchmark"
    )
    parser.add_argument("case_dir", type=Path)
    parser.add_argument("prepared_manifest", type=Path)
    parser.add_argument("--mode", required=True, choices=MODES)
    parser.add_argument("--model", required=True)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--pass-env", action="append", default=[])
    parser.add_argument("--run-id")
    return parser


def _split_argv(argv: Sequence[str]) -> tuple[list[str], list[str]]:
    values = list(argv)
    try:
        separator = values.index("--")
    except ValueError as exc:
        raise ValueError("host command must follow a -- separator") from exc
    runner_argv = values[:separator]
    host_argv = values[separator + 1 :]
    if not host_argv:
        raise ValueError("host command is required after --")
    return runner_argv, host_argv


def main(argv: Sequence[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    try:
        runner_argv, host_argv = _split_argv(raw_argv)
        args = _build_parser().parse_args(runner_argv)
        result = run_host(
            args.case_dir,
            args.prepared_manifest,
            mode=args.mode,
            model=args.model,
            seed=args.seed,
            output=args.output,
            host_command=host_argv,
            timeout_seconds=args.timeout_seconds,
            pass_env=args.pass_env,
            run_id=args.run_id,
        )
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["status"] in {"ok", "incomplete"} else 1


if __name__ == "__main__":
    sys.exit(main())
