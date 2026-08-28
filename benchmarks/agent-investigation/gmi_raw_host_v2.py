from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

import gmi_host as base
import openai_host as common


_ORIGINAL_TOOLS_FOR_MODE = common._tools_for_mode


class InspectFirstRuntime(base.BenchmarkToolRuntime):
    """Raw-evidence adapter that makes the first source inspection explicit.

    This does not add a model turn or an output budget. It gives the Agent one
    deterministic way to inspect a source before using targeted search, which
    avoids treating search keywords as the mechanism for reading the source.
    """

    def __init__(self, *, mode: str, input_root: Path, scratch: Path, context_id: str) -> None:
        super().__init__(mode=mode, input_root=input_root, scratch=scratch, context_id=context_id)
        self._inspected_files: set[str] = set()

    def _tracecite_inspect(self, args: Mapping[str, Any]) -> str:
        file_name = str(args.get("file") or "")
        if not file_name:
            raise ValueError("file must be non-empty")
        if file_name in self._inspected_files:
            return (
                "ALREADY INSPECTED: this source has already been returned with line-addressable "
                "Coverage. Use tracecite_search only for a new, specific hypothesis or citation."
            )
        self._inspected_files.add(file_name)
        return self._tracecite_search({"file": file_name, "query": ".*", "regex": True})

    def call(self, name: str, args: Mapping[str, Any]) -> str:
        if name == "tracecite_inspect" and self.mode in {"tracecite", "tracecite_context"}:
            return self._tracecite_inspect(args)
        return super().call(name, args)


def _tools_for_mode(mode: str, files: Sequence[Path]) -> list[dict[str, Any]]:
    if mode not in {"tracecite", "tracecite_context"}:
        return _ORIGINAL_TOOLS_FOR_MODE(mode, files)

    file_property = common._common_file_property(files)
    return [
        common._function_tool(
            "tracecite_inspect",
            (
                "Inspect one raw evidence source before doing keyword searches. Use this first for a "
                "source you have not inspected. It returns line-addressable TraceCite evidence plus "
                "Coverage with no benchmark character cap. If Coverage shows the relevant source is "
                "fully represented, reason from it instead of issuing synonym searches."
            ),
            {"file": file_property},
            ["file"],
        ),
        common._function_tool(
            "tracecite_search",
            (
                "Run a targeted TraceCite search only after inspection, when reasoning creates a new "
                "specific hypothesis or you need a precise citation. query is a literal substring unless "
                "regex=true; space-separated synonyms are not OR terms. Do not repeat broad searches for "
                "evidence already returned by tracecite_inspect."
            ),
            {
                "file": file_property,
                "query": {"type": "string"},
                "regex": {"type": "boolean"},
            },
            ["file", "query", "regex"],
        ),
    ]


# Keep the provider/protocol loop identical to gmi_host.py. Only the Agent-facing
# raw evidence tool surface changes for this experiment.
base.BenchmarkToolRuntime = InspectFirstRuntime
common._tools_for_mode = _tools_for_mode


if __name__ == "__main__":
    raise SystemExit(base.run())
