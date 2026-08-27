from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Mapping, Sequence

import openai_host as common


ALLOWED_PROGRAMS = (
    "rg",
    "jq",
    "cat",
    "head",
    "tail",
    "find",
    "wc",
    "sort",
    "uniq",
    "ls",
)

_FORBIDDEN_EXACT_ARGS = {
    "rg": frozenset(),
    "jq": frozenset(),
    "cat": frozenset(),
    "head": frozenset(),
    "tail": frozenset({"-f", "-F", "--follow"}),
    "find": frozenset(
        {
            "-exec",
            "-execdir",
            "-ok",
            "-okdir",
            "-delete",
            "-fls",
            "-fprint",
            "-fprint0",
            "-fprintf",
            "-files0-from",
        }
    ),
    "wc": frozenset(),
    "sort": frozenset({"-o", "--output", "--compress-program"}),
    "uniq": frozenset(),
    "ls": frozenset(),
}

_FORBIDDEN_PREFIX_ARGS = {
    "rg": ("--pre",),
    "jq": ("-L", "--library-path"),
    "cat": (),
    "head": (),
    "tail": ("--follow=",),
    "find": (
        "-exec",
        "-execdir",
        "-ok",
        "-okdir",
        "-delete",
        "-fls",
        "-fprint",
        "-fprint0",
        "-fprintf",
        "-files0-from",
    ),
    "wc": (),
    "sort": ("-o", "--output=", "--compress-program="),
    "uniq": (),
    "ls": (),
}


def tools(files: Sequence[Path]) -> list[dict[str, Any]]:
    names = ", ".join(path.name for path in files)
    return [
        common._function_tool(
            "shell_exec",
            (
                "Run one read-only local analysis utility directly inside the isolated evidence directory. "
                "You freely choose the utility and arguments. No shell expansion, pipes, network tools, "
                "write-capable flags, subprocess-spawning flags, or arbitrary code execution are available. "
                "Every args item must be a string. Evidence files: " + names
            ),
            {
                "program": {"type": "string", "enum": list(ALLOWED_PROGRAMS)},
                "args": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 32,
                },
            },
            ["program", "args"],
        )
    ]


def _validate_arg(value: str) -> str:
    if "\x00" in value or len(value) > 2000:
        raise ValueError("invalid shell argument")
    candidate = Path(value)
    if candidate.is_absolute():
        raise ValueError("absolute paths are not allowed")
    if any(part == ".." for part in candidate.parts):
        raise ValueError("parent path traversal is not allowed")
    if "=" in value:
        embedded = value.split("=", 1)[1]
        embedded_path = Path(embedded)
        if embedded_path.is_absolute() or any(part == ".." for part in embedded_path.parts):
            raise ValueError("embedded paths must stay inside the evidence workspace")
    return value


def _validate_program_args(program: str, argv: Sequence[str]) -> None:
    exact = _FORBIDDEN_EXACT_ARGS.get(program, frozenset())
    prefixes = _FORBIDDEN_PREFIX_ARGS.get(program, ())
    for arg in argv:
        if arg in exact or any(arg.startswith(prefix) for prefix in prefixes):
            raise ValueError(f"argument is not allowed for {program}: {arg}")


class Runtime(common.ToolRuntime):
    def _shell_exec(self, args: Mapping[str, Any]) -> str:
        program = args.get("program")
        if not isinstance(program, str) or program not in ALLOWED_PROGRAMS:
            raise ValueError(f"program is not allowed: {program}")
        raw_args = args.get("args")
        if not isinstance(raw_args, list) or len(raw_args) > 32:
            raise ValueError("args must be an array with at most 32 items")
        if not all(isinstance(value, str) for value in raw_args):
            raise ValueError("every shell argument must be a string")
        argv = [_validate_arg(value) for value in raw_args]
        _validate_program_args(program, argv)
        env = {
            "PATH": os.environ.get("PATH", ""),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
        }
        completed = subprocess.run(
            [program, *argv],
            cwd=self.input_root,
            env=env,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )
        output = completed.stdout.strip()
        if completed.stderr.strip():
            output = (output + "\n" + completed.stderr.strip()).strip()
        if completed.returncode != 0:
            output = (output + f"\n[exit={completed.returncode}]").strip()
        return common._truncate(output or "NO OUTPUT")

    def call(self, name: str, args: Mapping[str, Any]) -> str:
        if self.mode == "free_shell" and name == "shell_exec":
            return self._shell_exec(args)
        return super().call(name, args)
