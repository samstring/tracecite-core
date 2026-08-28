from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from collections import deque
from pathlib import Path
from typing import Any, Mapping, Sequence

import gmi_host as base
import openai_host as common


_ORIGINAL_TOOLS_FOR_MODE = common._tools_for_mode
_ORIGINAL_POST_CHAT = base._post_chat

_SIGNAL_PATTERNS: tuple[tuple[int, re.Pattern[str]], ...] = (
    (
        4,
        re.compile(
            r"panic|fatal|crash(?:ed)?|corrupt(?:ed|ion)?|exception|checksum\s+(?:error|mismatch)",
            re.IGNORECASE,
        ),
    ),
    (
        3,
        re.compile(
            r"\berror\b|\bfail(?:ed|ure)?\b|mismatch|timeout|timed\s+out|"
            r"connection\s+reset|broken\s+pipe|refused",
            re.IGNORECASE,
        ),
    ),
    (
        2,
        re.compile(r"unavailable|denied|abort(?:ed)?|\binvalid\b", re.IGNORECASE),
    ),
)
_LINE_REFERENCE_RE = re.compile(r"^\s*(?:#?L(?:INE)?\s*)?\d+\s*$", re.IGNORECASE)
_IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_HEX_RE = re.compile(r"\b[0-9a-f]{8,}\b", re.IGNORECASE)
_NUMBER_RE = re.compile(r"(?<![A-Za-z])[-+]?\d+(?![A-Za-z])")
_SPACE_RE = re.compile(r"\s+")

_CONTEXT_RADIUS = 4
_MAX_SIGNAL_SIGNATURES = 256
_MAX_SIGNAL_CLUSTERS = 12
_MAX_INSPECT_CHARS = 24_000
_MAX_RENDERED_LINE_CHARS = 1_600
_INDEX_STRIDE = 1_024
_MAX_GET_RADIUS = 8


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


def _signal_severity(text: str) -> int:
    for severity, pattern in _SIGNAL_PATTERNS:
        if pattern.search(text):
            return severity
    return 0


def _signal_signature(text: str) -> str:
    value = text.casefold()
    value = _IP_RE.sub("<ip>", value)
    value = _HEX_RE.sub("<hex>", value)
    value = _NUMBER_RE.sub("<num>", value)
    value = _SPACE_RE.sub(" ", value).strip()
    return value[:600]


def _render_line(line_number: int, text: str) -> str:
    clean = text.rstrip("\r\n")
    if len(clean) > _MAX_RENDERED_LINE_CHARS:
        clean = clean[: _MAX_RENDERED_LINE_CHARS - 1] + "…"
    return f"#L{line_number}\t{clean}"


def _survey_overview(raw_output: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw_output)
    except (TypeError, ValueError):
        return {"status": "unparsed", "preview": raw_output[:2_000]}
    if not isinstance(payload, Mapping):
        return {"status": "unparsed"}
    coverage = dict(payload.get("coverage") or {})
    data = dict(payload.get("data") or {})
    templates: list[dict[str, Any]] = []
    for item in list(data.get("top_templates") or [])[:8]:
        if not isinstance(item, Mapping):
            continue
        samples = []
        for sample in list(item.get("samples") or [])[:1]:
            if isinstance(sample, Mapping):
                samples.append(
                    {
                        "start_line": sample.get("start_line"),
                        "end_line": sample.get("end_line"),
                    }
                )
        templates.append(
            {
                "count": item.get("count"),
                "approximate": item.get("approximate", False),
                "template": item.get("template"),
                "samples": samples,
            }
        )
    return {
        "status": payload.get("status"),
        "segmenter": data.get("segmenter"),
        "lines_scanned": coverage.get("lines_scanned"),
        "records_scanned": coverage.get("records_scanned"),
        "levels": data.get("levels", []),
        "templates_retained": coverage.get("templates_retained"),
        "template_evictions": coverage.get("template_evictions"),
        "top_templates": templates,
    }


class ScaleRuntime(base.BenchmarkToolRuntime):
    """Large-evidence adapter using bounded inspect before targeted retrieval.

    ``inspect`` performs one streaming pass that combines TraceCite's structural
    survey with generic incident-signal windows. It deliberately does not know
    benchmark labels, task IDs, HDFS operation names, or expected root causes.
    The output size is bounded while scan cost remains linear in source size.

    ``get`` recovers a small line window around an already-known line reference.
    ``search`` remains available for genuinely new semantic hypotheses rather
    than being abused as a line reader.
    """

    def __init__(self, *, mode: str, input_root: Path, scratch: Path, context_id: str) -> None:
        super().__init__(mode=mode, input_root=input_root, scratch=scratch, context_id=context_id)
        self._inspected_files: set[str] = set()
        self._searched_queries: dict[str, set[str]] = {}
        self._line_indexes: dict[str, list[tuple[int, int]]] = {}
        self._line_counts: dict[str, int] = {}

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

    def _survey(self, path: Path) -> str:
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

    def _scan_incident_signals(self, file_name: str, path: Path) -> dict[str, Any]:
        before: deque[tuple[int, str]] = deque(maxlen=_CONTEXT_RADIUS)
        clusters: dict[str, dict[str, Any]] = {}
        active: list[dict[str, Any]] = []
        line_index: list[tuple[int, int]] = []
        signal_lines = 0
        omitted_signatures = 0
        total_lines = 0
        byte_offset = 0

        with path.open("rb") as handle:
            for raw in handle:
                total_lines += 1
                line_number = total_lines
                if (line_number - 1) % _INDEX_STRIDE == 0:
                    line_index.append((line_number, byte_offset))
                text = raw.decode("utf-8", errors="replace").rstrip("\r\n")

                next_active: list[dict[str, Any]] = []
                for cluster in active:
                    if line_number > cluster["line"] and cluster["remaining_after"] > 0:
                        cluster["rows"].append((line_number, text))
                        cluster["remaining_after"] -= 1
                    if cluster["remaining_after"] > 0:
                        next_active.append(cluster)
                active = next_active

                severity = _signal_severity(text)
                if severity:
                    signal_lines += 1
                    signature = _signal_signature(text)
                    existing = clusters.get(signature)
                    if existing is not None:
                        existing["count"] += 1
                        existing["severity"] = max(existing["severity"], severity)
                    elif len(clusters) < _MAX_SIGNAL_SIGNATURES:
                        cluster = {
                            "signature": signature,
                            "severity": severity,
                            "count": 1,
                            "line": line_number,
                            "rows": [*before, (line_number, text)],
                            "remaining_after": _CONTEXT_RADIUS,
                        }
                        clusters[signature] = cluster
                        active.append(cluster)
                    else:
                        omitted_signatures += 1

                before.append((line_number, text))
                byte_offset += len(raw)

        self._line_indexes[file_name] = line_index
        self._line_counts[file_name] = total_lines
        selected = sorted(
            clusters.values(),
            key=lambda item: (-int(item["severity"]), int(item["count"]), int(item["line"])),
        )[:_MAX_SIGNAL_CLUSTERS]
        return {
            "lines_scanned": total_lines,
            "signal_lines": signal_lines,
            "signal_signatures": len(clusters),
            "omitted_signatures": omitted_signatures,
            "clusters": selected,
        }

    def _tracecite_inspect(self, args: Mapping[str, Any]) -> str:
        file_name = str(args.get("file") or "")
        if not file_name:
            raise ValueError("file must be non-empty")
        path = common._safe_input(self.input_root, file_name)
        if file_name in self._inspected_files:
            return (
                "ALREADY_INSPECTED: this source already has a bounded structural and incident-signal "
                "inspection in context. Use tracecite_get for known #L references or tracecite_search "
                "only for a genuinely new semantic hypothesis."
            )

        survey = _survey_overview(self._survey(path))
        signals = self._scan_incident_signals(file_name, path)
        self._inspected_files.add(file_name)

        clusters = list(signals["clusters"])
        header = [
            "@TCI 1 inspect status=ok outcome=bounded",
            f"@SRC file={file_name} bytes={path.stat().st_size}",
            (
                "@COV "
                f"lines_scanned={signals['lines_scanned']} "
                f"incident_signal_lines={signals['signal_lines']} "
                f"signal_signatures={signals['signal_signatures']} "
                f"signal_clusters_returned={len(clusters)} "
                f"signal_signatures_omitted={signals['omitted_signatures']}"
            ),
            "@STRUCT " + json.dumps(survey, ensure_ascii=False, separators=(",", ":")),
            (
                "@GUIDE Reason from the inspection first. Use tracecite_get for context around a known #L. "
                "Use tracecite_search only when a new semantic hypothesis is not already represented here."
            ),
        ]
        sections: list[str] = ["\n".join(header)]
        rendered_chars = len(sections[0])
        seen_rows: set[int] = set()
        output_truncated = False

        for rank, cluster in enumerate(clusters, 1):
            block_lines = [
                (
                    f"@SIGNAL rank={rank} severity={cluster['severity']} count={cluster['count']} "
                    f"first_line={cluster['line']} signature={cluster['signature']}"
                )
            ]
            for line_number, text in cluster["rows"]:
                if line_number in seen_rows:
                    continue
                seen_rows.add(line_number)
                block_lines.append(_render_line(line_number, text))
            block = "\n".join(block_lines)
            if rendered_chars + len(block) + 1 > _MAX_INSPECT_CHARS:
                output_truncated = True
                break
            sections.append(block)
            rendered_chars += len(block) + 1

        sections.append(
            "@STOP inspection_output_truncated=" + str(output_truncated)
            + " source_scan_complete=True"
        )
        return "\n".join(sections)

    def _ensure_line_index(self, file_name: str, path: Path) -> None:
        if file_name in self._line_indexes:
            return
        index: list[tuple[int, int]] = []
        total_lines = 0
        offset = 0
        with path.open("rb") as handle:
            for raw in handle:
                total_lines += 1
                if (total_lines - 1) % _INDEX_STRIDE == 0:
                    index.append((total_lines, offset))
                offset += len(raw)
        self._line_indexes[file_name] = index
        self._line_counts[file_name] = total_lines

    def _tracecite_get(self, args: Mapping[str, Any]) -> str:
        file_name = str(args.get("file") or "")
        if not file_name:
            raise ValueError("file must be non-empty")
        path = common._safe_input(self.input_root, file_name)
        if file_name not in self._inspected_files:
            return "INSPECT_REQUIRED: call tracecite_inspect on this source before line recovery."
        try:
            line = int(args.get("line"))
            radius = int(args.get("radius", 3))
        except (TypeError, ValueError) as exc:
            raise ValueError("line and radius must be integers") from exc
        if line < 1:
            raise ValueError("line must be >= 1")
        if radius < 0 or radius > _MAX_GET_RADIUS:
            raise ValueError(f"radius must be between 0 and {_MAX_GET_RADIUS}")

        self._ensure_line_index(file_name, path)
        total_lines = self._line_counts[file_name]
        start = max(1, line - radius)
        end = min(total_lines, line + radius)
        anchors = self._line_indexes[file_name]
        anchor_line, anchor_offset = anchors[0] if anchors else (1, 0)
        for candidate_line, candidate_offset in anchors:
            if candidate_line > start:
                break
            anchor_line, anchor_offset = candidate_line, candidate_offset

        rendered: list[str] = []
        with path.open("rb") as handle:
            handle.seek(anchor_offset)
            current = anchor_line
            while current <= end:
                raw = handle.readline()
                if not raw:
                    break
                if current >= start:
                    rendered.append(
                        _render_line(current, raw.decode("utf-8", errors="replace"))
                    )
                current += 1
        return "\n".join(
            [
                "@TCG 1 get status=ok",
                f"@SRC file={file_name}",
                f"@COV requested_line={line} start_line={start} end_line={end} total_lines={total_lines}",
                *rendered,
            ]
        )

    def _tracecite_search_scale(self, args: Mapping[str, Any]) -> str:
        file_name = str(args.get("file") or "")
        path = common._safe_input(self.input_root, file_name)
        query = str(args.get("query") or "").strip()
        if not query:
            raise ValueError("query must be non-empty")
        if file_name not in self._inspected_files:
            return "INSPECT_REQUIRED: call tracecite_inspect before targeted semantic search."
        if _LINE_REFERENCE_RE.fullmatch(query):
            return (
                "USE_GET: numeric/line-reference queries are not semantic search. "
                "Call tracecite_get with the known line number and a small radius."
            )
        normalized_query = query.casefold()
        seen = self._searched_queries.setdefault(file_name, set())
        if normalized_query in seen:
            return (
                "NO_NEW_EVIDENCE: this exact semantic query was already searched. "
                "Reason from the existing result, use tracecite_get for known #L context, "
                "or search only if you have a different concrete hypothesis."
            )
        seen.add(normalized_query)

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
            if name == "tracecite_inspect":
                return self._tracecite_inspect(args)
            if name == "tracecite_get":
                return self._tracecite_get(args)
            if name == "tracecite_search":
                return self._tracecite_search_scale(args)
        return super().call(name, args)


def _tools_for_mode(mode: str, files: Sequence[Path]) -> list[dict[str, Any]]:
    if mode not in {"tracecite", "tracecite_context"}:
        return _ORIGINAL_TOOLS_FOR_MODE(mode, files)
    file_property = common._common_file_property(files)
    return [
        common._function_tool(
            "tracecite_inspect",
            (
                "Inspect one large raw evidence source first. Returns a bounded structural overview plus "
                "generic high-signal incident windows with precise #L references. The scan is complete even "
                "though the returned evidence is bounded. Reason from this before issuing searches."
            ),
            {"file": file_property},
            ["file"],
        ),
        common._function_tool(
            "tracecite_get",
            (
                "Recover a small exact line window around a #L reference already discovered by inspect or "
                "search. Use this instead of searching for line numbers. radius must be 0-8."
            ),
            {
                "file": file_property,
                "line": {"type": "integer", "minimum": 1},
                "radius": {"type": "integer", "minimum": 0, "maximum": _MAX_GET_RADIUS},
            },
            ["file", "line", "radius"],
        ),
        common._function_tool(
            "tracecite_search",
            (
                "Targeted semantic search only after inspect and only for a genuinely new concrete hypothesis, "
                "identifier, component, operation, or fault signature not already covered. Do not search line "
                "numbers and do not repeat an exact query; use tracecite_get for #L context."
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
