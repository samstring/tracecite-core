"""Candidate-first implementation of the public text filter contract.

This module intentionally reuses the stable artifact/scope helpers from
``text_filter`` while replacing its search loop. Candidate-first is enabled
only when Core can prove that a raw-line prefilter has no false negatives and
when record scope does not itself require a full semantic scan. Every candidate
record is re-checked with the original Matcher.
"""

from __future__ import annotations

import json
import re
import shutil
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Union

from .candidate_search import (
    can_capture_candidate_lines,
    candidate_anchors,
    iter_candidate_records,
    scan_candidate_lines,
    supports_candidate_records,
)
from .matcher import Matcher, PatternComponent, coerce_pattern_components
from .segmenter import JsonLineSegmenter, RawTextSegmenter, Segmenter
from . import text_filter as _legacy


@dataclass
class FilterResult(_legacy.FilterResult):
    """Filter result without publishing unmatched-search suggestion data."""

    candidate_strategy: str = "segment-first"

    def to_dict(self) -> Dict[str, object]:
        payload = super().to_dict()
        payload.pop("unmatched_summary", None)
        payload["candidate_strategy"] = self.candidate_strategy
        return payload


def _candidate_eligible(
    *,
    matcher: Matcher,
    segmenter: Segmenter,
    pid: Optional[int],
    tail_lines: Optional[int],
    line_from: Optional[int],
    line_to: Optional[int],
    last: Optional[str],
    since: Optional[str],
    until: Optional[str],
) -> bool:
    if any(value is not None for value in (pid, tail_lines, line_from, line_to, last, since, until)):
        return False
    return supports_candidate_records(segmenter) and candidate_anchors(matcher) is not None


def filter_text(
    input_path: Path,
    *,
    pattern: str,
    tag: Optional[str] = None,
    pattern_components: Optional[
        Iterable[Union[PatternComponent, Mapping[str, Any]]]
    ] = None,
    match_mode: str = "or",
    output_path: Optional[Path] = None,
    snapshot: bool = False,
    pid: Optional[int] = None,
    tail_lines: Optional[int] = None,
    line_from: Optional[int] = None,
    line_to: Optional[int] = None,
    last: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    segmenter: Optional[Segmenter] = None,
    template_threshold: int = 0,
    encoding: str = "utf-8",
    max_line_chars: Optional[int] = _legacy.DEFAULT_MAX_LINE_CHARS,
    parse_record_timestamps: bool = True,
) -> FilterResult:
    """Filter text with a conservative raw-candidate → segment → re-check plan."""
    original = Path(input_path).expanduser().resolve()
    if not original.is_file():
        raise _legacy.FilterError(f"日志文件不存在: {original}")
    if not pattern:
        raise _legacy.FilterError("必须指定 pattern（--grep 或 --preset）")
    if str(match_mode).strip().lower() != "or":
        raise _legacy.FilterError("当前过滤组件只支持 OR 组合")
    try:
        normalized_components = coerce_pattern_components(pattern_components)
    except (TypeError, ValueError) as exc:
        raise _legacy.FilterError(str(exc)) from exc

    if tail_lines is not None and tail_lines <= 0:
        raise _legacy.FilterError("--tail-lines 必须大于 0")
    if line_from is not None and line_from <= 0:
        raise _legacy.FilterError("--line-from 必须大于 0")
    if line_to is not None and line_to <= 0:
        raise _legacy.FilterError("--line-to 必须大于 0")
    if line_from is not None and line_to is not None and line_from > line_to:
        raise _legacy.FilterError("--line-from 不能大于 --line-to")

    try:
        matcher = Matcher(pattern)
    except re.error as exc:
        raise _legacy.FilterError(f"非法正则: {exc}") from exc

    selected_segmenter = segmenter or RawTextSegmenter()
    component_payload = [
        _legacy._bounded_component_dict(component) for component in normalized_components
    ]
    matched_by_fallback = not bool(normalized_components)
    if matched_by_fallback:
        component_payload = [
            {
                "id": "pattern",
                "kind": "pattern",
                "effective": True,
                "reserved": True,
                "fallback": True,
                "pattern_ref": "final",
            }
        ]

    resolved_tag = tag or _legacy._default_tag_from_pattern(pattern)
    safe_tag = _legacy._safe_tag(resolved_tag)
    src_dir = original.parent
    explicit_output = output_path is not None
    if output_path is not None:
        output_path = Path(output_path).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)

    snapshot_path: Optional[Path] = None
    snapshot_lines: Optional[int] = None
    work_input = original
    if snapshot:
        snapshot_root = output_path.parent if explicit_output and output_path else src_dir
        snap_dir = snapshot_root / ".snapshots"
        snap_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%dT%H%M%S%f")
        snapshot_path = snap_dir / f"{original.stem}_{stamp}.log"
        shutil.copy2(original, snapshot_path)
        work_input = snapshot_path

    if output_path is None:
        filter_dir = src_dir / ".filtered"
        filter_dir.mkdir(parents=True, exist_ok=True)
        output_path = filter_dir / f"{safe_tag}_{original.name}"
        history_dir = filter_dir
    else:
        history_dir = output_path.parent / ".filtered"
        if output_path.parent.name == ".filtered":
            history_dir = output_path.parent

    use_candidates = _candidate_eligible(
        matcher=matcher,
        segmenter=selected_segmenter,
        pid=pid,
        tail_lines=tail_lines,
        line_from=line_from,
        line_to=line_to,
        last=last,
        since=since,
        until=until,
    )
    candidate_scan = (
        scan_candidate_lines(
            work_input,
            matcher,
            encoding=encoding,
            capture_lines=can_capture_candidate_lines(selected_segmenter),
        )
        if use_candidates
        else None
    )
    candidate_first = candidate_scan is not None
    record_segmenter = selected_segmenter
    if (
        candidate_first
        and not parse_record_timestamps
        and isinstance(selected_segmenter, JsonLineSegmenter)
    ):
        record_segmenter = selected_segmenter.with_timestamp_parsing(False)

    work_total_lines = (
        candidate_scan.total_lines
        if candidate_scan is not None
        else _legacy._count_lines(work_input, encoding=encoding)
    )
    if snapshot:
        snapshot_lines = work_total_lines
    original_total = (
        work_total_lines
        if not snapshot
        else _legacy._count_lines(original, encoding=encoding)
    )

    time_from, time_to, last_raw = _legacy._resolve_time_window(
        work_input,
        last=last,
        since=since,
        until=until,
        segmenter=selected_segmenter,
        encoding=encoding,
    )
    ref = (
        datetime.fromtimestamp(work_input.stat().st_mtime)
        if candidate_first
        else _legacy.reference_datetime(
            work_input, segmenter=selected_segmenter, encoding=encoding
        )
    )
    scope = _legacy._build_scope_desc(
        tail_lines=tail_lines,
        line_from=line_from,
        line_to=line_to,
        pid=pid,
        last=last_raw,
        time_from=time_from,
        time_to=time_to,
    )
    scope_start, scope_end = _legacy._resolve_scope_bounds(
        work_total_lines,
        tail_lines=tail_lines,
        line_from=line_from,
        line_to=line_to,
    )

    records_path = Path(str(output_path) + ".records.jsonl")
    hits_candidate = Path(str(output_path) + ".hits.jsonl")
    records_handle = records_path.open("w", encoding="utf-8")
    hits_handle = hits_candidate.open("w", encoding="utf-8")

    match_records = 0
    match_lines = 0
    hit_record_count = 0
    term_usage: Dict[str, int] = {}
    matched_by_counts: Counter = Counter()
    template_items: List[Dict[str, object]] = []
    lines_truncated = 0
    scoped_physical_lines = work_total_lines if candidate_first else 0
    pid_token = f"[{int(pid)}]" if pid is not None else None

    if candidate_first:
        raw_records = iter_candidate_records(
            work_input,
            record_segmenter,
            candidate_scan.line_numbers,
            encoding=encoding,
            captured_lines=candidate_scan.captured_lines,
        )
    else:
        raw_records = _legacy._iter_merged_records(
            work_input, segmenter=selected_segmenter, encoding=encoding
        )

    try:
        for record in raw_records:
            if not _legacy._record_overlaps_scope(record, scope_start, scope_end):
                continue
            if not _legacy._record_in_time_window(
                record,
                ref=ref,
                time_from=time_from,
                time_to=time_to,
                segmenter=selected_segmenter,
            ):
                continue
            if not candidate_first:
                scoped_physical_lines += record.end_line - record.start_line + 1
            if pid_token is not None:
                header = record.text.split("\n", 1)[0]
                if (
                    pid_token not in header
                    and str(record.fields.get("pid") or "") != str(int(pid))
                ):
                    continue

            matched, term, terms_hit, matched_by = matcher.match_with_components(
                record.text, normalized_components
            )
            if not matched:
                continue

            text = record.text if record.text.endswith("\n") else record.text + "\n"
            if max_line_chars is not None:
                _, truncated = _legacy._truncate_output_line(
                    text,
                    max_line_chars=max_line_chars,
                    start_line=record.start_line,
                )
                if truncated:
                    lines_truncated += 1
            ts = (
                _legacy.record_timestamp(
                    record, ref=ref, segmenter=record_segmenter
                )
                if parse_record_timestamps
                else None
            )
            metadata = {
                "start_line": record.start_line,
                "end_line": record.end_line,
                "term": term,
                "terms": sorted(terms_hit),
                "matched_by": list(matched_by),
                "timestamp": (
                    ts.isoformat(timespec="milliseconds") if ts is not None else None
                ),
            }
            records_handle.write(
                json.dumps({"text": text, "metadata": metadata}, ensure_ascii=False)
                + "\n"
            )
            match_records += 1
            match_lines += text.count("\n")
            if term is not None:
                hits_handle.write(
                    json.dumps(
                        {
                            "start_line": record.start_line,
                            "end_line": record.end_line,
                            "term": term,
                            "hit_lines": _legacy._hit_lines(record, term),
                            "matched_by": list(matched_by),
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                hit_record_count += 1
                for token in terms_hit:
                    term_usage[token] = term_usage.get(token, 0) + 1
            if "pattern" in matched_by:
                matched_by_fallback = True
            for component_id in matched_by:
                matched_by_counts[component_id] += 1
            if template_threshold > 0:
                template_items.append(
                    {
                        "text": record.text,
                        "term": term,
                        "ts": _legacy._format_scope_time(ts) if ts is not None else None,
                    }
                )
    finally:
        records_handle.close()
        hits_handle.close()

    if matched_by_fallback and not any(
        str(item.get("id")) == "pattern" for item in component_payload
    ):
        component_payload.append(
            {
                "id": "pattern",
                "kind": "pattern",
                "effective": True,
                "reserved": True,
                "fallback": True,
                "pattern_ref": "final",
            }
        )

    strategy = "segment-first"
    if candidate_scan is not None:
        strategy = f"candidate-first:{candidate_scan.strategy}"

    result = FilterResult(
        original_source=original,
        original_total_lines_at_run=original_total,
        output_path=output_path,
        tag=resolved_tag,
        pattern=pattern,
        work_input=work_input,
        total_lines=scoped_physical_lines,
        match_lines=match_lines,
        match_records=match_records,
        lines_truncated=lines_truncated,
        max_line_chars=max_line_chars,
        snapshot_path=snapshot_path,
        snapshot_lines=snapshot_lines,
        scope=scope,
        time_from=_legacy._format_scope_time(time_from) if time_from else None,
        time_to=_legacy._format_scope_time(time_to) if time_to else None,
        records_path=records_path,
        engine=matcher.engine,
        unmatched_summary=None,
        term_usage=term_usage or None,
        match_mode="or",
        pattern_components=component_payload or None,
        matched_by_counts=(
            {key: matched_by_counts[key] for key in sorted(matched_by_counts)} or None
        ),
        matched_by_fallback=matched_by_fallback,
        candidate_strategy=strategy,
    )

    history_dir.mkdir(parents=True, exist_ok=True)
    result.history_path = _legacy._write_filter_history(history_dir, result)
    if hit_record_count:
        result.hits_path = hits_candidate
    else:
        hits_candidate.unlink(missing_ok=True)

    if template_threshold > 0 and template_items and match_records >= template_threshold:
        entries = _legacy._fold_templates(
            template_items,
            normalizers=selected_segmenter.template_normalizers,
        )
        if entries:
            templates_path = Path(str(output_path) + ".templates.jsonl")
            templates_path.write_text(
                "".join(json.dumps(entry, ensure_ascii=False) + "\n" for entry in entries),
                encoding="utf-8",
            )
            result.templates_path = templates_path
            result.template_stats = _legacy.template_stats(
                entries, match_records=match_records
            )

    with output_path.open("w", encoding="utf-8") as output_handle:
        output_handle.write(result.metadata_header())
        with records_path.open("r", encoding="utf-8") as records_reader:
            for line in records_reader:
                row = json.loads(line)
                text = str(row.get("text") or "")
                metadata = row.get("metadata") or {}
                start_line = int(metadata.get("start_line") or 0)
                if max_line_chars is not None:
                    text, _ = _legacy._truncate_output_line(
                        text,
                        max_line_chars=max_line_chars,
                        start_line=start_line,
                    )
                output_handle.write(text)
    return result
