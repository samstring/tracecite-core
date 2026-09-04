from __future__ import annotations

"""Mechanical search dispatch for the canonical Runtime.

The fast path is deliberately conservative: exact literal searches over
single-line segmenters use the parity-tested candidate-first filter. Any
request outside that proven subset falls back to the legacy Core filter with
unchanged semantics. Multiline local-record recovery remains internal until its
artifact/result parity is proven at this boundary.
"""

from pathlib import Path
from typing import Optional

from tracecite_core.segmenter import Segmenter
from tracecite_core.text_filter import FilterResult, filter_text

from .candidate_filter import CandidateFilterUnsupported, filter_literal_single_line


def search_text(
    source: Path,
    *,
    pattern: str,
    regex: bool,
    output_path: Path,
    snapshot: bool,
    segmenter: Segmenter,
    last: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    fold: bool = False,
    max_line_chars: Optional[int] = None,
) -> FilterResult:
    """Execute one search with a correctness-preserving candidate-first fast path."""

    template_threshold = 10 if fold else 0
    if not regex:
        try:
            return filter_literal_single_line(
                source,
                pattern=pattern,
                output_path=output_path,
                snapshot=snapshot,
                segmenter=segmenter,
                last=last,
                since=since,
                until=until,
                template_threshold=template_threshold,
                max_line_chars=max_line_chars,
            )
        except CandidateFilterUnsupported:
            pass

    return filter_text(
        source,
        pattern=pattern,
        output_path=output_path,
        snapshot=snapshot,
        segmenter=segmenter,
        last=last,
        since=since,
        until=until,
        template_threshold=template_threshold,
        max_line_chars=max_line_chars,
    )


__all__ = ["search_text"]
