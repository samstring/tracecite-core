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
    "sed",
    "head",
    "tail",
    "find",
    "wc",
    "sort",
    "uniq",
    "ls",
)


def tools(files: Sequence[Path]) -> list[dict[str, Any]]:
    names = ", ".join(path.name for path in files)
    return [
        common._function_tool(
            "shell_exec",
            (
                "Run one read-only shell utility directly inside the isolated evidence directory. "
                "You freely choose the utility and arguments. No shell expansion, pipes, network tools, "
                "or arbitrary code execution are available. Evidence files: " + names
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
    return value


class Runtime(common.ToolRuntime):
    def _shell_exec(self, args: Mapping[str, Any]) -> str:
        program = str(args.get("program") or "")
        if program not in ALLOWED_PROGRAMS:
            raise ValueError(f"program is not allowed: {program}")
        raw_args = args.get("args")
        if not isinstance(raw_args, list) or len(raw_args) > 32:
            raise ValueError("args must be an array with at most 32 items")
        argv = [_validate_arg(str(value)) for value in raw_args]
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
