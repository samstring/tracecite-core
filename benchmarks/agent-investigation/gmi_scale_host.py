from __future__ import annotations

import copy
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
from tracecite.integrations.agent_profile import render_frame
from tracecite.integrations.agent_projection import project
from tracecite.integrations.context_engine import ContextEngine
from tracecite.integrations.evidence_ledger import EvidenceLedger
from tracecite.runtime.evidence_progress import EvidenceProgressTracker, EvidenceReadiness
from tracecite.runtime.tools import search as tracecite_search


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
_CONTEXT_WINDOW_RE = re.compile(
    r"context window exceeds limit|context length exceeded|maximum context length|context_length_exceeded",
    re.IGNORECASE,
)

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


def _host_failure_reason(exc: BaseException) -> str:
    """Return a stable benchmark failure reason without hiding the raw error."""

    if isinstance(exc, subprocess.TimeoutExpired):
        return "tool_timeout"
    if _CONTEXT_WINDOW_RE.search(str(exc)):
        return "context_window_exceeded"
    return "host_error"


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


def _line_ranges(line_numbers: Sequence[int] | set[int]) -> tuple[tuple[int, int], ...]:
    ordered = sorted(set(int(item) for item in line_numbers))
    if not ordered:
        return ()
    ranges: list[tuple[int, int]] = []
    start = previous = ordered[0]
    for current in ordered[1:]:
        if current == previous + 1:
            previous = current
            continue
        ranges.append((start, previous))
        start = previous = current
    ranges.append((start, previous))
    return tuple(ranges)


def _progress_line(progress: EvidenceReadiness) -> str:
    delta = progress.delta
    return (
        "@PROGRESS "
        f"new_evidence={delta.new_evidence} new_lines={delta.new_lines} "
        f"seen_evidence={progress.seen_evidence} seen_lines={progress.seen_lines} "
        f"source_complete={progress.source_complete} "
        f"no_growth={progress.consecutive_no_growth} stop={progress.stop_reason}"
    )


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
        self._progress_by_file: dict[str, EvidenceProgressTracker] = {}

    def _progress(self, file_name: str) -> EvidenceProgressTracker:
        return self._progress_by_file.setdefault(file_name, EvidenceProgressTracker())

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
                    else:
                        cluster = {
                            "signature": signature,
                            "severity": severity,
                            "count": 1,
                            "line": line_number,
                            "rows": [*before, (line_number, text)],
                            "remaining_after": _CONTEXT_RADIUS,
                        }
                        if len(clusters) < _MAX_SIGNAL_SIGNATURES:
                            clusters[signature] = cluster
                            active.append(cluster)
                        else:
                            victim_signature, victim = min(
                                clusters.items(),
                                key=lambda item: (
                                    int(item[1]["severity"]),
                                    -int(item[1]["count"]),
                                    -int(item[1]["line"]),
                                ),
                            )
                            if severity > int(victim["severity"]):
                                del clusters[victim_signature]
                                active = [item for item in active if item is not victim]
                                clusters[signature] = cluster
                                active.append(cluster)
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
        tracker = self._progress(file_name)
        if file_name in self._inspected_files:
            progress = tracker.observe(source=file_name, source_complete=True)
            return "\n".join(
                [
                    "@TCI 1 inspect status=no_new_evidence outcome=bounded",
                    f"@SRC file={file_name} bytes={path.stat().st_size}",
                    _progress_line(progress),
                    "@STOP reason=NO_NEW_EVIDENCE source_scan_complete=True",
                ]
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
            block_rows: list[tuple[int, str]] = []
            block_lines = [
                (
                    f"@SIGNAL rank={rank} severity={cluster['severity']} count={cluster['count']} "
                    f"first_line={cluster['line']} signature={cluster['signature']}"
                )
            ]
            for line_number, text in cluster["rows"]:
                if line_number in seen_rows:
                    continue
                block_rows.append((line_number, text))
                block_lines.append(_render_line(line_number, text))
            block = "\n".join(block_lines)
            if rendered_chars + len(block) + 1 > _MAX_INSPECT_CHARS:
                output_truncated = True
                break
            seen_rows.update(line_number for line_number, _text in block_rows)
            sections.append(block)
            rendered_chars += len(block) + 1

        progress = tracker.observe(
            source=file_name,
            line_ranges=_line_ranges(seen_rows),
            source_complete=True,
        )
        sections.append(_progress_line(progress))
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
        tracker = self._progress(file_name)
        if tracker.range_is_covered(file_name, start, end):
            progress = tracker.observe(source=file_name)
            return "\n".join(
                [
                    "@TCG 1 get status=no_new_evidence",
                    f"@SRC file={file_name}",
                    f"@COV requested_line={line} start_line={start} end_line={end} total_lines={total_lines}",
                    _progress_line(progress),
                    "@STOP reason=NO_NEW_EVIDENCE requested_range_already_covered=True",
                ]
            )

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
        progress = tracker.observe(source=file_name, line_ranges=((start, end),))
        return "\n".join(
            [
                "@TCG 1 get status=ok",
                f"@SRC file={file_name}",
                f"@COV requested_line={line} start_line={start} end_line={end} total_lines={total_lines}",
                _progress_line(progress),
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
        tracker = self._progress(file_name)
        normalized_query = query.casefold()
        seen = self._searched_queries.setdefault(file_name, set())
        if normalized_query in seen:
            progress = tracker.observe(source=file_name)
            return "\n".join(
                [
                    "@TCF 1 search status=no_new_evidence outcome=bounded",
                    f"@SRC file={file_name}",
                    _progress_line(progress),
                    "@STOP reason=NO_NEW_EVIDENCE exact_query_already_searched=True",
                ]
            )
        seen.add(normalized_query)

        payload = tracecite_search(
            path,
            query,
            regex=bool(args.get("regex")),
            snapshot=False,
            segmenter="auto",
            max_evidence=None,
            max_line_chars=None,
            cache=True,
        )
        if not isinstance(payload, Mapping):
            payload = payload.to_dict()
        canonical = copy.deepcopy(dict(payload))

        ledger_dir = self.scratch / "ledger"
        ledger_dir.mkdir(parents=True, exist_ok=True)
        result_id = EvidenceLedger(ledger_dir).store(canonical)
        data = dict(canonical.get("data") or {})
        data["result_id"] = result_id
        canonical["data"] = data

        evidence_ids = [
            str(item.get("uri") or "")
            for item in canonical.get("evidence") or []
            if isinstance(item, Mapping) and str(item.get("uri") or "")
        ]
        progress = tracker.observe(source=file_name, evidence_ids=evidence_ids)
        if evidence_ids and progress.delta.new_evidence == 0:
            return "\n".join(
                [
                    "@TCF 1 search status=no_new_evidence outcome=bounded",
                    f"@R {result_id}",
                    f"@SRC file={file_name}",
                    _progress_line(progress),
                    "@STOP reason=NO_NEW_EVIDENCE search_returned_only_seen_evidence=True",
                ]
            )

        baseline = project(canonical, profile="frame", max_output_chars=None)
        baseline_frame = render_frame(baseline)
        selected_frame = baseline_frame

        if self.mode == "tracecite_context":
            if not self.context_id:
                raise RuntimeError("tracecite_context requires context_id")
            projected = ContextEngine(ledger_dir, self.context_id).project_search(
                canonical,
                result_id=result_id,
            )
            delta = project(projected, profile="frame", max_output_chars=None)
            delta_frame = render_frame(delta)
            if len(delta_frame) < len(baseline_frame):
                selected_frame = delta_frame

        return selected_frame + "\n" + _progress_line(progress)

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
                "search. Fully covered ranges return NO_NEW_EVIDENCE without rereading the source. "
                "Use this instead of searching for line numbers. radius must be 0-8."
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
                "identifier, component, operation, or fault signature not already covered. Exact duplicate "
                "queries and searches that return only previously seen evidence stop with NO_NEW_EVIDENCE. "
                "Do not search line numbers; use tracecite_get for #L context."
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
        failure_reason = _host_failure_reason(exc)
        if transcript_value:
            try:
                common._append_event(
                    Path(transcript_value),
                    {
                        "type": "host_error",
                        "error": type(exc).__name__,
                        "failure_reason": failure_reason,
                        "message": str(exc),
                    },
                )
            except Exception:
                pass
        print(
            f"benchmark host failed: reason={failure_reason} {type(exc).__name__}: {exc}",
            file=os.sys.stderr,
        )
        raise
