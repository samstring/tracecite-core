from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

import gmi_host as base
import openai_host as common


_ORIGINAL_TOOLS_FOR_MODE = common._tools_for_mode
_ORIGINAL_POST_CHAT = base._post_chat


def _post_chat_with_transient_retry(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Retry transient provider overloads only."""
    for attempt in range(3):
        try:
            return _ORIGINAL_POST_CHAT(payload)
        except RuntimeError as exc:
            message = str(exc)
            transient = any(f"HTTP {code}" in message for code in (429, 500, 502, 503, 504))
            if not transient or attempt >= 2:
                raise
            time.sleep(2 ** attempt)
    raise AssertionError("unreachable")


class ScaleRuntime(base.BenchmarkToolRuntime):
    """Large-evidence adapter using bounded survey before targeted search.

    Prepared benchmark inputs are checksum-pinned and immutable, so this adapter
    disables redundant per-search snapshots. It intentionally omits benchmark-
    specific max-output/max-evidence/max-line arguments: the normal TraceCite
    Agent projection defaults remain in force as product behavior.
    """

    def __init__(self, *, mode: str, input_root: Path, scratch: Path, context_id: str) -> None:
        super().__init__(mode=mode, input_root=input_root, scratch=scratch, context_id=context_id)
        self._surveyed_files: set[str] = set()

    def _run(self, command: Sequence[str], *, timeout: int = 300) -> str:
        completed = subprocess.run(
            list(command),
            cwd=self.scratch,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
        output = completed.stdout.strip()
        if completed.returncode != 0:
            output = (output + "\n" + completed.stderr.strip()).strip()
        return output or "NO OUTPUT"

    def _tracecite_survey(self, args: Mapping[str, Any]) -> str:
        file_name = str(args.get("file") or "")
        if not file_name:
            raise ValueError("file must be non-empty")
        path = common._safe_input(self.input_root, file_name)
        if file_name in self._surveyed_files:
            return (
                "ALREADY_SURVEYED: this source already has a bounded structural survey in context. "
                "Use targeted search for a concrete hypothesis instead of repeating survey."
            )
        self._surveyed_files.add(file_name)
        return self._run(
            [
                sys.executable,
                "-m",
                "tracecite.integrations.cli",
                "survey",
                str(path),
                "--no-snapshot",
                "--brief",
                "--lightweight",
                "--max-templates",
                "20",
                "--samples-per-template",
                "1",
            ],
            timeout=600,
        )

    def _tracecite_search_scale(self, args: Mapping[str, Any]) -> str:
        file_name = str(args.get("file") or "")
        path = common._safe_input(self.input_root, file_name)
        query = str(args.get("query") or "")
        if not query:
            raise ValueError("query must be non-empty")
        ledger = self.scratch / "ledger"
        ledger.mkdir(parents=True, exist_ok=True)
        command = [
            sys.executable,
            "-m",
            "tracecite.integrations.stateful_cli",
            "search",
            str(path),
            query,
            "--no-snapshot",
            "--compact",
            "--ledger-dir",
            str(ledger),
            "--agent-profile",
            "frame",
            "--lightweight",
        ]
        if bool(args.get("regex")):
            command.append("--regex")
        if self.mode == "tracecite_context":
            if not self.context_id:
                raise RuntimeError("tracecite_context requires context_id")
            command.extend(["--context-id", self.context_id])
        return self._run(command, timeout=600)

    def call(self, name: str, args: Mapping[str, Any]) -> str:
        if self.mode in {"tracecite", "tracecite_context"}:
            if name == "tracecite_survey":
                return self._tracecite_survey(args)
            if name == "tracecite_search":
                return self._tracecite_search_scale(args)
        return super().call(name, args)


def _tools_for_mode(mode: str, files: Sequence[Path]) -> list[dict[str, Any]]:
    if mode not in {"tracecite", "tracecite_context"}:
        return _ORIGINAL_TOOLS_FOR_MODE(mode, files)
    file_property = common._common_file_property(files)
    return [
        common._function_tool(
            "tracecite_survey",
            (
                "Bounded streaming survey of a large immutable evidence source. Use this first when the "
                "source is large or unfamiliar. It returns structural/time/template statistics without "
                "returning the whole file. Survey each source at most once."
            ),
            {"file": file_property},
            ["file"],
        ),
        common._function_tool(
            "tracecite_search",
            (
                "Targeted TraceCite search after survey or when you have a concrete hypothesis, identifier, "
                "error, component, time clue, or fault signature. Returns bounded line-addressable evidence, "
                "Coverage, recovery metadata and source provenance. Do not issue synonym searches when prior "
                "searches produced no new evidence."
            ),
            {
                "file": file_property,
                "query": {"type": "string"},
                "regex": {"type": "boolean"},
            },
            ["file", "query", "regex"],
        ),
    ]


base.BenchmarkToolRuntime = ScaleRuntime
base._post_chat = _post_chat_with_transient_retry
common._tools_for_mode = _tools_for_mode


if __name__ == "__main__":
    try:
        raise SystemExit(base.run())
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
