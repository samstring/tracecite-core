from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

import gmi_host as base
import openai_host as common


_ORIGINAL_TOOLS_FOR_MODE = common._tools_for_mode
_ORIGINAL_POST_CHAT = base._post_chat
_COVERAGE_RE = re.compile(
    r"@COV\s+evidence_available=(\d+)\s+evidence_returned=(\d+)\s+"
    r"evidence_truncated=(True|False)"
)


def _post_chat_with_transient_retry(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Retry provider overloads, not semantic/model failures or billing failures."""
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


class InspectFirstRuntime(base.BenchmarkToolRuntime):
    """Raw-evidence adapter that makes the first source inspection explicit.

    This does not add a model turn or an output budget. It gives the Agent one
    deterministic way to inspect a source before using targeted search, which
    avoids treating search keywords as the mechanism for reading the source.
    """

    def __init__(self, *, mode: str, input_root: Path, scratch: Path, context_id: str) -> None:
        super().__init__(mode=mode, input_root=input_root, scratch=scratch, context_id=context_id)
        self._inspected_files: set[str] = set()
        self._fully_inspected: dict[str, tuple[int, int]] = {}

    def _tracecite_inspect(self, args: Mapping[str, Any]) -> str:
        file_name = str(args.get("file") or "")
        if not file_name:
            raise ValueError("file must be non-empty")
        if file_name in self._inspected_files:
            return (
                "ALREADY INSPECTED: this source has already been returned with line-addressable "
                "Coverage. Reason from the existing evidence instead of inspecting it again."
            )
        output = super()._tracecite_search({"file": file_name, "query": ".*", "regex": True})
        self._inspected_files.add(file_name)
        match = _COVERAGE_RE.search(output)
        if match is not None:
            available = int(match.group(1))
            returned = int(match.group(2))
            truncated = match.group(3) == "True"
            if available == returned and not truncated:
                self._fully_inspected[file_name] = (available, returned)
        return output

    def _tracecite_search(self, args: Mapping[str, Any]) -> str:
        file_name = str(args.get("file") or "")
        complete = self._fully_inspected.get(file_name)
        if complete is not None:
            available, returned = complete
            return (
                "NO_NEW_EVIDENCE: this source was fully inspected already "
                f"({returned}/{available} evidence records returned; evidence_truncated=False). "
                "A keyword search cannot reveal evidence that was not already delivered. "
                "Use the existing #L references and reason from them; inspect another source only if one exists."
            )
        return super()._tracecite_search(args)

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
                "Inspect one raw evidence source before keyword search. Use this first. It returns "
                "line-addressable TraceCite evidence and Coverage with no benchmark character cap. "
                "When Coverage says evidence_available equals evidence_returned and "
                "evidence_truncated=False, the source is complete: reason from those lines and do not search it."
            ),
            {"file": file_property},
            ["file"],
        ),
        common._function_tool(
            "tracecite_search",
            (
                "Target a source only when its prior inspection was partial/truncated or when it has not "
                "been fully inspected. If inspection already returned the entire source, TraceCite will "
                "deterministically return NO_NEW_EVIDENCE instead of repeating evidence. query is literal "
                "unless regex=true; space-separated synonyms are not OR terms."
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
# raw evidence tool surface and transport retry policy change for this experiment.
base.BenchmarkToolRuntime = InspectFirstRuntime
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
