"""Small, deterministic tool surface intended for AI agents."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Union

from tracecite_core.run import RunFile, RunIntegrityError, verify_manifest
from tracecite_core.segmenter import build_segmenter, detect_segmenter_kind
from tracecite_core.source import SourceError, resolve_paths
from tracecite_core.text_filter import FilterError, filter_text, text_time_range

from .runtime import DEFAULT_RUNTIME, ScenarioRuntime
from .schema import AgentResult, EvidencePointer, MAX_RESULT_EVIDENCE, ScenarioDocument
from .scenario import load_spec, run_scenario


def _sha256(path: Path) -> str:
    item = RunFile.from_path("evidence", path)
    if not item.sha256:
        raise RunIntegrityError(f"无法计算证据摘要: {path}")
    return item.sha256


def _evidence_uri(sha256: str, start_line: Optional[int], end_line: Optional[int]) -> str:
    fragment = ""
    if start_line is not None:
        fragment = f"#L{start_line}"
        if end_line is not None and end_line != start_line:
            fragment += f"-L{end_line}"
    return f"evidence://sha256/{sha256}{fragment}"


def _error(operation: str, exc: Exception) -> Dict[str, Any]:
    return AgentResult(
        operation=operation,
        status="error",
        outcome="unknown",
        error={"type": type(exc).__name__, "message": str(exc)},
    ).to_dict()


def probe(
    input_path: Union[str, Path],
    *,
    glob: str = "*",
    recursive: bool = False,
    segmenter: str = "auto",
) -> Dict[str, Any]:
    """Inspect sources without producing filter artifacts."""
    try:
        files = resolve_paths(str(input_path), glob=glob, recursive=recursive)
        sources: List[Dict[str, Any]] = []
        for path in files:
            kind = detect_segmenter_kind(path) if segmenter == "auto" else segmenter
            seg = build_segmenter(kind)
            source = RunFile.from_path("source", path)
            time_info = text_time_range(path, segmenter=seg)
            sources.append(
                {
                    "path": str(path.resolve()),
                    "size": source.size,
                    "sha256": source.sha256,
                    "segmenter": kind,
                    "records": time_info.get("total_records"),
                    "time_from": time_info.get("time_from"),
                    "time_to": time_info.get("time_to"),
                    "timestamped_records": time_info.get("timestamped_records"),
                }
            )
        return AgentResult(
            operation="probe",
            outcome="not_assessed",
            data={"sources": sources, "source_count": len(sources)},
            coverage={"files": len(sources)},
        ).to_dict()
    except (OSError, ValueError, SourceError) as exc:
        return _error("probe", exc)


def search(
    input_path: Union[str, Path],
    query: str,
    *,
    regex: bool = False,
    output_path: Optional[Union[str, Path]] = None,
    snapshot: bool = True,
    segmenter: str = "auto",
    last: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    fold: bool = False,
) -> Dict[str, Any]:
    """Search one source and return pointers; literal matching is the default."""
    try:
        source = Path(input_path).expanduser().resolve()
        kind = detect_segmenter_kind(source) if segmenter == "auto" else segmenter
        pattern = query if regex else re.escape(query)
        if output_path is None:
            run_id = datetime.now().strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
            resolved_output = (
                source.parent / ".tracecite" / "agent-search" / run_id / "evidence.log"
            )
        else:
            resolved_output = Path(output_path)
        result = filter_text(
            source,
            pattern=pattern,
            output_path=resolved_output,
            snapshot=snapshot,
            segmenter=build_segmenter(kind),
            last=last,
            since=since,
            until=until,
            template_threshold=10 if fold else 0,
        )
        evidence_source = Path(result.work_input).resolve()
        digest = _sha256(evidence_source)
        evidence: List[Dict[str, Any]] = []
        if result.records_path and result.records_path.is_file():
            with result.records_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if len(evidence) >= MAX_RESULT_EVIDENCE:
                        break
                    row = json.loads(line)
                    meta = row.get("metadata") or {}
                    start_line = meta.get("start_line")
                    end_line = meta.get("end_line")
                    text = str(row.get("text") or "")
                    pointer = EvidencePointer(
                        uri=_evidence_uri(digest, start_line, end_line),
                        source_path=str(evidence_source),
                        sha256=digest,
                        start_line=start_line,
                        end_line=end_line,
                        timestamp=meta.get("timestamp"),
                        label=next((item.strip() for item in text.splitlines() if item.strip()), "")[:240] or None,
                        metadata={"term": meta.get("term"), "terms": meta.get("terms") or []},
                    )
                    evidence.append(pointer.to_dict())
        summary = dict(result.unmatched_summary or {})
        next_queries = [
            str(item.get("token"))
            for item in summary.get("top_unmatched_tokens") or []
            if item.get("token")
        ][:10]
        warnings: List[str] = []
        if not evidence:
            warnings.append(
                "零命中只表示当前查询和范围内证据不足；可使用 next_queries、放宽时间窗或更换格式。"
            )
        artifacts = [
            {"role": role, "path": str(path)}
            for role, path in (
                ("filtered_log", result.output_path),
                ("matched_records", result.records_path),
                ("hit_metadata", result.hits_path),
                ("templates", result.templates_path),
            )
            if path is not None
        ]
        return AgentResult(
            operation="search",
            status="ok" if evidence else "no_match",
            outcome="supported" if evidence else "unknown",
            evidence=evidence,
            artifacts=artifacts,
            coverage={
                "scoped_lines": result.total_lines,
                "match_records": result.match_records,
                "match_lines": result.match_lines,
                "evidence_returned": len(evidence),
                "evidence_truncated": result.match_records > len(evidence),
                "unmatched": summary,
            },
            warnings=warnings,
            missing_evidence=(
                []
                if evidence
                else [
                    {
                        "kind": "query_coverage",
                        "detail": "No evidence matched the current query and scope.",
                    }
                ]
            ),
            next_queries=next_queries,
            data={
                "query": query,
                "regex": regex,
                "segmenter": kind,
                "engine": result.engine,
                "source_sha256": digest,
            },
        ).to_dict()
    except (OSError, ValueError, FilterError, RunIntegrityError) as exc:
        return _error("search", exc)


def expand(
    source_path: Union[str, Path],
    start_line: int,
    *,
    end_line: Optional[int] = None,
    before: int = 3,
    after: int = 3,
    expected_sha256: Optional[str] = None,
    max_chars: int = 20_000,
) -> Dict[str, Any]:
    """Expand bounded context around a cited line range after hash checking."""
    try:
        path = Path(source_path).expanduser().resolve()
        if start_line <= 0 or (end_line is not None and end_line < start_line):
            raise ValueError("行号范围无效")
        if max_chars <= 0:
            raise ValueError("max_chars 必须大于 0")
        digest = _sha256(path)
        if expected_sha256 and digest != expected_sha256:
            raise RunIntegrityError(
                f"证据文件摘要不匹配: {digest} != {expected_sha256}"
            )
        selected_end = end_line or start_line
        context_start = max(1, start_line - max(0, before))
        context_end = selected_end + max(0, after)
        rows: List[str] = []
        last_seen = 0
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for number, line in enumerate(handle, start=1):
                last_seen = number
                if number < context_start:
                    continue
                if number > context_end:
                    break
                rows.append(f"{number}: {line}")
        if last_seen < selected_end:
            raise ValueError(
                f"引用行超出证据文件范围: {selected_end} > {last_seen}"
            )
        text = "".join(rows)
        truncated = len(text) > max_chars
        if truncated:
            text = text[:max_chars]
        pointer = EvidencePointer(
            uri=_evidence_uri(digest, start_line, selected_end),
            source_path=str(path),
            sha256=digest,
            start_line=start_line,
            end_line=selected_end,
        )
        return AgentResult(
            operation="expand",
            outcome="supported",
            evidence=[pointer.to_dict()],
            coverage={
                "context_start_line": context_start,
                "context_end_line": context_end,
                "truncated": truncated,
            },
            data={"text": text},
        ).to_dict()
    except (OSError, ValueError, RunIntegrityError) as exc:
        return _error("expand", exc)


def verify(manifest_path: Union[str, Path]) -> Dict[str, Any]:
    """Verify a completed evidence manifest without throwing to the caller."""
    try:
        checked = verify_manifest(Path(manifest_path))
        return AgentResult(
            operation="verify",
            run_id=str(checked.get("run_id") or "") or None,
            verdict=str(checked.get("verdict") or "") or None,
            outcome="supported",
            coverage={"checked_files": checked.get("checked_files", 0)},
            verification={"integrity_checked": True, "manifest": str(Path(manifest_path))},
            data=checked,
        ).to_dict()
    except (OSError, ValueError, RunIntegrityError) as exc:
        return _error("verify", exc)


def run(
    scenario: Union[Mapping[str, Any], str, Path],
    *,
    base_dir: Optional[Union[str, Path]] = None,
    platform: str = "",
    runtime: ScenarioRuntime = DEFAULT_RUNTIME,
) -> Dict[str, Any]:
    """Execute a scenario and return the canonical Agent result envelope."""
    try:
        spec_path: Optional[Path] = None
        if isinstance(scenario, Mapping):
            document = ScenarioDocument.from_dict(scenario)
            spec = document.to_dict()
            resolved_base = Path(base_dir or Path.cwd()).expanduser().resolve()
        else:
            spec_path = Path(scenario).expanduser().resolve()
            spec = load_spec(spec_path)
            resolved_base = Path(base_dir).expanduser().resolve() if base_dir else spec_path.parent
        summary = run_scenario(
            spec,
            base_dir=resolved_base,
            platform=platform,
            spec_path=spec_path,
            runtime=runtime,
        )
        return AgentResult.from_scenario_summary(summary).to_dict()
    except Exception as exc:  # public tool boundary always returns a structured error
        return _error("run", exc)
