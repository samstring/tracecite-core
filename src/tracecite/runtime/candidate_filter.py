from __future__ import annotations

"""Parity-oriented filter fast path for single-line segmenters.

Unlike :mod:`candidate_search`, this module reproduces the existing
``filter_text`` artifacts and ``FilterResult`` shape.  It is intentionally
narrow: only escaped-literal patterns, no time/line/PID scopes, no folding,
and segmenters whose logical record is one physical line.

The important optimization is that unmatched JSONL rows are never
``json.loads``-parsed.  Raw text is scanned once; only matched rows are handed
to the segmenter for structured metadata.  Unmatched token statistics are
still computed from the exact record text so Agent guidance is preserved.
"""

import re
import shutil
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Iterable, Mapping, Optional, Union

from tracecite_core.matcher import Matcher, PatternComponent
from tracecite_core.segmenter import JsonLineSegmenter, RawTextSegmenter, Segmenter
from tracecite_core.text_filter import (
    DEFAULT_MAX_LINE_CHARS,
    FilterResult,
    _UNMATCHED_POOL_MAX,
    _UNMATCHED_SAMPLE_CHARS,
    _build_unmatched_summary,
    _count_lines,
    _default_tag_from_pattern,
    _extract_record_tokens,
    _safe_tag,
    _truncate_output_line,
    _write_filter_history,
    record_timestamp,
)


class CandidateFilterUnsupported(RuntimeError):
    """The request cannot safely use the candidate-first parity fast path."""


def literal_from_escaped_pattern(pattern: str) -> str | None:
    """Invert ``re.escape`` only when round-tripping proves it is exact."""

    raw = re.sub(r"\\(.)", r"\1", pattern)
    return raw if re.escape(raw) == pattern else None


def supports_single_line_fast_filter(segmenter: Segmenter) -> bool:
    return isinstance(segmenter, JsonLineSegmenter) or (
        isinstance(segmenter, RawTextSegmenter) and segmenter.mode == "line"
    )


def _one_record(
    segmenter: Segmenter,
    *,
    line_number: int,
    text: str,
):
    rows = list(segmenter.segment_lines(iter([(line_number, text)])))
    if len(rows) != 1:
        raise CandidateFilterUnsupported(
            f"single-line segmenter yielded {len(rows)} records for line {line_number}"
        )
    return rows[0]


def filter_literal_single_line(
    input_path: Path,
    *,
    pattern: str,
    tag: Optional[str] = None,
    pattern_components: Optional[
        Iterable[Union[PatternComponent, Mapping[str, object]]]
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
    max_line_chars: Optional[int] = DEFAULT_MAX_LINE_CHARS,
) -> FilterResult:
    """Fast ``filter_text`` equivalent for the conservative eligible subset."""

    if pattern_components:
        raise CandidateFilterUnsupported("pattern components require legacy filter")
    if str(match_mode).strip().lower() != "or":
        raise CandidateFilterUnsupported("non-OR matching requires legacy filter")
    if any(value is not None for value in (pid, tail_lines, line_from, line_to, last, since, until)):
        raise CandidateFilterUnsupported("scoped filtering requires legacy filter")
    if template_threshold > 0:
        raise CandidateFilterUnsupported("template folding requires legacy filter")
    selected = segmenter or RawTextSegmenter(mode="line")
    if not supports_single_line_fast_filter(selected):
        raise CandidateFilterUnsupported(type(selected).__name__)
    literal = literal_from_escaped_pattern(pattern)
    if literal is None or not literal:
        raise CandidateFilterUnsupported("pattern is not an exact escaped literal")

    original = Path(input_path).expanduser().resolve()
    if not original.is_file():
        raise FileNotFoundError(original)

    resolved_tag = tag or _default_tag_from_pattern(pattern)
    safe_tag = _safe_tag(resolved_tag)
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
        snapshot_lines = _count_lines(snapshot_path, encoding=encoding)

    original_total = _count_lines(original, encoding=encoding)
    if output_path is None:
        filter_dir = src_dir / ".filtered"
        filter_dir.mkdir(parents=True, exist_ok=True)
        output_path = filter_dir / f"{safe_tag}_{original.name}"
        history_dir = filter_dir
    else:
        history_dir = output_path.parent / ".filtered"
        if output_path.parent.name == ".filtered":
            history_dir = output_path.parent

    matcher = Matcher(pattern)
    records_path = Path(str(output_path) + ".records.jsonl")
    hits_candidate = Path(str(output_path) + ".hits.jsonl")

    match_records = 0
    match_lines = 0
    scoped_physical_lines = 0
    scoped_records = 0
    unmatched_count = 0
    token_counter: Counter = Counter()
    unmatched_pool: list[str] = []
    term_usage: dict[str, int] = {}
    matched_by_counts: Counter = Counter()
    hit_record_count = 0
    lines_truncated = 0
    # For eligible segmenters this reference cannot alter record boundaries.
    # JsonLine timestamps are parsed eagerly; RawText has no timestamp.
    ref = datetime.fromtimestamp(work_input.stat().st_mtime)

    with records_path.open("w", encoding="utf-8") as records_handle, hits_candidate.open(
        "w", encoding="utf-8"
    ) as hits_handle, work_input.open("r", encoding=encoding, errors="replace") as source_handle:
        for line_number, text in enumerate(source_handle, start=1):
            # JsonLineSegmenter intentionally skips blank physical lines.
            if isinstance(selected, JsonLineSegmenter) and not text.strip():
                continue
            scoped_physical_lines += 1
            scoped_records += 1
            if literal not in text:
                unmatched_count += 1
                if len(unmatched_pool) < _UNMATCHED_POOL_MAX:
                    unmatched_pool.append(text[:_UNMATCHED_SAMPLE_CHARS])
                for token in _extract_record_tokens(
                    text,
                    header_re=selected.header_strip_re,
                    token_re=selected.token_re,
                ):
                    token_counter[token] += 1
                continue

            record = _one_record(selected, line_number=line_number, text=text)
            matched, term, terms_hit, matched_by = matcher.match_with_components(
                record.text, ()
            )
            if not matched:
                # Round-trip validation above should make this unreachable, but
                # never silently change matching semantics.
                raise CandidateFilterUnsupported(
                    "literal prefilter disagreed with Matcher"
                )

            rendered = record.text if record.text.endswith("\n") else record.text + "\n"
            if max_line_chars is not None:
                _, truncated = _truncate_output_line(
                    rendered,
                    max_line_chars=max_line_chars,
                    start_line=record.start_line,
                )
                if truncated:
                    lines_truncated += 1
            ts = record_timestamp(record, ref=ref, segmenter=selected)
            metadata = {
                "start_line": record.start_line,
                "end_line": record.end_line,
                "term": term,
                "terms": sorted(terms_hit),
                "matched_by": list(matched_by),
                "timestamp": ts.isoformat(timespec="milliseconds") if ts is not None else None,
            }
            records_handle.write(
                __import__("json").dumps(
                    {"text": rendered, "metadata": metadata}, ensure_ascii=False
                )
                + "\n"
            )
            match_records += 1
            match_lines += rendered.count("\n")
            if term is not None:
                hits_handle.write(
                    __import__("json").dumps(
                        {
                            "start_line": record.start_line,
                            "end_line": record.end_line,
                            "term": term,
                            "hit_lines": [record.start_line],
                            "matched_by": list(matched_by),
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                hit_record_count += 1
                for token in terms_hit:
                    term_usage[token] = term_usage.get(token, 0) + 1
            for component_id in matched_by:
                matched_by_counts[component_id] += 1

    unmatched_summary = _build_unmatched_summary(
        unmatched_count=unmatched_count,
        scoped_records=scoped_records,
        token_counter=token_counter,
        pool=unmatched_pool,
    )
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
        scope=None,
        time_from=None,
        time_to=None,
        records_path=records_path,
        engine=matcher.engine,
        unmatched_summary=unmatched_summary,
        term_usage=term_usage or None,
        match_mode="or",
        pattern_components=component_payload,
        matched_by_counts=(
            {key: matched_by_counts[key] for key in sorted(matched_by_counts)} or None
        ),
        matched_by_fallback=True,
    )

    history_dir.mkdir(parents=True, exist_ok=True)
    result.history_path = _write_filter_history(history_dir, result)
    if hit_record_count:
        result.hits_path = hits_candidate
    else:
        hits_candidate.unlink(missing_ok=True)

    import json

    with output_path.open("w", encoding="utf-8") as output_handle:
        output_handle.write(result.metadata_header())
        with records_path.open("r", encoding="utf-8") as records_handle:
            for line in records_handle:
                row = json.loads(line)
                rendered = str(row.get("text") or "")
                metadata = row.get("metadata") or {}
                start_line = int(metadata.get("start_line") or 0)
                if max_line_chars is not None:
                    rendered, _ = _truncate_output_line(
                        rendered,
                        max_line_chars=max_line_chars,
                        start_line=start_line,
                    )
                output_handle.write(rendered)

    return result
