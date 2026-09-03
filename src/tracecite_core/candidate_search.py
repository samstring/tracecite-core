"""Conservative candidate-first helpers for text evidence search.

The first pass only locates physical lines that contain literals which every
successful match must contain. Full query semantics are always re-checked on
complete logical records afterwards. If Core cannot prove a no-false-negative
candidate plan, callers must fall back to the ordinary segment-first path.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, List, Optional, Sequence, Set, Tuple

try:
    from re import _parser as _RE_PARSER  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover
    import sre_parse as _RE_PARSER  # type: ignore[no-redef]

from .matcher import Matcher
from .records import Record
from .segmenter import (
    FormatSegmenter,
    JsonLineSegmenter,
    RawTextSegmenter,
    RegexSegmenter,
    Segmenter,
)

_MAX_CANDIDATE_LINES = 200_000
_MAX_CANDIDATE_RATIO = 0.35
_MIN_RATIO_SAMPLE_LINES = 10_000


@dataclass(frozen=True)
class CandidateScan:
    line_numbers: frozenset[int]
    total_lines: int
    anchors: Tuple[str, ...]
    strategy: str


def _op_name(op: Any) -> str:
    return str(op)


def _sequence_data(sequence: Any) -> Any:
    return getattr(sequence, "data", sequence)


def _split_anchor(anchor: str) -> Optional[str]:
    """Return a line-local piece that is still mandatory for the same match."""
    if not anchor:
        return None
    pieces = [part for part in anchor.splitlines() if part]
    if not pieces:
        return None
    return max(pieces, key=len)


def _literal_run(sequence: Sequence[Any], start: int) -> Tuple[str, int]:
    chars: List[str] = []
    index = start
    while index < len(sequence):
        op, arg = sequence[index]
        if _op_name(op) != "LITERAL":
            break
        chars.append(chr(int(arg)))
        index += 1
    return "".join(chars), index


def _best_anchor_set(options: Iterable[Set[str]]) -> Optional[Set[str]]:
    prepared = [set(item) for item in options if item]
    if not prepared:
        return None
    # Prefer the plan whose shortest alternative is longest. That usually makes
    # the raw pass much sparser while preserving the no-false-negative rule.
    return max(
        prepared,
        key=lambda values: (
            min(len(value) for value in values),
            sum(len(value) for value in values),
            -len(values),
        ),
    )


def _required_anchors(sequence: Any) -> Optional[Set[str]]:
    """Return literals covering every successful path, or None if unprovable.

    The returned set is OR semantics: every successful regex match is guaranteed
    to contain at least one returned literal. False positives are allowed because
    the full Matcher is applied again after logical record reconstruction.
    """
    data = list(_sequence_data(sequence))
    options: List[Set[str]] = []
    index = 0
    while index < len(data):
        op, arg = data[index]
        name = _op_name(op)
        if name == "LITERAL":
            run, index = _literal_run(data, index)
            anchor = _split_anchor(run)
            if anchor:
                options.append({anchor})
            continue
        if name in {"SUBPATTERN", "ATOMIC_GROUP"}:
            child = arg[-1] if name == "SUBPATTERN" else arg
            anchors = _required_anchors(child)
            if anchors:
                options.append(anchors)
        elif name == "BRANCH":
            branch_sets: List[Set[str]] = []
            for branch in arg[1]:
                anchors = _required_anchors(branch)
                if not anchors:
                    branch_sets = []
                    break
                branch_sets.append(anchors)
            if branch_sets:
                union: Set[str] = set()
                for anchors in branch_sets:
                    union.update(anchors)
                options.append(union)
        elif name in {"MAX_REPEAT", "MIN_REPEAT", "POSSESSIVE_REPEAT"}:
            min_count, _max_count, child = arg
            if int(min_count) > 0:
                anchors = _required_anchors(child)
                if anchors:
                    options.append(anchors)
        elif name == "IN":
            literals: List[str] = []
            only_literals = True
            for child_op, child_arg in _sequence_data(arg):
                if _op_name(child_op) == "LITERAL":
                    literals.append(chr(int(child_arg)))
                else:
                    only_literals = False
                    break
            # A one-character class can be a sound candidate but is normally so
            # dense that the fast path loses. Keep it only when no better anchor
            # is available; density gating below will usually reject it.
            if only_literals and literals:
                options.append(set(literals))
        # ASSERT / ASSERT_NOT / GROUPREF / ANY / CATEGORY / AT are deliberately
        # ignored. A later mandatory consuming token can still provide a plan.
        index += 1
    return _best_anchor_set(options)


def candidate_anchors(matcher: Matcher) -> Optional[Tuple[str, ...]]:
    """Build a conservative raw-line candidate plan for one Matcher."""
    if matcher.terms is not None:
        anchors: List[str] = []
        for term in matcher.terms:
            # Literal matching uses the original AC/literal Matcher on each
            # physical line. A literal spanning physical lines cannot therefore
            # use this fast path without changing semantics.
            if "\n" in term or "\r" in term:
                return None
            if not term:
                return None
            anchors.append(term)
        return tuple(dict.fromkeys(anchors)) or None

    if matcher.regex is None:
        return None
    # Python's Unicode IGNORECASE has equivalences that are wider than a raw
    # escaped-literal prefilter (for example ``k`` also matches Kelvin sign K).
    # A narrower candidate scan would introduce false negatives, so only ASCII
    # ignore-case regexes are eligible until candidate folding exactly mirrors
    # the regex engine.
    if matcher.regex.flags & re.IGNORECASE and not matcher.regex.flags & re.ASCII:
        return None
    try:
        parsed = _RE_PARSER.parse(matcher.pattern, matcher.regex.flags)
    except (re.error, RecursionError, TypeError, ValueError):
        return None
    anchors = _required_anchors(parsed)
    if not anchors:
        return None
    cleaned = tuple(
        sorted(
            {anchor for raw in anchors if (anchor := _split_anchor(raw))},
            key=lambda item: (-len(item), item),
        )
    )
    return cleaned or None


def supports_candidate_records(segmenter: Segmenter) -> bool:
    if isinstance(segmenter, JsonLineSegmenter):
        return True
    if isinstance(segmenter, RawTextSegmenter):
        return segmenter.mode in {"line", "paragraph", "window"}
    if isinstance(segmenter, FormatSegmenter):
        return not bool(segmenter.continuation)
    if isinstance(segmenter, RegexSegmenter):
        return True
    return False


def _anchor_regex(matcher: Matcher, anchors: Sequence[str]) -> re.Pattern[str]:
    flags = 0
    if matcher.regex is not None:
        flags = matcher.regex.flags & (re.IGNORECASE | re.ASCII)
    return re.compile("|".join(re.escape(anchor) for anchor in anchors), flags)


def scan_candidate_lines(
    path: Path,
    matcher: Matcher,
    *,
    encoding: str = "utf-8",
) -> Optional[CandidateScan]:
    """Scan raw physical lines before any logical record construction.

    None means the caller must use the old path. An empty line_numbers set means
    Core proved there cannot be a match and can return zero hits without
    invoking the segmenter.
    """
    anchors = candidate_anchors(matcher)
    if not anchors:
        return None
    line_numbers: Set[int] = set()
    total_lines = 0
    literal_matcher = matcher if matcher.terms is not None else None
    anchor_re = None if literal_matcher is not None else _anchor_regex(matcher, anchors)
    with Path(path).open("r", encoding=encoding, errors="replace") as handle:
        for total_lines, line in enumerate(handle, start=1):
            matched = (
                literal_matcher.match(line)[0]
                if literal_matcher is not None
                else bool(anchor_re and anchor_re.search(line))
            )
            if matched:
                line_numbers.add(total_lines)
                if len(line_numbers) > _MAX_CANDIDATE_LINES:
                    return None
            if (
                total_lines >= _MIN_RATIO_SAMPLE_LINES
                and len(line_numbers) / total_lines > _MAX_CANDIDATE_RATIO
            ):
                return None
    return CandidateScan(
        line_numbers=frozenset(line_numbers),
        total_lines=total_lines,
        anchors=tuple(anchors),
        strategy="literal" if literal_matcher is not None else "required-literal",
    )


def _records_from_numbered_lines(
    segmenter: Segmenter,
    rows: List[Tuple[int, str]],
) -> Iterator[Record]:
    if not rows:
        return
    yield from segmenter.segment_lines(iter(rows))


def _iter_selected_independent_lines(
    path: Path,
    segmenter: Segmenter,
    candidates: Set[int],
    *,
    encoding: str,
) -> Iterator[Record]:
    with Path(path).open("r", encoding=encoding, errors="replace") as handle:
        for line_number, line in enumerate(handle, start=1):
            if line_number not in candidates:
                continue
            yield from _records_from_numbered_lines(segmenter, [(line_number, line)])


def _iter_raw_windows(
    path: Path,
    segmenter: RawTextSegmenter,
    candidates: Set[int],
    *,
    encoding: str,
) -> Iterator[Record]:
    starts = {
        ((line_number - 1) // segmenter.window) * segmenter.window + 1
        for line_number in candidates
    }
    if not starts:
        return
    rows: List[Tuple[int, str]] = []
    current_start: Optional[int] = None
    with Path(path).open("r", encoding=encoding, errors="replace") as handle:
        for line_number, line in enumerate(handle, start=1):
            window_start = ((line_number - 1) // segmenter.window) * segmenter.window + 1
            if window_start not in starts:
                continue
            if current_start is None:
                current_start = window_start
            if window_start != current_start:
                yield from _records_from_numbered_lines(segmenter, rows)
                rows = []
                current_start = window_start
            rows.append((line_number, line))
    if rows:
        yield from _records_from_numbered_lines(segmenter, rows)


def _iter_raw_paragraphs(
    path: Path,
    segmenter: RawTextSegmenter,
    candidates: Set[int],
    *,
    encoding: str,
) -> Iterator[Record]:
    pending: List[Tuple[int, str]] = []
    contains_candidate = False
    with Path(path).open("r", encoding=encoding, errors="replace") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                if pending and contains_candidate:
                    yield from _records_from_numbered_lines(segmenter, pending)
                pending = []
                contains_candidate = False
                continue
            pending.append((line_number, line))
            contains_candidate = contains_candidate or line_number in candidates
    if pending and contains_candidate:
        yield from _records_from_numbered_lines(segmenter, pending)


def _iter_start_delimited_candidates(
    path: Path,
    segmenter: Segmenter,
    candidates: Set[int],
    *,
    encoding: str,
) -> Iterator[Record]:
    """Scan boundaries, constructing Record objects only for candidate records."""
    pattern = getattr(segmenter, "pattern", None)
    if pattern is None:
        return
    candidate_record = False
    pending_start = 1
    pending_rows: Optional[List[Tuple[int, str]]] = None
    # Keep only one raw record prefix at a time. We deliberately avoid invoking
    # the segmenter's Record construction for non-candidates; the prefix is
    # needed only so a hit on a continuation line can recover its record header.
    prefix_rows: List[Tuple[int, str]] = []
    with Path(path).open("r", encoding=encoding, errors="replace") as handle:
        for line_number, line in enumerate(handle, start=1):
            is_start = bool(pattern.match(line))
            if is_start and line_number != pending_start:
                if candidate_record and pending_rows is not None:
                    yield from _records_from_numbered_lines(segmenter, pending_rows)
                pending_start = line_number
                candidate_record = False
                pending_rows = None
                prefix_rows = []

            if pending_rows is not None:
                pending_rows.append((line_number, line))
            else:
                prefix_rows.append((line_number, line))

            if line_number in candidates and not candidate_record:
                candidate_record = True
                pending_rows = prefix_rows
                prefix_rows = []

        if candidate_record and pending_rows is not None:
            yield from _records_from_numbered_lines(segmenter, pending_rows)


def iter_candidate_records(
    path: Path,
    segmenter: Segmenter,
    candidate_lines: Iterable[int],
    *,
    encoding: str = "utf-8",
) -> Iterator[Record]:
    """Yield only logical records intersecting previously located candidates."""
    candidates = set(int(item) for item in candidate_lines)
    if not candidates:
        return

    if isinstance(segmenter, JsonLineSegmenter):
        yield from _iter_selected_independent_lines(
            path, segmenter, candidates, encoding=encoding
        )
        return
    if isinstance(segmenter, RawTextSegmenter):
        if segmenter.mode == "line":
            yield from _iter_selected_independent_lines(
                path, segmenter, candidates, encoding=encoding
            )
        elif segmenter.mode == "window":
            yield from _iter_raw_windows(path, segmenter, candidates, encoding=encoding)
        else:
            yield from _iter_raw_paragraphs(path, segmenter, candidates, encoding=encoding)
        return
    if isinstance(segmenter, FormatSegmenter) and not segmenter.multiline:
        yield from _iter_selected_independent_lines(
            path, segmenter, candidates, encoding=encoding
        )
        return
    if isinstance(segmenter, (FormatSegmenter, RegexSegmenter)):
        yield from _iter_start_delimited_candidates(
            path, segmenter, candidates, encoding=encoding
        )
        return
    raise TypeError(f"segmenter does not support candidate records: {type(segmenter).__name__}")
